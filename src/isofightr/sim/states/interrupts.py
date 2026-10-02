"""Interrupt checks: what an actionable fighter does with its buffered input.

Plan note "07 - Fighter State Machine and Move Data" ("Actionability and interrupts"):
interrupts are tried in priority order on each actionable frame, and the table is kept here
as data so it is easy to tweak. M2 added the movement rows and M3 the attacks; special,
grab and shield rows slot into the same tuples from M4 on.

Each check returns ``True`` if it changed the fighter's state.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from isofightr.sim.combat.constants import BACK_DOT
from isofightr.sim.constants import FLICK_HIGH, TURN_THRESHOLD_DEGREES
from isofightr.sim.events import JumpEvent, JumpKind
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    VERTICAL_UP,
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


def start_move(match: Match, fighter: Fighter, move_id: str) -> None:
    """Begin performing a move (the generic ``Attack`` state runs it)."""
    fighter.move_id = move_id
    change_state(match, fighter, StateId.ATTACK)


def _take_vertical(fighter: Fighter) -> int:
    """Return the held vertical intent and use up its tap, so the same press that picked an
    up or down move does not also fast-fall or drop through a platform."""
    vertical = fighter.buffer.vertical
    if vertical == VERTICAL_UP:
        fighter.buffer.consume(Press.UP)
    elif vertical == VERTICAL_DOWN:
        fighter.buffer.consume(Press.DOWN)
    return vertical


# --- ground interrupts ---------------------------------------------------------------------


def ground_strong(match: Match, fighter: Fighter) -> bool:
    """Smash attack: the strong button, or a right-stick flick toward a direction.

    Up or down modifier picks the up or down smash; otherwise it is a forward smash, turned
    toward the stick (or the right-stick direction) if one is held.
    """
    buffer = fighter.buffer
    moveset = fighter.character.moveset
    if buffer.consume(Press.CSTICK) and buffer.frame.cstick is not None:
        snap_facing(fighter, buffer.frame.cstick)
        start_move(match, fighter, moveset.fsmash)
        return True
    if not buffer.consume(Press.STRONG):
        return False
    vertical = _take_vertical(fighter)
    if vertical == VERTICAL_UP:
        start_move(match, fighter, moveset.usmash)
    elif vertical == VERTICAL_DOWN:
        start_move(match, fighter, moveset.dsmash)
    else:
        snap_facing(fighter, stick_direction(fighter))
        start_move(match, fighter, moveset.fsmash)
    return True


def ground_attack(match: Match, fighter: Fighter) -> bool:
    """Jab or tilt: up and down modifiers pick the up and down tilts, a stick direction the
    forward tilt (turning to face it), and no direction the jab."""
    if not fighter.buffer.consume(Press.ATTACK):
        return False
    moveset = fighter.character.moveset
    vertical = _take_vertical(fighter)
    direction = stick_direction(fighter)
    if vertical == VERTICAL_UP:
        start_move(match, fighter, moveset.utilt)
    elif vertical == VERTICAL_DOWN:
        start_move(match, fighter, moveset.dtilt)
    elif direction != Vec2():
        snap_facing(fighter, direction)
        start_move(match, fighter, moveset.ftilt)
    else:
        start_move(match, fighter, moveset.jab[0])
    return True


def dash_attack(match: Match, fighter: Fighter) -> bool:
    """Dash attack: attack while dashing or running."""
    if fighter.buffer.consume(Press.ATTACK):
        start_move(match, fighter, fighter.character.moveset.dash_attack)
        return True
    return False


def ground_actions(match: Match, fighter: Fighter) -> bool:
    """Smash, jump or attack, in priority order: what interrupts most ground movement."""
    return (
        ground_strong(match, fighter)
        or ground_jump(match, fighter)
        or ground_attack(match, fighter)
    )


def running_actions(match: Match, fighter: Fighter) -> bool:
    """Like :func:`ground_actions`, but attack is the dash attack."""
    return (
        ground_strong(match, fighter) or ground_jump(match, fighter) or dash_attack(match, fighter)
    )


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


def ground_dash_held(match: Match, fighter: Fighter) -> bool:
    """Dash because the stick is already fully pushed when control comes back.

    Without this, holding a direction through landing lag (or a turn, or the end of a dash)
    would only walk, and running would need the stick released and flicked again. On a
    keyboard that feels unresponsive; on an analog stick a partial tilt still walks.
    """
    buffer = fighter.buffer
    if buffer.move.length() > FLICK_HIGH and not buffer.holds(Button.WALK):
        buffer.consume(Press.FLICK)
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
    # M4+: special goes above strong; grab and shield below attack.
    ground_strong,
    ground_jump,
    ground_attack,
    ground_dash,
    ground_move,
    platform_drop_hold,
)
"""Priority order for a fighter that is free to do anything on the ground."""


def run_interrupts(match: Match, fighter: Fighter, interrupts: tuple[Interrupt, ...]) -> bool:
    """Try each interrupt in priority order. Returns whether one fired."""
    return any(interrupt(match, fighter) for interrupt in interrupts)


GROUND_RECOVER: tuple[Interrupt, ...] = (
    ground_strong,
    ground_jump,
    ground_attack,
    ground_dash,
    ground_dash_held,
    ground_move,
    platform_drop_hold,
)
"""Priority order on the first actionable frame after landing lag, a turn, a skid or a dash:
like :data:`GROUND_NEUTRAL`, plus a fully held stick dashes without a fresh flick."""


def become_ground_neutral(match: Match, fighter: Fighter) -> None:
    """Hand control back to the player on the ground: act on held or buffered input, or
    stand idle."""
    if not run_interrupts(match, fighter, GROUND_RECOVER):
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


def air_attack(match: Match, fighter: Fighter) -> bool:
    """Aerial: attack (or strong, or a right-stick flick) in the air.

    Up and down modifiers pick the up and down airs. A stick direction picks forward or back
    air by comparing it with the facing, which never changes in the air. No direction is
    the neutral air.
    """
    buffer = fighter.buffer
    moveset = fighter.character.moveset
    direction = stick_direction(fighter)
    if buffer.consume(Press.CSTICK) and buffer.frame.cstick is not None:
        direction = buffer.frame.cstick
    elif not (buffer.consume(Press.ATTACK) or buffer.consume(Press.STRONG)):
        return False
    vertical = _take_vertical(fighter)
    if vertical == VERTICAL_UP:
        start_move(match, fighter, moveset.uair)
    elif vertical == VERTICAL_DOWN:
        start_move(match, fighter, moveset.dair)
    elif direction == Vec2():
        start_move(match, fighter, moveset.nair)
    elif fighter.facing.world.dot(direction.normalized()) < BACK_DOT:
        start_move(match, fighter, moveset.bair)
    else:
        start_move(match, fighter, moveset.fair)
    return True


def fast_fall(match: Match, fighter: Fighter) -> bool:
    """Fast fall: a Down tap at or after the apex. Never changes state."""
    if fighter.vel.z <= 0.0 and not fighter.fast_falling and fighter.buffer.consume(Press.DOWN):
        fighter.fast_falling = True
    return False


AIR_NEUTRAL: tuple[Interrupt, ...] = (
    # M4+: special and air dodge go above the aerials.
    air_attack,
    air_jump,
    fast_fall,
)
"""Priority order for a fighter that is free to do anything in the air (drift is physics)."""
