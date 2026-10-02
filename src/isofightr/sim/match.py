"""``Match``: ``tick()``, rules, stocks and the per-tick event list.

Plan note "02 - Technical Architecture" ("Order of operations inside ``Match.tick()``",
"Entity model", "Determinism rules"). A match is driven only by one ``InputFrame`` per player
per tick; the same inputs and seed always produce the same :meth:`Match.state_hash`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from isofightr.sim import physics
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat.constants import MAX_DAMAGE, SHIELD_MAX_HP, SHIELD_REGEN
from isofightr.sim.combat.grab_resolution import resolve_grabs
from isofightr.sim.combat.hit_resolution import resolve_hits, step_hitlag
from isofightr.sim.combat.projectile_hits import resolve_projectile_hits
from isofightr.sim.constants import DEFAULT_STOCKS, PUSH_HEIGHT_TOLERANCE, PUSH_SPEED
from isofightr.sim.events import Event, KoEvent, LandEvent, ProjectileEvent
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Dir8, InputFrame, facing_from_move
from isofightr.sim.math3d import EPSILON, Box3, Vec2, Vec3
from isofightr.sim.move_def import ProjectileDef
from isofightr.sim.projectile import Projectile, spawn
from isofightr.sim.projectile import step as step_projectile
from isofightr.sim.rng import Rng
from isofightr.sim.stage import Stage
from isofightr.sim.states import STATES, change_state
from isofightr.sim.states.ledge import try_grab_ledge

HASH_DECIMALS: Final[int] = 6
"""Floats are rounded to this many decimals in the state hash (plan note 16, "State hash")."""
HASH_BYTES: Final[int] = 16
_PUSHABLE: Final[frozenset[GroundKind]] = frozenset({GroundKind.CELL, GroundKind.PLATFORM})


@dataclass(frozen=True, slots=True)
class MatchRules:
    """The rules of a match. Timers, teams and the rest arrive in M6."""

    stocks: int | None = DEFAULT_STOCKS
    """Stocks per fighter, or ``None`` for infinite (training)."""
    parry: bool = False
    """Whether a hit in the first frames of dropping shield is parried (optional rule)."""
    air_dodge_helpless: bool = False
    """Whether a directional air dodge ends in the helpless fall (optional rule)."""


@dataclass(slots=True)
class Match:
    """The whole simulation: a stage, its fighters, a seeded RNG and a frame counter."""

    stage: Stage
    fighters: list[Fighter]
    rng: Rng
    rules: MatchRules = field(default_factory=MatchRules)
    frame: int = 0
    events: list[Event] = field(default_factory=list)
    """Events emitted by the latest tick, for presentation and audio. Replaced every tick."""
    projectiles: list[Projectile] = field(default_factory=list)
    """Projectiles in flight, oldest first."""
    next_projectile_id: int = 0

    @classmethod
    def create(
        cls,
        stage: Stage,
        characters: Sequence[CharacterDef],
        seed: int = 0,
        rules: MatchRules | None = None,
    ) -> Match:
        """Start a match with one fighter per character, standing on the spawn points."""
        if not 1 <= len(characters) <= len(stage.spawns):
            raise ValueError(
                f"a match needs 1 to {len(stage.spawns)} fighters, got {len(characters)}"
            )
        rules = rules or MatchRules()
        centre = stage.respawn_point()
        fighters = []
        for index, character in enumerate(characters):
            pos = stage.spawn_point(index)
            facing = facing_from_move((centre - pos).xy) or Dir8.SE
            fighters.append(
                Fighter(
                    player_index=index,
                    character=character,
                    pos=pos,
                    facing=facing,
                    air_jumps_left=character.movement.air_jumps,
                    stocks=rules.stocks,
                )
            )
        return cls(stage=stage, fighters=fighters, rng=Rng.seeded(seed), rules=rules)

    def tick(self, inputs: Sequence[InputFrame]) -> None:
        """Advance the simulation by exactly one frame.

        ``inputs`` holds one frame per fighter, in player index order. The order of
        operations follows the plan note 02; steps for systems that do not exist yet (hitlag,
        move scripts, projectiles, hit resolution, match rules) are marked where they will go.
        """
        if len(inputs) != len(self.fighters):
            raise ValueError(f"expected {len(self.fighters)} input frames, got {len(inputs)}")
        self.frame += 1
        self.events = []

        # 1. Input.
        for fighter, frame in zip(self.fighters, inputs, strict=True):
            fighter.buffer.push(frame)

        # 2. Hitlag: frozen fighters read SDI, launch when it ends, and skip steps 3 to 5.
        frozen = {fighter.player_index for fighter in self.fighters if fighter.hitlag > 0}
        for fighter in self.fighters:
            if fighter.player_index in frozen:
                step_hitlag(self, fighter)

        # 3. State machine.
        for fighter in self.fighters:
            if fighter.player_index in frozen:
                continue
            self._upkeep(fighter)
            fighter.state_frame += 1
            STATES[fighter.state].step(self, fighter)

        # 4. Move scripts: hitbox windows and scripted motion are read from the move data
        #    by the Attack state and by hit resolution. Special-move scripts arrive in M5.

        # 5. Physics.
        for fighter in self.fighters:
            if fighter.player_index in frozen:
                continue
            physics.decay_knockback(fighter)
            state = STATES[fighter.state]
            state.motion(self, fighter)
            if state.uses_physics:
                result = physics.step(self.stage, fighter, state.stops_at_edges)
                self._apply(fighter, result)
                if not result.landed:
                    try_grab_ledge(self, fighter)
        self._push_fighters_apart()

        # 6. Projectiles fly.
        for projectile in self.projectiles:
            step_projectile(self.stage, projectile)

        # 7. Hit resolution, then grabs (a grabber that was just hit does not grab).
        resolve_hits(self)
        resolve_projectile_hits(self)
        resolve_grabs(self)
        self._clear_dead_projectiles()

        # 8. Blast zones.
        for fighter in self.fighters:
            if fighter.in_play and not self.stage.blast_zone.contains(fighter.pos):
                self._knock_out(fighter)

        # 9. Rules: timer, game end, sudden death (M6).

    # --- training and debug tools ------------------------------------------------------------
    # The only ways anything outside the sim may change a running match besides input. They
    # exist for training mode, are never called during normal play, and keep the match valid.

    def set_damage(self, player_index: int, percent: float) -> None:
        """Set a fighter's damage percent (training mode)."""
        self.fighters[player_index].damage = min(max(percent, 0.0), MAX_DAMAGE)

    def reload_characters(self, characters: Sequence[CharacterDef]) -> None:
        """Swap in freshly loaded character data, one per fighter (F9 hot reload).

        A fighter in the middle of a move that no longer exists drops out of it.
        """
        if len(characters) != len(self.fighters):
            raise ValueError(f"expected {len(self.fighters)} characters, got {len(characters)}")
        for fighter, character in zip(self.fighters, characters, strict=True):
            fighter.character = character
            if fighter.state is StateId.ATTACK and fighter.move_id not in character.moves:
                change_state(self, fighter, StateId.IDLE if fighter.grounded else StateId.FALL)

    def state_hash(self) -> str:
        """Return a stable hash of all sim state.

        Used by determinism tests and golden replays now, and by rollback desync detection
        later. Floats are rounded so the hash does not depend on print formatting.
        """
        digest = hashlib.blake2b(digest_size=HASH_BYTES)
        digest.update(repr(self._canonical()).encode())
        return digest.hexdigest()

    # --- internals -------------------------------------------------------------------------

    def spawn_projectile(
        self, owner: Fighter, definition: ProjectileDef, damage: float
    ) -> Projectile:
        """Add a projectile fired by ``owner``'s current move, and return it."""
        projectile = spawn(self.next_projectile_id, owner, definition, damage)
        self.next_projectile_id += 1
        self.projectiles.append(projectile)
        self.events.append(ProjectileEvent(owner.player_index, projectile.pos, spawned=True))
        return projectile

    def _clear_dead_projectiles(self) -> None:
        for projectile in self.projectiles:
            if not projectile.alive:
                self.events.append(ProjectileEvent(projectile.owner, projectile.pos, spawned=False))
        self.projectiles = [projectile for projectile in self.projectiles if projectile.alive]

    def _upkeep(self, fighter: Fighter) -> None:
        """Run a fighter's per-frame timers (start of tick step 3; frozen fighters skip it)."""
        if fighter.invincible_frames > 0:
            fighter.invincible_frames -= 1
        if fighter.intangible_frames > 0:
            fighter.intangible_frames -= 1
        if fighter.ledge_cooldown > 0:
            fighter.ledge_cooldown -= 1
        if fighter.tech_window > 0:
            fighter.tech_window -= 1
        if fighter.tech_lockout > 0:
            fighter.tech_lockout -= 1
        if fighter.dodge_stale_timer > 0:
            fighter.dodge_stale_timer -= 1
            if fighter.dodge_stale_timer == 0:
                fighter.dodge_stale = 0
        if STATES[fighter.state].regens_shield:
            fighter.shield_hp = min(SHIELD_MAX_HP, fighter.shield_hp + SHIELD_REGEN)
        fighter.air_frames = 0 if fighter.grounded else fighter.air_frames + 1

    def _apply(self, fighter: Fighter, result: physics.StepResult) -> None:
        """Turn what physics found into state changes and events."""
        if result.landed:
            fighter.air_dodge_used = False
            fighter.ledge_grabs = 0
            fighter.air_moves_used = []
            self.events.append(LandEvent(fighter.player_index, fighter.pos, result.fall_speed))
            STATES[fighter.state].on_land(self, fighter)
        elif result.left_ground:
            STATES[fighter.state].on_leave_ground(self, fighter)
        elif result.wall_normal is not None:
            STATES[fighter.state].on_wall(self, fighter, result.wall_normal, result.wall_knockback)

    def _push_fighters_apart(self) -> None:
        """Gently separate grounded fighters whose bodies overlap (plan note 04, pushboxes).

        All pushes are worked out from the positions before any is applied, so the result
        does not depend on the order fighters are visited in.
        """
        pushes: list[Vec2] = [Vec2() for _ in self.fighters]
        for first_index, first in enumerate(self.fighters):
            for second in self.fighters[first_index + 1 :]:
                if first.ground not in _PUSHABLE or second.ground not in _PUSHABLE:
                    continue
                if not (STATES[first.state].uses_physics and STATES[second.state].uses_physics):
                    continue  # a held fighter is placed by its grabber
                if abs(first.pos.z - second.pos.z) > PUSH_HEIGHT_TOLERANCE:
                    continue
                gap = (second.pos - first.pos).xy
                reach = first.character.body.radius + second.character.body.radius
                if gap.length() >= reach:
                    continue
                # Exactly on top of each other: split along world x, lower index first.
                away = gap.normalized() if gap.length() > EPSILON else Vec2(1.0, 0.0)
                pushes[first.player_index] = pushes[first.player_index] - away * PUSH_SPEED
                pushes[second.player_index] = pushes[second.player_index] + away * PUSH_SPEED
        for fighter, push in zip(self.fighters, pushes, strict=True):
            if push != Vec2():
                stop = STATES[fighter.state].stops_at_edges
                self._apply(fighter, physics.nudge_grounded(self.stage, fighter, push, stop))

    def _knock_out(self, fighter: Fighter) -> None:
        """Take a stock from a fighter that crossed a blast zone and send it to respawn."""
        position, normal = _blast_crossing(self.stage.blast_zone, fighter.pos)
        if fighter.stocks is not None:
            fighter.stocks -= 1
        self.events.append(KoEvent(fighter.player_index, position, normal, fighter.stocks))
        change_state(self, fighter, StateId.KO)

    def _canonical(self) -> tuple[object, ...]:
        return (
            self.frame,
            self.stage.id,
            self.rng.state,
            self.rng.increment,
            tuple(_canonical_fighter(fighter) for fighter in self.fighters),
            self.next_projectile_id,
            tuple(_canonical_projectile(projectile) for projectile in self.projectiles),
        )


def _blast_crossing(zone: Box3, pos: Vec3) -> tuple[Vec3, Vec3]:
    """Return where a position left the blast-zone box, and that face's outward normal.

    If the position is outside on several axes, the face it is furthest beyond wins.
    """
    overshoots = (
        (zone.x_min - pos.x, Vec3(-1.0, 0.0, 0.0)),
        (pos.x - zone.x_max, Vec3(1.0, 0.0, 0.0)),
        (zone.y_min - pos.y, Vec3(0.0, -1.0, 0.0)),
        (pos.y - zone.y_max, Vec3(0.0, 1.0, 0.0)),
        (zone.z_min - pos.z, Vec3(0.0, 0.0, -1.0)),
        (pos.z - zone.z_max, Vec3(0.0, 0.0, 1.0)),
    )
    normal = max(overshoots, key=lambda entry: entry[0])[1]
    clamped = Vec3(
        min(max(pos.x, zone.x_min), zone.x_max),
        min(max(pos.y, zone.y_min), zone.y_max),
        min(max(pos.z, zone.z_min), zone.z_max),
    )
    return clamped, normal


def _round(value: float) -> float:
    return round(value, HASH_DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0


def _canonical_vec2(vector: Vec2) -> tuple[float, float]:
    return (_round(vector.x), _round(vector.y))


def _canonical_vec3(vector: Vec3) -> tuple[float, float, float]:
    return (_round(vector.x), _round(vector.y), _round(vector.z))


def _canonical_projectile(projectile: Projectile) -> tuple[object, ...]:
    return (
        projectile.id,
        projectile.owner,
        projectile.move_id,
        _canonical_vec3(projectile.pos),
        _canonical_vec3(projectile.previous),
        _canonical_vec3(projectile.vel),
        _round(projectile.damage),
        projectile.lifetime,
        projectile.age,
        projectile.pierce_left,
        tuple(projectile.hit),
    )


def _canonical_fighter(fighter: Fighter) -> tuple[object, ...]:
    buffer = fighter.buffer
    return (
        fighter.player_index,
        fighter.character.id,
        _canonical_vec3(fighter.pos),
        _canonical_vec3(fighter.vel),
        _canonical_vec3(fighter.kb_vel),
        int(fighter.facing),
        fighter.state.value,
        fighter.state_frame,
        int(fighter.ground),
        fighter.platform,
        fighter.drop_platform,
        fighter.air_jumps_left,
        fighter.fast_falling,
        _canonical_vec2(fighter.drive),
        _round(fighter.damage),
        fighter.stocks,
        fighter.invincible_frames,
        fighter.land_lag,
        fighter.move_id,
        fighter.charge_frames,
        tuple(sorted(fighter.hit_log.items())),
        fighter.move_connected,
        _round(fighter.move_stale),
        tuple(
            (key, _canonical_vec3(value)) for key, value in sorted(fighter.hitbox_centres.items())
        ),
        fighter.hitlag,
        fighter.hitstun,
        None
        if fighter.launch is None
        else (
            _round(fighter.launch.knockback),
            _canonical_vec2(fighter.launch.heading),
            _round(fighter.launch.elevation),
            fighter.launch.tumble,
            _canonical_vec3(fighter.launch.carry),
        ),
        _round(fighter.sdi_mult),
        tuple(fighter.stale_queue),
        _round(fighter.last_knockback),
        _round(fighter.shield_hp),
        fighter.intangible_frames,
        fighter.stun_frames,
        fighter.air_dodge_used,
        _canonical_vec3(fighter.dodge_dir),
        fighter.dodge_stale,
        fighter.dodge_stale_timer,
        fighter.dodge_lag,
        fighter.grab_partner,
        fighter.grab_timer,
        fighter.pummel_cooldown,
        fighter.throw_id,
        fighter.ledge,
        _canonical_vec2(fighter.ledge_point),
        fighter.ledge_cooldown,
        fighter.ledge_grabs,
        fighter.air_frames,
        fighter.tech_window,
        fighter.tech_lockout,
        _round(fighter.counter_damage),
        tuple(fighter.air_moves_used),
        _canonical_vec2(buffer.frame.move),
        buffer.frame.vertical,
        buffer.frame.held,
        None if buffer.frame.cstick is None else _canonical_vec2(buffer.frame.cstick),
        buffer.pressed,
        buffer.released,
        tuple(buffer.ages),
        tuple(_canonical_vec2(move) for move in buffer.history),
    )
