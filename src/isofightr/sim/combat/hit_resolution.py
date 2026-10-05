"""Gathers overlaps, resolves priority and clanks, then applies all hits simultaneously.

Plan note "05 - Combat Core" ("Hit resolution"). This runs once per tick after physics, on
this tick's positions. Every hit is worked out before any is applied, so two fighters that
hit each other on the same frame trade.

Also here: applying a hit's launch when the target's hitlag ends (with DI), and SDI.
Shields, grabs, armor and counters join the target-state checks in M4 and M5.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb_math
from isofightr.sim.combat.hitbox import (
    ActiveHitbox,
    active_hitboxes,
    hit_damage,
    hitboxes_touch,
    hits,
    remember_hitboxes,
)
from isofightr.sim.combat.shield import (
    is_shielding,
    shield_damage,
    shield_push_speed,
    shield_volume,
    shieldstun_frames,
)
from isofightr.sim.combat.staling import push_stale
from isofightr.sim.events import ClankEvent, CounterEvent, HitEvent, ShieldHitEvent
from isofightr.sim.fighter import Fighter, GroundKind, Launch, StateId
from isofightr.sim.input_frame import VERTICAL_NONE, Press
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3, capsules_overlap
from isofightr.sim.move_def import DirectionMode, HitboxDef
from isofightr.sim.states.base import change_state
from isofightr.sim.states.interrupts import snap_facing, start_move

if TYPE_CHECKING:
    from isofightr.sim.match import Match

type Change = Callable[[], None]
"""A state change caused by a hit, applied after every hit of the tick is worked out."""


@dataclass(frozen=True, slots=True)
class _Hit:
    attacker: Fighter
    target: Fighter
    box: ActiveHitbox
    blocked: bool = False
    """The hitbox touched the target's shield."""
    parried: bool = False
    countered: bool = False


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
        if (hit := _find_hit(match, attacker, target, boxes[attacker.player_index])) is not None
    ]
    clanks = _find_clanks(match, boxes, found)

    for fighter in match.fighters:
        remember_hitboxes(fighter, boxes[fighter.player_index])
    _apply_hits(match, found)
    for fighter, point in clanks:
        match.events.append(ClankEvent(fighter.player_index, point))
        change_state(match, fighter, StateId.REBOUND)


def _find_hit(
    match: Match, attacker: Fighter, target: Fighter, boxes: list[ActiveHitbox]
) -> _Hit | None:
    """Return the highest-priority hitbox of ``attacker`` that connects with ``target``.

    A hitbox that touches a raised shield is blocked; one that reaches the hurtbox without
    touching the shield pokes through and hits normally.
    """
    if attacker is target or not target.in_play or target.ground is GroundKind.REVIVAL:
        return None
    if target.intangible:
        return None
    if attacker.allied_with(target) and not match.rules.friendly_fire:
        return None
    countering = counter_window_open(target)
    bubble = shield_volume(target) if is_shielding(target) else None
    parry = (
        match.rules.parry
        and target.state is StateId.SHIELD_DROP
        and target.state_frame <= c.PARRY_WINDOW
    )
    frame = attacker.state_frame
    for box in boxes:  # lowest id first
        definition = box.definition
        last = attacker.hit_log.get((target.player_index, definition.group))
        if last is not None and (definition.rehit == 0 or frame - last < definition.rehit):
            continue
        if not (definition.hits_ground if target.grounded else definition.hits_air):
            continue
        if bubble is not None and capsules_overlap(box.volume, bubble):
            return _Hit(attacker, target, box, blocked=True)
        if hits(box, target):
            return _Hit(attacker, target, box, parried=parry, countered=countering)
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
    damages = [
        hit_damage(hit.attacker, hit.box.definition) * team_multiplier(hit.attacker, hit.target)
        for hit in found
    ]
    full_charges = [
        (move := hit.attacker.move) is not None
        and move.charge is not None
        and hit.attacker.charge_frames >= move.charge.max_frames
        for hit in found
    ]
    headings = [_heading(hit) for hit in found]
    changes: list[Change] = []

    for hit, damage, full_charge, heading in zip(
        found, damages, full_charges, headings, strict=True
    ):
        attacker, target, definition = hit.attacker, hit.target, hit.box.definition
        attacker.hit_log[(target.player_index, definition.group)] = frames[attacker.player_index]
        if hit.countered:
            hitlag = kb_math.hitlag_frames(damage, definition.hitlag_mult, definition.effect)
            attacker.hitlag = max(attacker.hitlag, hitlag)
            target.hitlag = max(target.hitlag, hitlag)
            changes.append(partial(counter_reply, match, target, attacker, damage))
            continue
        if hit.blocked or hit.parried:
            state = _block(match, hit, damage, full_charge)
            changes.append(partial(change_state, match, target, state))
            continue
        attacker.dodge_stale = 0
        if not attacker.move_connected:
            attacker.move_connected = True
            push_stale(attacker.stale_queue, attacker.move_id)

        hitlag = kb_math.hitlag_frames(
            damage, definition.hitlag_mult, definition.effect, full_charge
        )
        attacker.hitlag = max(attacker.hitlag, hitlag)
        target.hitlag = max(target.hitlag, hitlag)

        invincible = target.invincible
        carry = attacker.vel if definition.direction_mode is DirectionMode.AUTOLINK else ZERO3
        knockback = strike(
            target,
            damage,
            definition,
            heading,
            grounded[target.player_index],
            carry,
            match.rules.launch_rate * team_multiplier(attacker, target),
        )
        match.events.append(
            HitEvent(
                attacker=attacker.player_index,
                target=target.player_index,
                move_id=attacker.move_id,
                damage=0.0 if invincible else damage,
                knockback=knockback,
                position=hit.box.centre,
                effect=definition.effect,
                hitlag=hitlag,
            )
        )
    for change in changes:
        change()


def team_multiplier(attacker: Fighter, target: Fighter) -> float:
    """Return the damage and knockback multiplier for a hit: reduced between teammates."""
    return c.FRIENDLY_FIRE_MULT if attacker.allied_with(target) else 1.0


def strike(
    target: Fighter,
    damage: float,
    definition: HitboxDef,
    heading: Vec2,
    was_grounded: bool,
    carry: Vec3 = ZERO3,
    rate: float = 1.0,
) -> float:
    """Damage a fighter and queue its launch. Returns the knockback (0 if invincible).

    ``carry`` is added to the launch velocity (autolink hits pass the attacker's velocity).
    ``rate`` is the match's launch rate, a multiplier on all knockback.

    Armor on the target's current move frame lets the damage through but not the launch,
    unless the knockback reaches the armor's threshold.
    """
    if target.invincible:
        return 0.0
    target.damage = min(target.damage + damage, c.MAX_DAMAGE)
    knockback = kb_math.knockback(
        target.damage,
        damage,
        target.character.weight,
        definition.bkb,
        definition.kbg,
        definition.fkb,
        rate,
    )
    target.last_knockback = knockback
    move = target.move
    threshold = None if move is None else move.armor_threshold(target.state_frame)
    if threshold is not None and knockback < threshold:
        return knockback
    launch = Launch(
        knockback=knockback,
        heading=heading,
        elevation=kb_math.resolve_elevation(definition.angle, knockback, was_grounded),
        tumble=kb_math.is_tumble(knockback)
        or kb_math.meteor_tumbles(definition.angle, knockback, was_grounded),
        carry=carry,
    )
    # Hit several times at once: the strongest launch wins, all damage counts.
    if target.launch is None or launch.knockback >= target.launch.knockback:
        target.launch = launch
        target.sdi_mult = definition.sdi_mult
    return knockback


def counter_window_open(fighter: Fighter) -> bool:
    """Return whether the fighter is in the counter window of a counter move."""
    move = fighter.move
    return (
        move is not None
        and move.counter is not None
        and (fighter.state_frame in move.counter.frames)
    )


def counter_reply(
    match: Match, fighter: Fighter, attacker: Fighter | None, incoming: float
) -> None:
    """A counter caught a hit: turn toward the attacker and start the reply move, which
    deals at least the incoming damage times the counter's multiplier."""
    move = fighter.move
    if move is None or move.counter is None:
        return
    counter = move.counter
    if attacker is not None:
        snap_facing(fighter, (attacker.pos - fighter.pos).xy)
    match.events.append(CounterEvent(fighter.player_index, fighter.pos))
    start_move(match, fighter, counter.into)
    fighter.counter_damage = incoming * counter.damage_mult


def _block(match: Match, hit: _Hit, damage: float, full_charge: bool) -> StateId:
    """Apply a blocked (or parried) hit. Returns the state the defender goes to."""
    attacker, target, definition = hit.attacker, hit.target, hit.box.definition
    hitlag = kb_math.hitlag_frames(damage, definition.hitlag_mult, definition.effect, full_charge)
    target.hitlag = max(target.hitlag, hitlag)
    if hit.parried:
        attacker.hitlag = max(attacker.hitlag, hitlag + c.PARRY_EXTRA_HITLAG)
        match.events.append(
            ShieldHitEvent(
                attacker.player_index, target.player_index, 0.0, hit.box.centre, hitlag, True
            )
        )
        return StateId.IDLE

    attacker.hitlag = max(attacker.hitlag, hitlag)
    away = (target.pos - attacker.pos).xy.normalized()
    if away == ZERO2:
        away = attacker.facing.world
    state, taken = block_with_shield(target, damage, definition, away)
    if attacker.grounded:
        back = away * (-shield_push_speed(damage) * c.SHIELD_ATTACKER_PUSH)
        attacker.vel = Vec3(attacker.vel.x + back.x, attacker.vel.y + back.y, attacker.vel.z)
    match.events.append(
        ShieldHitEvent(
            attacker.player_index, target.player_index, taken, hit.box.centre, hitlag, False
        )
    )
    return state


def block_with_shield(
    target: Fighter, damage: float, definition: HitboxDef, away: Vec2, stun_mult: float = 1.0
) -> tuple[StateId, float]:
    """Take a hit on the shield: shield damage, shieldstun and pushback along ``away``.

    Returns the state the defender goes to and the shield damage taken.
    """
    taken = shield_damage(damage, definition.shield_damage)
    target.shield_hp -= taken
    stun = math.floor(shieldstun_frames(damage) * stun_mult)
    target.stun_frames = max(target.stun_frames, stun) if is_shielding(target) else stun
    push = away * shield_push_speed(damage)
    target.vel = Vec3(push.x, push.y, 0.0)
    state = StateId.SHIELD_BREAK if target.shield_hp <= 0.0 else StateId.SHIELD_STUN
    return state, taken


def _heading(hit: _Hit) -> Vec2:
    """Return the horizontal launch direction of a hit, before DI."""
    attacker, target, definition = hit.attacker, hit.target, hit.box.definition
    facing = attacker.facing.world
    if definition.direction_mode is DirectionMode.RADIAL:
        away = (target.pos - hit.box.centre).xy.normalized()
        return facing if away == ZERO2 else away
    if definition.direction_mode is DirectionMode.AUTOLINK:
        toward = (hit.box.centre.xy - target.pos.xy).normalized()
        return facing if toward == ZERO2 else toward
    return facing.rotated(definition.yaw)


# --- hitlag: SDI and the launch ------------------------------------------------------------


def step_hitlag(match: Match, fighter: Fighter) -> None:
    """Run one frozen frame for a fighter in hitlag (tick step 2).

    A target can nudge itself with SDI on each new stick or modifier input. On the last
    frame of hitlag whatever it is holding nudges it once more (ASDI), and then the launch is
    applied, bent by that same held input (DI).
    """
    if fighter.launch is not None:
        _smash_di(match, fighter)
    fighter.hitlag -= 1
    if fighter.hitlag == 0 and fighter.launch is not None:
        _automatic_sdi(match, fighter)
        _launch(match, fighter, fighter.launch)
        fighter.launch = None


def _smash_di(match: Match, fighter: Fighter) -> None:
    buffer = fighter.buffer
    distance = c.SDI_DISTANCE * fighter.sdi_mult
    if buffer.stick_active and buffer.consume(Press.FLICK):
        physics.shift(match.stage, fighter, buffer.move.normalized() * distance)
    if not fighter.grounded:
        if buffer.consume(Press.UP):
            _nudge_vertical(match, fighter, distance)
        elif buffer.consume(Press.DOWN):
            _nudge_vertical(match, fighter, -distance)


def _automatic_sdi(match: Match, fighter: Fighter) -> None:
    """ASDI: on the last hitlag frame the held stick (and, in the air, the held up or down
    modifier) nudges the target by ``ASDI_DISTANCE``. Holding is enough, and it does not use
    up SDI's flick (plan note 05, decision D-058)."""
    buffer = fighter.buffer
    distance = c.ASDI_DISTANCE * fighter.sdi_mult
    if buffer.stick_active:
        physics.shift(match.stage, fighter, buffer.move.normalized() * distance)
    if not fighter.grounded and buffer.vertical != VERTICAL_NONE:
        _nudge_vertical(match, fighter, distance * buffer.vertical)


def _nudge_vertical(match: Match, fighter: Fighter, offset: float) -> None:
    """Move an airborne fighter up or down, but never down through the surface below it."""
    pos = fighter.pos
    height = pos.z + offset
    if offset < 0.0:
        floor = match.stage.support_below(pos.x, pos.y, pos.z)
        if floor is not None:
            height = max(height, floor)
    fighter.pos = Vec3(pos.x, pos.y, height)


def _launch(match: Match, fighter: Fighter, launch: Launch) -> None:
    """Send a fighter flying: set knockback velocity, hitstun and the hurt state."""
    buffer = fighter.buffer
    stick = buffer.move if buffer.stick_active else ZERO2
    heading, elevation = kb_math.apply_di(launch.heading, launch.elevation, stick, buffer.vertical)
    if fighter.grounded and elevation < 0.0:
        elevation = 0.0  # DI cannot push a standing fighter into the floor
    direction = kb_math.launch_vector(heading, elevation)
    fighter.kb_vel = direction * kb_math.launch_speed(launch.knockback) + launch.carry
    kept = fighter.vel.xy * c.LAUNCH_SELF_VELOCITY_KEEP
    fighter.vel = Vec3(kept.x, kept.y, 0.0)
    fighter.hitstun = kb_math.hitstun_frames(launch.knockback)
    fighter.fast_falling = False
    fighter.ledge_grabs = 0
    fighter.tech_window = 0
    fighter.intangible_frames = 0
    if fighter.kb_vel.z > 0.0 and fighter.grounded:
        fighter.ground = GroundKind.NONE
        fighter.platform = -1
    # Down held at launch is DI, not a fast-fall or platform-drop request.
    if buffer.vertical != VERTICAL_NONE:
        buffer.consume(Press.DOWN)
        buffer.consume(Press.UP)
    airborne_tumble = launch.tumble and not fighter.grounded
    change_state(match, fighter, StateId.TUMBLE if airborne_tumble else StateId.FLINCH)
