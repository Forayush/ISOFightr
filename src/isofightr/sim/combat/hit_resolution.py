"""Gathers overlaps, resolves priority and clanks, then applies all hits simultaneously.

Plan note "05 - Combat Core" ("Hit resolution"). This runs once per tick after physics, on
this tick's positions. Every hit is worked out before any is applied, so two fighters that
hit each other on the same frame trade.

Also here: applying a hit's launch when the target's hitlag ends (with DI), and SDI.
Shields, grabs, armor and counters join the target-state checks in M4 and M5.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb_math
from isofightr.sim.combat.hitbox import (
    ActiveHitbox,
    active_hitboxes,
    hitboxes_touch,
    hits,
    remember_hitboxes,
)
from isofightr.sim.combat.staling import push_stale
from isofightr.sim.events import ClankEvent, HitEvent
from isofightr.sim.fighter import Fighter, GroundKind, Launch, StateId
from isofightr.sim.input_frame import VERTICAL_NONE, Press
from isofightr.sim.math3d import ZERO2, Vec2, Vec3
from isofightr.sim.move_def import DirectionMode, HitboxDef
from isofightr.sim.states.base import change_state

if TYPE_CHECKING:
    from isofightr.sim.match import Match

AUTOLINK_DISTANCE = 1.0
"""Autolink hits pull toward a point this far in front of the attacker, in units."""


@dataclass(frozen=True, slots=True)
class _Hit:
    attacker: Fighter
    target: Fighter
    box: ActiveHitbox


def charge_multiplier(fighter: Fighter) -> float:
    """Return the damage multiplier from charging the current smash attack."""
    move = fighter.move
    if move is None or move.charge is None:
        return 1.0
    charged = fighter.charge_frames / move.charge.max_frames
    return 1.0 + (move.charge.damage_mult - 1.0) * charged


def hit_damage(attacker: Fighter, definition: HitboxDef) -> float:
    """Return the damage a hitbox deals right now: base, times charge, times staling."""
    return definition.damage * charge_multiplier(attacker) * attacker.move_stale


def resolve_hits(match: Match) -> None:
    """Find and apply this tick's hits and clanks (tick step 7)."""
    boxes = {
        fighter.player_index: active_hitboxes(fighter) if fighter.in_play else []
        for fighter in match.fighters
    }
    found = [
        hit
        for attacker in match.fighters
        for target in match.fighters
        if (hit := _find_hit(attacker, target, boxes[attacker.player_index])) is not None
    ]
    clanks = _find_clanks(match, boxes, found)

    for fighter in match.fighters:
        remember_hitboxes(fighter, boxes[fighter.player_index])
    _apply_hits(match, found)
    for fighter, point in clanks:
        match.events.append(ClankEvent(fighter.player_index, point))
        change_state(match, fighter, StateId.REBOUND)


def _find_hit(attacker: Fighter, target: Fighter, boxes: list[ActiveHitbox]) -> _Hit | None:
    """Return the highest-priority hitbox of ``attacker`` that connects with ``target``."""
    if attacker is target or not target.in_play or target.ground is GroundKind.REVIVAL:
        return None
    frame = attacker.state_frame
    for box in boxes:  # lowest id first
        definition = box.definition
        last = attacker.hit_log.get((target.player_index, definition.group))
        if last is not None and (definition.rehit == 0 or frame - last < definition.rehit):
            continue
        if not (definition.hits_ground if target.grounded else definition.hits_air):
            continue
        if hits(box, target):
            return _Hit(attacker, target, box)
    return None


def _find_clanks(
    match: Match, boxes: dict[int, list[ActiveHitbox]], found: list[_Hit]
) -> list[tuple[Fighter, Vec3]]:
    """Return the fighters whose attacks are stopped by clashing with another attack.

    Two attacks clank when their hitboxes touch and neither fighter was hit by the other
    this tick. If their damage differs by less than ``CLANK_DAMAGE_WINDOW`` both rebound;
    otherwise only the weaker one does. Aerials (``clank = false``) pass through.
    """
    landed = {(hit.attacker.player_index, hit.target.player_index) for hit in found}
    rebounds: dict[int, Vec3] = {}
    for index, first in enumerate(match.fighters):
        for second in match.fighters[index + 1 :]:
            pair = (first.player_index, second.player_index)
            if pair in landed or pair[::-1] in landed:
                continue
            clash = _strongest_clash(first, second, boxes)
            if clash is None:
                continue
            first_damage, second_damage, point = clash
            difference = first_damage - second_damage
            if difference < c.CLANK_DAMAGE_WINDOW:
                rebounds[first.player_index] = point
            if -difference < c.CLANK_DAMAGE_WINDOW:
                rebounds[second.player_index] = point
    return [(match.fighters[index], point) for index, point in sorted(rebounds.items())]


def _strongest_clash(
    first: Fighter, second: Fighter, boxes: dict[int, list[ActiveHitbox]]
) -> tuple[float, float, Vec3] | None:
    best: tuple[float, float, Vec3] | None = None
    for own in boxes[first.player_index]:
        for other in boxes[second.player_index]:
            if not (own.definition.clank and other.definition.clank):
                continue
            if not hitboxes_touch(own, other):
                continue
            damages = (hit_damage(first, own.definition), hit_damage(second, other.definition))
            if best is None or sum(damages) > best[0] + best[1]:
                best = (*damages, (own.centre + other.centre) / 2)
    return best


def _apply_hits(match: Match, found: list[_Hit]) -> None:
    """Apply every hit of this tick. Results are computed from the state before any hit."""
    grounded = {fighter.player_index: fighter.grounded for fighter in match.fighters}
    frames = {fighter.player_index: fighter.state_frame for fighter in match.fighters}
    damages = [hit_damage(hit.attacker, hit.box.definition) for hit in found]
    full_charges = [
        (move := hit.attacker.move) is not None
        and move.charge is not None
        and hit.attacker.charge_frames >= move.charge.max_frames
        for hit in found
    ]
    headings = [_heading(hit) for hit in found]

    for hit, damage, full_charge, heading in zip(
        found, damages, full_charges, headings, strict=True
    ):
        attacker, target, definition = hit.attacker, hit.target, hit.box.definition
        attacker.hit_log[(target.player_index, definition.group)] = frames[attacker.player_index]
        if not attacker.move_connected:
            attacker.move_connected = True
            push_stale(attacker.stale_queue, attacker.move_id)

        hitlag = kb_math.hitlag_frames(
            damage, definition.hitlag_mult, definition.effect, full_charge
        )
        attacker.hitlag = max(attacker.hitlag, hitlag)
        target.hitlag = max(target.hitlag, hitlag)

        knockback = 0.0
        if not target.invincible:
            target.damage = min(target.damage + damage, c.MAX_DAMAGE)
            knockback = kb_math.knockback(
                target.damage,
                damage,
                target.character.weight,
                definition.bkb,
                definition.kbg,
                definition.fkb,
            )
            was_grounded = grounded[target.player_index]
            launch = Launch(
                knockback=knockback,
                heading=heading,
                elevation=kb_math.resolve_elevation(definition.angle, knockback, was_grounded),
                tumble=kb_math.is_tumble(knockback)
                or kb_math.meteor_tumbles(definition.angle, knockback, was_grounded),
            )
            # Hit by several fighters at once: the strongest launch wins, all damage counts.
            if target.launch is None or launch.knockback >= target.launch.knockback:
                target.launch = launch
                target.sdi_mult = definition.sdi_mult
            target.last_knockback = knockback
        match.events.append(
            HitEvent(
                attacker=attacker.player_index,
                target=target.player_index,
                move_id=attacker.move_id,
                damage=0.0 if target.invincible else damage,
                knockback=knockback,
                position=hit.box.centre,
                effect=definition.effect,
                hitlag=hitlag,
            )
        )


def _heading(hit: _Hit) -> Vec2:
    """Return the horizontal launch direction of a hit, before DI."""
    attacker, target, definition = hit.attacker, hit.target, hit.box.definition
    facing = attacker.facing.world
    if definition.direction_mode is DirectionMode.RADIAL:
        away = (target.pos - hit.box.centre).xy.normalized()
        return facing if away == ZERO2 else away
    if definition.direction_mode is DirectionMode.AUTOLINK:
        point = attacker.pos.xy + facing * AUTOLINK_DISTANCE
        toward = (point - target.pos.xy).normalized()
        return facing if toward == ZERO2 else toward
    return facing.rotated(definition.yaw)


# --- hitlag: SDI and the launch ------------------------------------------------------------


def step_hitlag(match: Match, fighter: Fighter) -> None:
    """Run one frozen frame for a fighter in hitlag (tick step 2).

    A target can nudge itself with SDI on each new stick or modifier input. On the last
    frame of hitlag the launch is applied, bent by whatever the target is holding (DI).
    """
    if fighter.launch is not None:
        _smash_di(match, fighter)
    fighter.hitlag -= 1
    if fighter.hitlag == 0 and fighter.launch is not None:
        _launch(match, fighter, fighter.launch)
        fighter.launch = None


def _smash_di(match: Match, fighter: Fighter) -> None:
    buffer = fighter.buffer
    distance = c.SDI_DISTANCE * fighter.sdi_mult
    if buffer.stick_active and buffer.consume(Press.FLICK):
        physics.shift(match.stage, fighter, buffer.move.normalized() * distance)
    if not fighter.grounded:
        if buffer.consume(Press.UP):
            fighter.pos = fighter.pos + Vec3(0.0, 0.0, distance)
        elif buffer.consume(Press.DOWN):
            fighter.pos = fighter.pos - Vec3(0.0, 0.0, distance)


def _launch(match: Match, fighter: Fighter, launch: Launch) -> None:
    """Send a fighter flying: set knockback velocity, hitstun and the hurt state."""
    buffer = fighter.buffer
    stick = buffer.move if buffer.stick_active else ZERO2
    heading, elevation = kb_math.apply_di(launch.heading, launch.elevation, stick, buffer.vertical)
    if fighter.grounded and elevation < 0.0:
        elevation = 0.0  # DI cannot push a standing fighter into the floor
    direction = kb_math.launch_vector(heading, elevation)
    fighter.kb_vel = direction * kb_math.launch_speed(launch.knockback)
    kept = fighter.vel.xy * c.LAUNCH_SELF_VELOCITY_KEEP
    fighter.vel = Vec3(kept.x, kept.y, 0.0)
    fighter.hitstun = kb_math.hitstun_frames(launch.knockback)
    fighter.fast_falling = False
    if direction.z > 0.0 and fighter.grounded:
        fighter.ground = GroundKind.NONE
        fighter.platform = -1
    # Down held at launch is DI, not a fast-fall or platform-drop request.
    if buffer.vertical != VERTICAL_NONE:
        buffer.consume(Press.DOWN)
        buffer.consume(Press.UP)
    airborne_tumble = launch.tumble and not fighter.grounded
    change_state(match, fighter, StateId.TUMBLE if airborne_tumble else StateId.FLINCH)
