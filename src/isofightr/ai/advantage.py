"""The advantage state: what to do with an opponent that cannot act freely (decision D-071).

Plan note "15 - CPU AI" ("Situations and their tactics", advantage). Most of the advantage
state is the intercept search of :mod:`isofightr.ai.intercept` aimed at a track that is
locked (a launch, a landing, a getup, a ledge option); this module holds what is particular
to it:

- :func:`throw_choices`: every throw the CPU could make (up, down, and a forward or back throw
  in each of the eight directions the stick can choose, D-015), each flown by
  :mod:`isofightr.ai.forecast` and valued: a KO that survives any DI, a KO without DI, a
  victim sent off the stage, the frames of advantage it leaves.
- :func:`chase_point`: where to be when a launched, landing or lying opponent can act again,
  on ground the CPU can stand on.
- :func:`ledge_trap_point`: where to wait for an opponent hanging from a ledge.
- :func:`can_return`: whether the CPU gets back to a ledge from a point off the stage, with
  the jumps and up special it has (the return check every off-stage edgeguard passes).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from isofightr import config
from isofightr.ai import forecast
from isofightr.ai.knowledge import CharacterKnowledge
from isofightr.ai.predict import Track
from isofightr.ai.terrain import closest_point, ground_below, over_ground
from isofightr.ai.view import FighterView
from isofightr.sim.character_def import CharacterDef, GrabSet, ThrowDef
from isofightr.sim.combat import constants as combat
from isofightr.sim.combat.knockback import (
    hitstun_frames,
    is_tumble,
    knockback,
    resolve_elevation,
)
from isofightr.sim.fighter import Launch
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_NONE, VERTICAL_UP, Dir8
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import Stage

BACK_THROW_DOT: Final[float] = math.cos(math.radians(combat.THROW_BACK_DEGREES))
"""A stick direction less in front than this throws backwards (as ``states/grab.py``)."""


@dataclass(frozen=True, slots=True)
class ThrowChoice:
    """One throw the CPU could make, and what the forecast makes of it."""

    name: str
    throw: ThrowDef
    heading: Vec2
    vertical: int
    """``VERTICAL_UP`` or ``VERTICAL_DOWN`` for those throws, else ``VERTICAL_NONE`` (then
    the stick is flicked along ``heading``)."""
    value: float
    kills: bool = False
    kills_through_di: bool = False
    off_stage: bool = False


def _throw_value(
    stage: Stage,
    throw: ThrowDef,
    heading: Vec2,
    victim: FighterView,
    character: CharacterDef,
) -> tuple[float, bool, bool, bool]:
    damage = throw.damage * forecast.FRESH
    after = min(victim.damage + damage, combat.MAX_DAMAGE)
    kb = knockback(after, damage, character.weight, throw.bkb, throw.kbg)
    launch = Launch(kb, heading, resolve_elevation(throw.angle, kb, True), is_tumble(kb))
    flown = forecast.flight(stage, launch, victim.pos, True, character)
    through = flown.ko and forecast.kills_through_di(stage, launch, victim.pos, True, character)
    landed = flown.end
    off = not flown.ko and not over_ground(stage, Vec3(landed.x, landed.y, victim.pos.z))
    advantage = hitstun_frames(kb) - (throw.total - throw.release)
    value = damage + config.CPU_HIT_VALUE
    value += max(-15, min(advantage, 15)) * config.CPU_ADVANTAGE_VALUE
    if through:
        value += config.CPU_KO_VALUE
    elif flown.ko:
        value += config.CPU_KO_VALUE * config.CPU_KO_WITHOUT_DI_SHARE
    elif off:
        value += config.CPU_OFF_STAGE_VALUE
    return value, flown.ko, through, off


def throw_choices(
    stage: Stage,
    grabber: FighterView,
    grabs: GrabSet,
    victim: FighterView,
    character: CharacterDef,
) -> list[ThrowChoice]:
    """Every throw ``grabber`` (whose throws are ``grabs``) could make on ``victim`` (whose
    character is ``character``), valued by the forecast, best first."""
    facing = grabber.facing.world
    found: list[ThrowChoice] = []
    for name, throw, vertical in (
        ("up", grabs.up, VERTICAL_UP),
        ("down", grabs.down, VERTICAL_DOWN),
    ):
        value, ko, through, off = _throw_value(stage, throw, facing, victim, character)
        found.append(ThrowChoice(name, throw, facing, vertical, value, ko, through, off))
    for direction in Dir8:
        heading = direction.world
        back = facing.dot(heading) < BACK_THROW_DOT
        throw = grabs.back if back else grabs.forward
        value, ko, through, off = _throw_value(stage, throw, heading, victim, character)
        name = f"{'back' if back else 'forward'} {direction.name}"
        found.append(ThrowChoice(name, throw, heading, VERTICAL_NONE, value, ko, through, off))
    found.sort(key=lambda choice: -choice.value)
    return found


def chase_point(stage: Stage, track: Track, me: FighterView, horizon: int) -> Vec3 | None:
    """Where to stand for an opponent that cannot act yet: under where it will be when it
    can (or at ``horizon`` frames), on ground the CPU can stand on; ``None`` if that place is
    over nothing (an edgeguard, not a chase)."""
    frame = max(min(track.locked, horizon), 1)
    point, _spread = track.at(frame)
    floor = ground_below(stage, point.x, point.y, point.z)
    if floor is None:
        return None
    return Vec3(point.x, point.y, floor)


def ledge_trap_point(stage: Stage, hanging: FighterView) -> Vec3 | None:
    """Where to wait for an opponent hanging from a ledge: inside the ledge by
    ``CPU_LEDGE_TRAP_INSET``, where its getup, attack and roll all come within reach."""
    best = None
    best_distance = math.inf
    for ledge in stage.ledges:
        point = closest_point(ledge, hanging.pos.xy)
        distance = (point - hanging.pos.xy).length()
        if distance < best_distance:
            best, best_distance = (ledge, point), distance
    if best is None:
        return None
    ledge, point = best
    spot = point - ledge.normal * config.CPU_LEDGE_TRAP_INSET
    floor = ground_below(stage, spot.x, spot.y, ledge.z + 0.1)
    if floor is None:
        return None
    return Vec3(spot.x, spot.y, floor)


def can_return(stage: Stage, point: Vec3, jumps: int, knowledge: CharacterKnowledge) -> bool:
    """Whether a fighter at ``point`` off the stage, with ``jumps`` air jumps and its up
    special, can still reach a ledge: the nearest ledge within what a jump and the up special
    carry it sideways, and not further below it than they lift it. Counted with
    ``CPU_RETURN_SAFETY`` to spare: an edgeguard is never worth a stock."""
    if over_ground(stage, point):
        return True
    lift = (jumps * knowledge.air_jump_rise + knowledge.up_special_rise) * config.CPU_RETURN_SAFETY
    reach = (
        knowledge.jump_distance * 0.5 * min(jumps, 1) + knowledge.up_special_reach
    ) * config.CPU_RETURN_SAFETY
    for ledge in stage.ledges:
        edge = closest_point(ledge, point.xy)
        if (edge - point.xy).length() <= reach and point.z >= ledge.z - lift:
            return True
    return False
