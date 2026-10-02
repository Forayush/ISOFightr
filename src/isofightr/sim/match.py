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
from isofightr.sim.constants import DEFAULT_STOCKS, PUSH_HEIGHT_TOLERANCE, PUSH_SPEED
from isofightr.sim.events import Event, KoEvent, LandEvent
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Dir8, InputFrame, facing_from_move
from isofightr.sim.math3d import EPSILON, Box3, Vec2, Vec3
from isofightr.sim.rng import Rng
from isofightr.sim.stage import Stage
from isofightr.sim.states import STATES, change_state

HASH_DECIMALS: Final[int] = 6
"""Floats are rounded to this many decimals in the state hash (plan note 16, "State hash")."""
HASH_BYTES: Final[int] = 16
_PUSHABLE: Final[frozenset[GroundKind]] = frozenset({GroundKind.CELL, GroundKind.PLATFORM})


@dataclass(frozen=True, slots=True)
class MatchRules:
    """The rules of a match. Timers, teams and the rest arrive in M6."""

    stocks: int | None = DEFAULT_STOCKS
    """Stocks per fighter, or ``None`` for infinite (training)."""


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

        # 2. Hitlag (M3).

        # 3. State machine.
        for fighter in self.fighters:
            if fighter.invincible_frames > 0:
                fighter.invincible_frames -= 1
            fighter.state_frame += 1
            STATES[fighter.state].step(self, fighter)

        # 4. Move scripts (M3).

        # 5. Physics.
        for fighter in self.fighters:
            STATES[fighter.state].motion(self, fighter)
            self._apply(fighter, physics.step(self.stage, fighter))
        self._push_fighters_apart()

        # 6. Projectiles (M5). 7. Hit resolution (M3).

        # 8. Blast zones.
        for fighter in self.fighters:
            if fighter.in_play and not self.stage.blast_zone.contains(fighter.pos):
                self._knock_out(fighter)

        # 9. Rules: timer, game end, sudden death (M6).

    def state_hash(self) -> str:
        """Return a stable hash of all sim state.

        Used by determinism tests and golden replays now, and by rollback desync detection
        later. Floats are rounded so the hash does not depend on print formatting.
        """
        digest = hashlib.blake2b(digest_size=HASH_BYTES)
        digest.update(repr(self._canonical()).encode())
        return digest.hexdigest()

    # --- internals -------------------------------------------------------------------------

    def _apply(self, fighter: Fighter, result: physics.StepResult) -> None:
        """Turn what physics found into state changes and events."""
        if result.landed:
            self.events.append(LandEvent(fighter.player_index, fighter.pos, result.fall_speed))
            change_state(self, fighter, StateId.LAND)
        elif result.left_ground:
            change_state(self, fighter, StateId.FALL)

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
                self._apply(fighter, physics.nudge_grounded(self.stage, fighter, push))

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
        _canonical_vec2(buffer.frame.move),
        buffer.frame.vertical,
        buffer.frame.held,
        None if buffer.frame.cstick is None else _canonical_vec2(buffer.frame.cstick),
        buffer.pressed,
        buffer.released,
        tuple(buffer.ages),
        tuple(_canonical_vec2(move) for move in buffer.history),
    )
