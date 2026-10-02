"""Hurt states: Flinch, Tumble, Knockdown and Getup.

Plan notes "05 - Combat Core" (hitstun, tumble at 80 knockback) and "06 - Shield Dodge Grab
and Ledge" (knockdown). Teching, wall bounces and the getup options arrive in M4; until then
a tumbling fighter that lands is always knocked down, and simply stands back up.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat.constants import (
    GETUP_FRAMES,
    HITSTUN_DRIFT_MULT,
    HITSTUN_GRAVITY_MULT,
    KNOCKDOWN_LOCK_FRAMES,
    KNOCKDOWN_MAX_FRAMES,
)
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_NONE
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import GroundState, State, change_state, register

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def _refill(fighter: Fighter) -> None:
    fighter.air_jumps_left = fighter.character.movement.air_jumps
    fighter.fast_falling = False


@register
class Flinch(State):
    """Hitstun from a hit below tumble knockback: stunned, then free to act."""

    id = StateId.FLINCH

    def step(self, match: Match, fighter: Fighter) -> None:
        """Count down hitstun, then hand control back."""
        fighter.hitstun -= 1
        if fighter.hitstun > 0:
            return
        fighter.hitstun = 0
        if fighter.grounded:
            interrupts.become_ground_neutral(match, fighter)
        else:
            change_state(match, fighter, StateId.FALL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Slide on the ground; in the air, fall with reduced drift."""
        if fighter.grounded:
            physics.apply_traction(fighter)
        else:
            physics.apply_gravity(fighter, HITSTUN_GRAVITY_MULT)
            physics.apply_air_drift(fighter, HITSTUN_DRIFT_MULT)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Landing does not end hitstun: keep flinching on the ground."""
        _refill(fighter)

    def on_leave_ground(self, match: Match, fighter: Fighter) -> None:
        """Sliding off an edge does not end hitstun either."""


@register
class Tumble(State):
    """Launched hard enough to tumble: helpless during hitstun, knocked down on landing."""

    id = StateId.TUMBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Count down hitstun; afterwards an air jump or an aerial escapes the tumble."""
        if fighter.hitstun > 0:
            fighter.hitstun -= 1
            return
        interrupts.run_interrupts(match, fighter, interrupts.AIR_NEUTRAL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Fall; gravity and drift are reduced while still in hitstun."""
        stunned = fighter.hitstun > 0
        physics.apply_gravity(fighter, HITSTUN_GRAVITY_MULT if stunned else 1.0)
        physics.apply_air_drift(fighter, HITSTUN_DRIFT_MULT if stunned else 1.0)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Hit the ground: knocked down (teching arrives in M4)."""
        change_state(match, fighter, StateId.KNOCKDOWN)


@register
class Knockdown(GroundState):
    """Lying on the ground after a tumble."""

    id = StateId.KNOCKDOWN

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Hitstun is over once the fighter is down."""
        fighter.hitstun = 0
        _refill(fighter)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Get up on any input after the lock, or automatically after the maximum."""
        frame = fighter.state_frame
        buffer = fighter.buffer
        wants_up = buffer.stick_active or buffer.frame.held != 0 or buffer.vertical != VERTICAL_NONE
        if frame > KNOCKDOWN_MAX_FRAMES or (frame > KNOCKDOWN_LOCK_FRAMES and wants_up):
            change_state(match, fighter, StateId.GETUP)


@register
class Getup(GroundState):
    """Standing back up from a knockdown."""

    id = StateId.GETUP

    def step(self, match: Match, fighter: Fighter) -> None:
        """Back to neutral once up."""
        if fighter.state_frame > GETUP_FRAMES:
            interrupts.become_ground_neutral(match, fighter)
