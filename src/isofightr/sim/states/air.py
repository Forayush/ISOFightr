"""Air states: Jump, DoubleJump and Fall.

Plan note "04 - Movement and Physics" ("Jumping and air"). All three share the same control:
air jump, fast fall, and drift (drift and gravity are the default air motion). Jump and
DoubleJump exist mostly for animation; they become Fall at the apex.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import AirState, change_state, register

if TYPE_CHECKING:
    from isofightr.sim.match import Match


class _Rising(AirState):
    """Shared behaviour of the two rising states."""

    grabs_ledges = True

    def step(self, match: Match, fighter: Fighter) -> None:
        """Air jump or fast fall; become Fall once no longer rising."""
        if interrupts.run_interrupts(match, fighter, interrupts.AIR_NEUTRAL):
            return
        if fighter.vel.z <= 0.0:
            change_state(match, fighter, StateId.FALL)


@register
class Jump(_Rising):
    """Rising from a grounded jump."""

    id = StateId.JUMP


@register
class DoubleJump(_Rising):
    """Rising from an air jump."""

    id = StateId.DOUBLE_JUMP


@register
class Fall(AirState):
    """Falling, or airborne without having jumped (walked off an edge)."""

    id = StateId.FALL
    grabs_ledges = True

    def step(self, match: Match, fighter: Fighter) -> None:
        """Air jump or fast fall."""
        interrupts.run_interrupts(match, fighter, interrupts.AIR_NEUTRAL)
