"""Ground states: Idle, Walk, Dash, Run, RunTurn, Skid, Turn, JumpSquat, Land, PlatformDrop.

Plan note "04 - Movement and Physics" ("Ground movement", "Jumping and air"). Fighters never
stop at edges: walking or running off one is handled by physics, which hands the fighter to
the Fall state.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.constants import (
    PLATFORM_DROP_FRAMES,
    RESPAWN_INVINCIBLE_FRAMES,
    RUN_TURN_FRAMES,
    RUN_TURN_TRACTION_MULT,
    TURN_FRAMES,
)
from isofightr.sim.events import JumpEvent, JumpKind
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Button, Press
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import NO_PLATFORM
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import GroundState, change_state, register

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def leave_ground(fighter: Fighter) -> None:
    """Mark a fighter airborne. Leaving the revival platform starts respawn invincibility."""
    if fighter.ground is GroundKind.REVIVAL:
        fighter.invincible_frames = RESPAWN_INVINCIBLE_FRAMES
    fighter.ground = GroundKind.NONE
    fighter.platform = NO_PLATFORM


@register
class Idle(GroundState):
    """Standing still and free to act."""

    id = StateId.IDLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Act on any input."""
        interrupts.run_interrupts(match, fighter, interrupts.GROUND_NEUTRAL)


@register
class Walk(GroundState):
    """Walking: speed scales with stick tilt, and the facing follows the stick."""

    id = StateId.WALK

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Face the stick."""
        interrupts.face(fighter, interrupts.stick_direction(fighter))

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump, dash, drop, turn around, keep walking, or stop."""
        if (
            interrupts.ground_jump(match, fighter)
            or interrupts.ground_dash(match, fighter)
            or interrupts.platform_drop_tap(match, fighter)
        ):
            return
        direction = interrupts.stick_direction(fighter)
        if direction == Vec2():
            change_state(match, fighter, StateId.IDLE)
        elif interrupts.needs_turnaround(fighter, direction):
            change_state(match, fighter, StateId.TURN)
        else:
            interrupts.face(fighter, direction)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Move at walk speed scaled by how far the stick is tilted."""
        speed = fighter.character.movement.walk_speed
        physics.set_ground_velocity(fighter, fighter.buffer.move * speed)


@register
class Dash(GroundState):
    """The initial dash: a fixed burst in the flicked direction."""

    id = StateId.DASH

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Lock the dash direction and face it."""
        fighter.drive = interrupts.stick_direction(fighter)
        interrupts.snap_facing(fighter, fighter.drive)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump, drop, dash back the other way (dash dance), or settle into a run."""
        if interrupts.ground_jump(match, fighter) or interrupts.platform_drop_tap(match, fighter):
            return
        direction = interrupts.stick_direction(fighter)
        buffer = fighter.buffer
        if buffer.has(Press.FLICK) and not buffer.holds(Button.WALK):
            buffer.consume(Press.FLICK)
            if direction.dot(fighter.drive) < 0.0:
                change_state(match, fighter, StateId.DASH)
                return
        if fighter.state_frame > fighter.character.movement.dash_frames:
            if direction.dot(fighter.drive) > 0.0:
                change_state(match, fighter, StateId.RUN)
            else:
                interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Move at dash speed along the locked direction."""
        speed = fighter.character.movement.dash_speed
        physics.set_ground_velocity(fighter, fighter.drive * speed)


@register
class Run(GroundState):
    """Running: steer up to 90 degrees freely; reversing skids into a run turnaround."""

    id = StateId.RUN

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump, drop, steer, turn around, or brake."""
        if interrupts.ground_jump(match, fighter) or interrupts.platform_drop_tap(match, fighter):
            return
        direction = interrupts.stick_direction(fighter)
        if direction == Vec2():
            change_state(match, fighter, StateId.SKID)
        elif direction.dot(fighter.drive) < 0.0:
            change_state(match, fighter, StateId.RUN_TURN)
        else:
            fighter.drive = direction
            interrupts.face(fighter, direction)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Move at run speed along the steered direction."""
        speed = fighter.character.movement.run_speed
        physics.set_ground_velocity(fighter, fighter.drive * speed)


@register
class RunTurn(GroundState):
    """Skidding turnaround out of a run: slide to a stop, then run the other way."""

    id = StateId.RUN_TURN

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Face the new direction straight away; the old momentum still carries."""
        fighter.drive = interrupts.stick_direction(fighter)
        interrupts.snap_facing(fighter, fighter.drive)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump out, or finish the turn into a run (or neutral if the stick was let go)."""
        if interrupts.ground_jump(match, fighter):
            return
        if fighter.state_frame > RUN_TURN_FRAMES:
            direction = interrupts.stick_direction(fighter)
            if direction.dot(fighter.drive) > 0.0:
                fighter.drive = direction
                change_state(match, fighter, StateId.RUN)
            else:
                interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Brake harder than a normal skid."""
        physics.apply_traction(fighter, RUN_TURN_TRACTION_MULT)


@register
class Skid(GroundState):
    """Braking after letting go of the stick during a run."""

    id = StateId.SKID

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump or dash out; otherwise slide until stopped."""
        if interrupts.ground_jump(match, fighter) or interrupts.ground_dash(match, fighter):
            return
        if fighter.vel.xy == Vec2():
            interrupts.become_ground_neutral(match, fighter)


@register
class Turn(GroundState):
    """Standing turnaround of more than 90 degrees."""

    id = StateId.TURN

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Face the stick straight away, so anything done out of the turn faces the new way."""
        interrupts.snap_facing(fighter, interrupts.stick_direction(fighter))

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump or dash out; otherwise finish the turn."""
        if interrupts.ground_jump(match, fighter) or interrupts.ground_dash(match, fighter):
            return
        if fighter.state_frame > TURN_FRAMES:
            interrupts.become_ground_neutral(match, fighter)


@register
class JumpSquat(GroundState):
    """The grounded wind-up before a jump leaves the ground."""

    id = StateId.JUMP_SQUAT

    def step(self, match: Match, fighter: Fighter) -> None:
        """Take off after the last jumpsquat frame: full hop if jump is still held."""
        stats = fighter.character.movement
        if fighter.state_frame <= stats.jumpsquat:
            return
        full_hop = fighter.buffer.holds(Button.JUMP)
        carried = physics.clamp_length(fighter.vel.xy, stats.air_speed)
        rise = stats.full_hop_vz if full_hop else stats.short_hop_vz
        fighter.vel = Vec3(carried.x, carried.y, rise)
        fighter.air_jumps_left = stats.air_jumps
        fighter.fast_falling = False
        leave_ground(fighter)
        kind = JumpKind.FULL_HOP if full_hop else JumpKind.SHORT_HOP
        match.events.append(JumpEvent(fighter.player_index, kind, fighter.pos))
        change_state(match, fighter, StateId.JUMP)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Keep the ground momentum through the squat (no traction)."""


@register
class Land(GroundState):
    """Landing lag after touching down."""

    id = StateId.LAND

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Refill air jumps."""
        fighter.air_jumps_left = fighter.character.movement.air_jumps
        fighter.fast_falling = False

    def step(self, match: Match, fighter: Fighter) -> None:
        """Become actionable once the landing lag is over."""
        if fighter.state_frame > fighter.character.movement.land_lag:
            interrupts.become_ground_neutral(match, fighter)


@register
class PlatformDrop(GroundState):
    """Crouching for a few frames before dropping through a soft platform."""

    id = StateId.PLATFORM_DROP

    def step(self, match: Match, fighter: Fighter) -> None:
        """Let go of the platform and fall through it."""
        if fighter.state_frame > PLATFORM_DROP_FRAMES:
            fighter.drop_platform = fighter.platform
            leave_ground(fighter)
            change_state(match, fighter, StateId.FALL)
