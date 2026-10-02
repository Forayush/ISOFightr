"""Dodge states: SpotDodge, Roll, AirDodge, and Helpless (special fall).

Plan note "06 - Shield Dodge Grab and Ledge" ("Dodges", "Helpless"). Rolls go in any of the
eight directions and keep the facing. Repeated dodges get longer end lag.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import facing_from_move
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import AirState, GroundState, change_state, register

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def open_intangible_window(fighter: Fighter, window: tuple[int, int]) -> None:
    """Make the fighter intangible from frame ``window[0]`` to ``window[1]`` of its state.

    Call it every frame of the state (in ``enter`` and in ``step``).
    """
    first, last = window
    if fighter.state_frame == first:
        fighter.intangible_frames = last - first + 1


def begin_dodge(fighter: Fighter) -> None:
    """Work out this dodge's extra end lag from recent dodges, and count this one."""
    fighter.dodge_lag = min(fighter.dodge_stale * c.DODGE_STALE_STEP, c.DODGE_STALE_MAX)
    fighter.dodge_stale += 1
    fighter.dodge_stale_timer = c.DODGE_STALE_RESET_FRAMES


def snapped_direction(direction: Vec2) -> Vec2:
    """Return ``direction`` snapped to the nearest of the eight directions (zero stays zero)."""
    facing = facing_from_move(direction)
    return Vec2() if facing is None else facing.world


def roll_velocity(frame: int, window: tuple[int, int], direction: Vec2, distance: float) -> Vec2:
    """Return the ground velocity of a roll: ``distance`` spread evenly over ``window``."""
    first, last = window
    if not first <= frame <= last:
        return Vec2()
    return direction * (distance / (last - first + 1))


@register
class SpotDodge(GroundState):
    """Dodging in place."""

    id = StateId.SPOT_DODGE
    stops_at_edges = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Count the dodge for staling."""
        begin_dodge(fighter)
        open_intangible_window(fighter, c.SPOT_DODGE_INTANGIBLE)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Become intangible on time; recover at the end."""
        open_intangible_window(fighter, c.SPOT_DODGE_INTANGIBLE)
        if fighter.state_frame > c.SPOT_DODGE_FRAMES + fighter.dodge_lag:
            interrupts.become_ground_neutral(match, fighter)


@register
class Roll(GroundState):
    """Rolling along the ground in one of eight directions, without turning."""

    id = StateId.ROLL
    stops_at_edges = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Lock the roll direction to the stick."""
        begin_dodge(fighter)
        fighter.drive = snapped_direction(interrupts.stick_direction(fighter))
        open_intangible_window(fighter, c.ROLL_INTANGIBLE)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Become intangible on time; recover at the end."""
        open_intangible_window(fighter, c.ROLL_INTANGIBLE)
        if fighter.state_frame > c.ROLL_FRAMES + fighter.dodge_lag:
            interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Travel during the middle of the roll."""
        velocity = roll_velocity(
            fighter.state_frame, c.ROLL_MOVE_FRAMES, fighter.drive, c.ROLL_DISTANCE
        )
        physics.set_ground_velocity(fighter, velocity)


@register
class AirDodge(AirState):
    """Dodging in the air: in place, or a burst in any 3D direction. Once per airtime."""

    id = StateId.AIR_DODGE

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Pick the direction from the stick and the up/down modifier."""
        begin_dodge(fighter)
        fighter.air_dodge_used = True
        fighter.fast_falling = False
        stick = interrupts.stick_direction(fighter)
        fighter.dodge_dir = Vec3(stick.x, stick.y, float(fighter.buffer.vertical)).normalized()
        if fighter.dodge_dir != ZERO3:
            fighter.vel = fighter.dodge_dir * c.AIR_DODGE_SPEED
        open_intangible_window(fighter, self._window(fighter))

    @staticmethod
    def _window(fighter: Fighter) -> tuple[int, int]:
        directional = fighter.dodge_dir != ZERO3
        return c.AIR_DODGE_DIRECTIONAL_INTANGIBLE if directional else c.AIR_DODGE_INTANGIBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Become intangible on time; fall (or fall helpless) at the end."""
        open_intangible_window(fighter, self._window(fighter))
        if fighter.state_frame > c.AIR_DODGE_FRAMES + fighter.dodge_lag:
            helpless = fighter.dodge_dir != ZERO3 and match.rules.air_dodge_helpless
            change_state(match, fighter, StateId.HELPLESS if helpless else StateId.FALL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """A directional dodge is a burst that fades out; afterwards, and for a neutral
        dodge, normal air motion."""
        frame = fighter.state_frame
        if fighter.dodge_dir == ZERO3 or frame > c.AIR_DODGE_BURST_FRAMES:
            super().motion(match, fighter)
            return
        fade = 1.0 - (frame - 1) / c.AIR_DODGE_BURST_FRAMES
        fighter.vel = fighter.dodge_dir * (c.AIR_DODGE_SPEED * fade)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Landing during an air dodge has its own lag."""
        directional = fighter.dodge_dir != ZERO3
        fighter.land_lag = c.AIR_DODGE_DIRECTIONAL_LAND_LAG if directional else c.AIR_DODGE_LAND_LAG
        change_state(match, fighter, StateId.LAND)


@register
class Helpless(AirState):
    """Special fall: only weak air drift until landing or grabbing a ledge."""

    id = StateId.HELPLESS
    grabs_ledges = True

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Fall with reduced drift."""
        physics.apply_gravity(fighter)
        physics.apply_air_drift(fighter, c.HELPLESS_DRIFT_MULT)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """A heavy landing."""
        fighter.land_lag = c.HELPLESS_LAND_LAG
        change_state(match, fighter, StateId.LAND)
