"""Where can a fighter be a few frames from now? Tracks and option sets (decision D-071).

Plan note "15 - CPU AI" ("Prediction: tracks and option sets"). The M10 CPU extends an
opponent's velocity in a straight line. That is right for almost nothing: a launched fighter
follows an arc, an attacker follows its move, a fighter lying down will do one of four things.
Here a prediction is a :class:`Track`: where the feet are on each coming frame, how sure that
is (``spread``, a horizontal radius), and for how long the fighter cannot change it
(``locked``).

- **It cannot act** (hitlag with a launch pending, hitstun, the rest of a move, landing lag,
  shieldstun, a roll or dodge): one path. A launch is flown by :mod:`isofightr.ai.forecast`
  and widened by what DI could do; a move follows its recorded path.
- **It is free on the ground:** it stays about where its speed takes it, in a disc that grows
  at its run speed.
- **It is free in the air:** its arc under gravity, widened by its air speed.
- **It must choose from a fixed menu** (lying down, hanging from a ledge, tumbling toward the
  ground): :func:`options` gives each choice as its own track with a weight. Weights start
  even; the habit model replaces them in group 5.

Everything is worked out from the sim's constants and the recorded knowledge, and
``tests/test_cpu_predict.py`` compares each kind with the real sim.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from isofightr.ai import forecast
from isofightr.ai.knowledge import Action, CharacterKnowledge
from isofightr.ai.view import FighterView
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import constants as combat
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import facing_from_move
from isofightr.sim.math3d import ZERO2, Vec2, Vec3
from isofightr.sim.stage import Stage

TRACK_FRAMES: Final[int] = 60
"""How far ahead a track goes unless asked otherwise."""
CARRY_FRAMES: Final[int] = 12
"""A free fighter's current speed is trusted for this many frames, fading out."""
FREE_SPREAD_SHARE: Final[float] = 1.0
"""A free fighter can be anywhere its top speed takes it: this share of it is counted on (a
fighter that keeps running leaves a smaller disc, which the tests caught)."""
DI_SIDES: Final[tuple[float, ...]] = (1.0, -1.0)
STILL: Final[frozenset[StateId]] = frozenset(
    {
        StateId.SHIELD_STUN,
        StateId.SHIELD_BREAK,
        StateId.DIZZY,
        StateId.GRABBED,
        StateId.GRAB_HOLD,
        StateId.THROW,
        StateId.GRAB,
        StateId.DASH_GRAB,
        StateId.SPOT_DODGE,
        StateId.GETUP,
        StateId.TECH,
        StateId.LEDGE_GETUP,
        StateId.LEDGE_ATTACK,
        StateId.LEDGE_ROLL,
        StateId.TECH_ROLL,
        StateId.GETUP_ROLL,
        StateId.ROLL,
        StateId.LAND,
        StateId.JUMP_SQUAT,
        StateId.SHIELD_DROP,
        StateId.GRAB_RELEASE,
        StateId.REBOUND,
        StateId.LEDGE_TRUMPED,
    }
)
"""States a fighter cannot act out of until they end (apart from attacks and hitstun)."""
STATE_LENGTH: Final[dict[StateId, int]] = {
    StateId.SPOT_DODGE: combat.SPOT_DODGE_FRAMES,
    StateId.ROLL: combat.ROLL_FRAMES,
    StateId.GETUP: combat.GETUP_FRAMES,
    StateId.GETUP_ROLL: combat.GETUP_ROLL_FRAMES,
    StateId.TECH: combat.TECH_FRAMES,
    StateId.TECH_ROLL: combat.TECH_ROLL_FRAMES,
    StateId.LEDGE_GETUP: combat.LEDGE_GETUP_FRAMES,
    StateId.LEDGE_ROLL: combat.LEDGE_ROLL_FRAMES,
    StateId.SHIELD_DROP: combat.SHIELD_DROP_FRAMES,
    StateId.GRAB_RELEASE: combat.GRAB_RELEASE_FRAMES,
    StateId.LEDGE_TRUMPED: combat.LEDGE_TRUMP_FRAMES,
}
"""How long the fixed-length states last, from the sim's constants."""
UNKNOWN_LOCK: Final[int] = 8
"""Frames a locked state of unknown length is counted on for."""


@dataclass(frozen=True, slots=True)
class Track:
    """Where a fighter's feet can be on each of the coming frames."""

    points: tuple[Vec3, ...]
    """The most likely place after each frame (index 0 = one frame from now)."""
    spread: tuple[float, ...]
    """How far from that place it could be instead, horizontally, on each frame."""
    locked: int
    """Frames for which it cannot act: the track is exact (but for DI) until then."""

    def at(self, frame: int) -> tuple[Vec3, float]:
        """The place and spread ``frame`` frames from now (clamped to the track)."""
        index = min(max(frame, 1), len(self.points)) - 1
        return self.points[index], self.spread[index]

    def sure(self, frame: int) -> bool:
        """Whether the fighter is still locked on that frame."""
        return frame <= self.locked


@dataclass(frozen=True, slots=True)
class Option:
    """One choice from a fixed menu: what it is, how likely, where it leads and when the
    fighter is free again."""

    name: str
    weight: float
    track: Track
    free: int
    """The frame, counted from the choice, on which the fighter can act again."""
    intangible: int
    """Frames from the choice during which it cannot be hit (0 = none)."""


def _hold(position: Vec3, frames: int, locked: int, spread: float = 0.0) -> Track:
    return Track((position,) * frames, (spread,) * frames, locked)


def _move_action(view: FighterView, knowledge: CharacterKnowledge) -> Action | None:
    """The recording of the move a fighter is performing, if it is one the CPU knows."""
    first = knowledge.ground_by_move if view.grounded else knowledge.air_by_move
    return (
        first.get(view.move_id)
        or knowledge.ground_by_move.get(view.move_id)
        or knowledge.air_by_move.get(view.move_id)
    )


def _rotate(local: Vec3, forward: Vec2) -> Vec3:
    left = forward.perpendicular_left()
    return Vec3(
        local.x * forward.x + local.y * left.x, local.x * forward.y + local.y * left.y, local.z
    )


def _launched(stage: Stage, view: FighterView, character: CharacterDef, frames: int) -> Track:
    """In hitlag with a launch pending: frozen until the hitlag ends, then the flight, as
    wide as DI to either side could make it."""
    launch = view.launch
    assert launch is not None
    wait = view.hitlag
    flown = forecast.flight(stage, launch, view.pos, view.grounded, character)
    across = launch.heading.perpendicular_left()
    sides = [
        forecast.flight(stage, launch, view.pos, view.grounded, character, across * side)
        for side in DI_SIDES
    ]
    points: list[Vec3] = []
    spread: list[float] = []
    for frame in range(1, frames + 1):
        if frame <= wait:
            points.append(view.pos)
            spread.append(0.0)
            continue
        here = flown.at(frame - wait)
        points.append(here)
        spread.append(max((side.at(frame - wait) - here).length() for side in sides))
    return Track(tuple(points), tuple(spread), wait + flown.hitstun)


def _stunned(stage: Stage, view: FighterView, character: CharacterDef, frames: int) -> Track:
    """Already flying: the rest of the flight from its knockback velocity."""
    fall = view.vel.z - view.kb_vel.z
    flown = forecast.coast(
        stage, view.pos, view.kb_vel, fall, view.hitstun, view.grounded, character
    )
    points = tuple(flown.at(frame) for frame in range(1, frames + 1))
    return Track(points, (0.0,) * frames, view.hitstun)


def _attacking(view: FighterView, action: Action, frames: int, character: CharacterDef) -> Track:
    """In a move the CPU has a recording of: its feet follow the recorded path."""
    now = action.move_start + view.state_frame - 1
    here = action.offset_at(now)
    forward = view.facing.world
    left = max(action.commit - now, 0)
    reach = character.movement.run_speed * FREE_SPREAD_SHARE
    points: list[Vec3] = []
    spread: list[float] = []
    for frame in range(1, frames + 1):
        step = action.offset_at(min(now + frame, action.commit)) - here
        points.append(view.pos + _rotate(step, forward))
        spread.append(max(frame - left, 0) * reach)
    return Track(tuple(points), tuple(spread), left)


def _free_ground(view: FighterView, character: CharacterDef, frames: int, locked: int) -> Track:
    """Free on the ground (or locked in place for a while first): its speed carries it a
    little, then it could be anywhere its legs take it."""
    reach = character.movement.run_speed * FREE_SPREAD_SHARE
    points: list[Vec3] = []
    spread: list[float] = []
    position = view.pos
    flat = Vec3(view.vel.x, view.vel.y, 0.0)
    for frame in range(1, frames + 1):
        if frame <= CARRY_FRAMES:
            position = position + flat * (1.0 - frame / (CARRY_FRAMES + 1))
        points.append(position)
        spread.append(max(frame - locked, 0) * reach)
    return Track(tuple(points), tuple(spread), locked)


def _free_air(stage: Stage, view: FighterView, character: CharacterDef, frames: int) -> Track:
    """Free in the air: its arc under gravity, and after landing a free fighter on the
    ground."""
    movement = character.movement
    reach = movement.air_speed * FREE_SPREAD_SHARE
    position = view.pos
    vz = view.vel.z
    flat = Vec3(view.vel.x, view.vel.y, 0.0)
    landed = 0
    points: list[Vec3] = []
    spread: list[float] = []
    for frame in range(1, frames + 1):
        if not landed:
            speed = flat.length()
            if speed <= movement.air_friction:
                flat = Vec3(0.0, 0.0, 0.0)
            else:
                flat = flat * ((speed - movement.air_friction) / speed)
            vz = max(vz - movement.gravity, -movement.max_fall)
            ahead = position + flat + Vec3(0.0, 0.0, vz)
            floor = stage.support_below(ahead.x, ahead.y, position.z) if vz <= 0.0 else None
            if floor is not None and ahead.z <= floor:
                ahead = Vec3(ahead.x, ahead.y, floor)
                landed = frame
            position = ahead
        points.append(position)
        spread.append(frame * reach)
    return Track(tuple(points), tuple(spread), 0)


def track(
    stage: Stage,
    view: FighterView,
    character: CharacterDef,
    knowledge: CharacterKnowledge,
    frames: int = TRACK_FRAMES,
) -> Track:
    """Where ``view``'s fighter can be over the next ``frames`` frames. ``stage`` is the
    stage as it is now; ``knowledge`` is that fighter's own."""
    if view.hitlag > 0 and view.launch is not None:
        return _launched(stage, view, character, frames)
    if view.hitstun > 0 and view.state in (StateId.TUMBLE, StateId.FLINCH):
        return _stunned(stage, view, character, frames)
    if view.state is StateId.ATTACK and not view.free:
        action = _move_action(view, knowledge)
        if action is not None:
            return _attacking(view, action, frames, character)
        left = max(view.move_faf - view.state_frame, 0)
        return _free_ground(view, character, frames, left)
    if view.state in STILL:
        if view.state is StateId.LAND:
            left = max(view.land_lag - view.state_frame, 0)
        elif view.state in (StateId.SHIELD_STUN, StateId.DIZZY, StateId.SHIELD_BREAK):
            left = view.stun_frames
        elif view.state in STATE_LENGTH:
            left = max(STATE_LENGTH[view.state] - view.state_frame, 0)
        else:
            left = UNKNOWN_LOCK
        return _free_ground(view, character, frames, left)
    if view.state in (StateId.KNOCKDOWN, StateId.LEDGE_HANG):
        return _hold(view.pos, frames, 0)
    if view.grounded:
        return _free_ground(view, character, frames, 0)
    return _free_air(stage, view, character, frames)


# --- fixed menus -----------------------------------------------------------------------------


def _slide(
    start: Vec3, direction: Vec2, distance: float, moving: int, length: int, frames: int
) -> Track:
    """A roll: ``distance`` along ``direction`` over its first ``moving`` frames (the sim
    moves a roll while it is intangible), then still until ``length``."""
    points = []
    for frame in range(1, frames + 1):
        offset = direction * (distance * min(frame / moving, 1.0))
        points.append(Vec3(start.x + offset.x, start.y + offset.y, start.z))
    return Track(tuple(points), (0.0,) * frames, length)


def _eight_way(direction: Vec2) -> Vec2:
    """A direction snapped to the eight ways a roll can go."""
    facing = facing_from_move(direction) if direction.length() > 0.0 else None
    return facing.world if facing is not None else direction


def _square(direction: Vec2) -> Vec2:
    """A direction snapped to the nearer grid axis: the way a ledge faces."""
    if abs(direction.x) >= abs(direction.y):
        return Vec2(1.0 if direction.x >= 0.0 else -1.0, 0.0)
    return Vec2(0.0, 1.0 if direction.y >= 0.0 else -1.0)


def _even(found: list[Option]) -> tuple[Option, ...]:
    weight = 1.0 / len(found)
    return tuple(
        Option(option.name, weight, option.track, option.free, option.intangible)
        for option in found
    )


def _inward(stage: Stage, position: Vec3) -> Vec2:
    toward = stage.respawn - position.xy
    return toward.normalized() if toward.length() > 0.0 else ZERO2


def getup_options(
    stage: Stage, view: FighterView, character: CharacterDef, frames: int = TRACK_FRAMES
) -> tuple[Option, ...]:
    """What a fighter lying down can do: stand, attack, or roll toward or away from the
    middle of the stage. (It rolls where its stick points, eight ways; in and out are the two
    that matter to whoever is waiting for it.)"""
    position = view.pos
    inward = _eight_way(_inward(stage, position))
    stand = combat.GETUP_FRAMES + 1
    roll = combat.GETUP_ROLL_FRAMES + 1
    safe = combat.GETUP_ROLL_INTANGIBLE
    found = [Option("stand", 1.0, _hold(position, frames, stand), stand, combat.GETUP_INTANGIBLE)]
    for name, direction in (("roll in", inward), ("roll out", inward * -1.0)):
        rolled = _slide(position, direction, combat.GETUP_ROLL_DISTANCE, safe, roll, frames)
        found.append(Option(name, 1.0, rolled, roll, safe))
    attack = character.moves.get(character.moveset.getup_attack)
    lag = attack.faf if attack is not None else stand
    safe_for = attack.intangible.last if attack is not None and attack.intangible else 0
    found.append(Option("attack", 1.0, _hold(position, frames, lag), lag, safe_for))
    return _even(found)


def ledge_options(
    stage: Stage, view: FighterView, character: CharacterDef, frames: int = TRACK_FRAMES
) -> tuple[Option, ...]:
    """What a fighter hanging from a ledge can do: climb up, roll in, attack, jump or let
    go. Where it ends up is measured from the hang position toward the stage."""
    position = view.pos
    inward = _square(_inward(stage, position))
    top = position.z + combat.LEDGE_HANG_BELOW
    step_in = combat.LEDGE_HANG_OUT + combat.LEDGE_GETUP_INSET
    stand = Vec3(position.x + inward.x * step_in, position.y + inward.y * step_in, top)
    climb = combat.LEDGE_GETUP_FRAMES + 1
    roll = combat.LEDGE_ROLL_FRAMES + 1
    attack = character.moves.get(character.moveset.ledge_attack)
    swing = combat.LEDGE_ATTACK_CLIMB_FRAMES + (attack.faf if attack is not None else 1)
    found = [
        Option("getup", 1.0, _hold(stand, frames, climb), climb, combat.LEDGE_GETUP_INTANGIBLE),
        Option(
            "roll",
            1.0,
            _slide(
                Vec3(position.x, position.y, top),
                inward,
                combat.LEDGE_HANG_OUT + combat.LEDGE_ROLL_DISTANCE,
                roll,
                roll,
                frames,
            ),
            roll,
            combat.LEDGE_ROLL_INTANGIBLE,
        ),
        Option("attack", 1.0, _hold(stand, frames, swing), swing, combat.LEDGE_ATTACK_CLIMB_FRAMES),
    ]
    movement = character.movement
    vz = movement.full_hop_vz * combat.LEDGE_JUMP_VZ_MULT
    here = position
    jump: list[Vec3] = []
    for _ in range(frames):
        vz = max(vz - movement.gravity, -movement.max_fall)
        drift = inward * combat.LEDGE_JUMP_IN_SPEED
        here = Vec3(here.x + drift.x, here.y + drift.y, here.z + vz)
        jump.append(here)
    reach = movement.air_speed * FREE_SPREAD_SHARE
    spread = tuple(frame * reach for frame in range(1, frames + 1))
    found.append(
        Option("jump", 1.0, Track(tuple(jump), spread, 0), 1, combat.LEDGE_JUMP_INTANGIBLE)
    )
    here, vz = position, 0.0
    drop: list[Vec3] = []
    for _ in range(frames):
        vz = max(vz - movement.gravity, -movement.max_fall)
        here = Vec3(here.x, here.y, here.z + vz)
        drop.append(here)
    found.append(Option("drop", 1.0, Track(tuple(drop), spread, 0), 1, 0))
    return _even(found)


def tech_options(stage: Stage, landing: Vec3, frames: int = TRACK_FRAMES) -> tuple[Option, ...]:
    """What a tumbling fighter can do where it comes down at ``landing``: tech in place,
    tech roll in or out, or miss the tech and lie there."""
    inward = _eight_way(_inward(stage, landing))
    stand = combat.TECH_FRAMES + 1
    roll = combat.TECH_ROLL_FRAMES + 1
    safe = combat.TECH_INTANGIBLE
    found = [Option("tech", 1.0, _hold(landing, frames, stand), stand, safe)]
    for name, direction in (("tech in", inward), ("tech out", inward * -1.0)):
        rolled = _slide(landing, direction, combat.TECH_ROLL_DISTANCE, safe, roll, frames)
        found.append(Option(name, 1.0, rolled, roll, safe))
    missed = combat.KNOCKDOWN_LOCK_FRAMES
    found.append(Option("miss", 1.0, _hold(landing, frames, missed), missed, 0))
    return _even(found)


def options(
    stage: Stage,
    view: FighterView,
    character: CharacterDef,
    knowledge: CharacterKnowledge,
    frames: int = TRACK_FRAMES,
) -> tuple[Option, ...]:
    """The fixed menu a fighter is in front of, or nothing if it is not in front of one:
    lying down, hanging from a ledge, or tumbling toward ground it will reach."""
    if view.state is StateId.KNOCKDOWN:
        return getup_options(stage, view, character, frames)
    if view.state is StateId.LEDGE_HANG:
        return ledge_options(stage, view, character, frames)
    if view.state is StateId.TUMBLE and not view.grounded:
        fall = view.vel.z - view.kb_vel.z
        flown = forecast.coast(
            stage, view.pos, view.kb_vel, fall, max(view.hitstun, 1), False, character
        )
        if flown.land_frame:
            return tech_options(stage, flown.end, frames)
    return ()
