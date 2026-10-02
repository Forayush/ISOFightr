"""Interrupt checks: what an actionable fighter does with its buffered input.

Plan note "07 - Fighter State Machine and Move Data" ("Actionability and interrupts"):
interrupts are tried in priority order on each actionable frame, and the table is kept here
as data so it is easy to tweak. M2 has the movement rows; the attack, special, grab and
shield rows slot into the same tuples from M3 on.

Each check returns ``True`` if it changed the fighter's state.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from isofightr.sim.constants import TURN_THRESHOLD_DEGREES
from isofightr.sim.events import JumpEvent, JumpKind
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    Button,
    Press,
    facing_from_move,
)
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.states.base import change_state

if TYPE_CHECKING:
    from isofightr.sim.match import Match

type Interrupt = Callable[[Match, Fighter], bool]


def stick_direction(fighter: Fighter) -> Vec2:
    """Return the unit direction of the stick, or zero when it is neutral."""
    return fighter.buffer.move.normalized() if fighter.buffer.stick_active else Vec2()


def needs_turnaround(fighter: Fighter, direction: Vec2) -> bool:
    """Return whether ``direction`` is more than 90 degrees away from the facing."""
    assert TURN_THRESHOLD_DEGREES == 90.0, "the dot-product test below assumes 90 degrees"
    return fighter.facing.world.dot(direction) < 0.0


def face(fighter: Fighter, direction: Vec2) -> None:
    """Turn the fighter to the facing nearest ``direction`` (with hysteresis)."""
    facing = facing_from_move(direction, fighter.facing)
    if facing is not None:
        fighter.facing = facing


def snap_facing(fighter: Fighter, direction: Vec2) -> None:
    """Turn the fighter to the facing nearest ``direction``, ignoring its current facing."""
    facing = facing_from_move(direction)
    if facing is not None:
        fighter.facing = facing


# --- ground interrupts ---------------------------------------------------------------------


def ground_jump(match: Match, fighter: Fighter) -> bool:
    """Jump: a buffered jump press starts jumpsquat."""
    if fighter.buffer.consume(Press.JUMP):
        change_state(match, fighter, StateId.JUMP_SQUAT)
        return True
    return False


def ground_dash(match: Match, fighter: Fighter) -> bool:
    """Dash: a stick flick in any direction, unless the walk modifier is held."""
    buffer = fighter.buffer
    if buffer.stick_active and not buffer.holds(Button.WALK) and buffer.consume(Press.FLICK):
        change_state(match, fighter, StateId.DASH)
        return True
    return False


def ground_move(match: Match, fighter: Fighter) -> bool:
    """Walk toward the stick, or turn around first if it points behind the fighter."""
    direction = stick_direction(fighter)
    if direction == Vec2():
        return False
    if needs_turnaround(fighter, direction):
        change_state(match, fighter, StateId.TURN)
    else:
        change_state(match, fighter, StateId.WALK)
    return True


def platform_drop_hold(match: Match, fighter: Fighter) -> bool:
    """Drop through a soft platform while Down is held (standing still)."""
    if fighter.ground is GroundKind.PLATFORM and fighter.buffer.vertical == VERTICAL_DOWN:
        fighter.buffer.consume(Press.DOWN)
        change_state(match, fighter, StateId.PLATFORM_DROP)
        return True
    return False


def platform_drop_tap(match: Match, fighter: Fighter) -> bool:
    """Drop through a soft platform on a fresh Down tap (while moving)."""
    if fighter.ground is GroundKind.PLATFORM and fighter.buffer.consume(Press.DOWN):
        change_state(match, fighter, StateId.PLATFORM_DROP)
        return True
    return False


GROUND_NEUTRAL: tuple[Interrupt, ...] = (
    # M3+: special, strong (smash attack) go above jump; attack, grab, shield below it.
    ground_jump,
    ground_dash,
    ground_move,
    platform_drop_hold,
)
"""Priority order for a fighter that is free to do anything on the ground."""


def run_interrupts(match: Match, fighter: Fighter, interrupts: tuple[Interrupt, ...]) -> bool:
    """Try each interrupt in priority order. Returns whether one fired."""
    return any(interrupt(match, fighter) for interrupt in interrupts)


def become_ground_neutral(match: Match, fighter: Fighter) -> None:
    """Hand control back to the player on the ground: act on buffered input, or stand idle."""
    if not run_interrupts(match, fighter, GROUND_NEUTRAL):
        change_state(match, fighter, StateId.IDLE)


# --- air interrupts ------------------------------------------------------------------------


def air_jump(match: Match, fighter: Fighter) -> bool:
    """Air jump: uses one of the remaining air jumps and can redirect drift instantly."""
    if fighter.air_jumps_left <= 0 or not fighter.buffer.consume(Press.JUMP):
        return False
    stats = fighter.character.movement
    fighter.air_jumps_left -= 1
    fighter.fast_falling = False
    horizontal = fighter.vel.xy
    if fighter.buffer.stick_active:
        horizontal = fighter.buffer.move * stats.air_speed
    fighter.vel = Vec3(horizontal.x, horizontal.y, stats.double_jump_vz)
    match.events.append(JumpEvent(fighter.player_index, JumpKind.AIR, fighter.pos))
    change_state(match, fighter, StateId.DOUBLE_JUMP)
    return True


def fast_fall(match: Match, fighter: Fighter) -> bool:
    """Fast fall: a Down tap at or after the apex. Never changes state."""
    if fighter.vel.z <= 0.0 and not fighter.fast_falling and fighter.buffer.consume(Press.DOWN):
        fighter.fast_falling = True
    return False


AIR_NEUTRAL: tuple[Interrupt, ...] = (
    # M3+: special, air dodge and aerials go above air jump.
    air_jump,
    fast_fall,
)
"""Priority order for a fighter that is free to do anything in the air (drift is physics)."""
