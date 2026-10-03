"""Mote's special-move scripts (plan note "12 - Roster").

- Ember Orb (neutral): a chargeable orb. Pressing shield while charging keeps the charge for
  next time; a fully charged orb fires at once. Charge makes it bigger, faster and longer-lived.
- Orbit Lamp (side): plain data, a lamp that curves out and comes back (one at a time).
- Blink (up): after a short windup, a fast, intangible hop in any 3D direction (stick plus the
  up/down modifiers), then helpless.
- Snare Glyph (down): plain data, a rune that sits on the ground until someone steps on it
  (one at a time).
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from isofightr.sim.characters import MoveScript, register_script
from isofightr.sim.characters.common import direction_3d, fall, fly
from isofightr.sim.input_frame import Press
from isofightr.sim.math3d import ZERO3

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter
    from isofightr.sim.match import Match
    from isofightr.sim.projectile import Projectile

ORB_GROWTH: Final[float] = 1.0
"""A fully charged Ember Orb is this much bigger (radius), on top of its normal size."""
ORB_SPEEDUP: Final[float] = 0.5
ORB_LIFETIME_GROWTH: Final[float] = 1.0

BLINK_WINDUP: Final[int] = 8
BLINK_FRAMES: Final[int] = 6
BLINK_SPEED: Final[float] = 0.62


class EmberOrb(MoveScript):
    """Neutral special: charge, store the charge with shield, or fire."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Pick up a stored charge; a full one skips straight past the charge frame."""
        if fighter.stored_charge <= 0:
            return
        fighter.charge_frames = fighter.stored_charge
        fighter.stored_charge = 0
        charge = fighter.character.moves[fighter.move_id].charge
        if charge is not None and fighter.charge_frames >= charge.max_frames:
            fighter.state_frame = charge.frame + 1

    def on_frame(self, match: Match, fighter: Fighter) -> None:
        """Shield while charging keeps the charge and ends the move."""
        charge = fighter.character.moves[fighter.move_id].charge
        if charge is None or fighter.state_frame != charge.frame + 1:
            return
        if fighter.buffer.consume(Press.SHIELD):
            from isofightr.sim.fighter import StateId
            from isofightr.sim.states import interrupts
            from isofightr.sim.states.base import change_state

            fighter.stored_charge = max(fighter.charge_frames, 1)
            if fighter.grounded:
                interrupts.become_ground_neutral(match, fighter)
            else:
                change_state(match, fighter, StateId.FALL)

    def on_projectile(self, match: Match, fighter: Fighter, projectile: Projectile) -> None:
        """Charge grows the orb, speeds it up and makes it last longer."""
        charge = fighter.character.moves[fighter.move_id].charge
        if charge is None:
            return
        charged = min(fighter.charge_frames / charge.max_frames, 1.0)
        definition = projectile.definition
        hitbox = replace(
            definition.hitbox, radius=definition.hitbox.radius * (1 + ORB_GROWTH * charged)
        )
        projectile.definition = replace(definition, hitbox=hitbox)
        projectile.vel = projectile.vel * (1 + ORB_SPEEDUP * charged)
        projectile.lifetime = round(projectile.lifetime * (1 + ORB_LIFETIME_GROWTH * charged))


class Blink(MoveScript):
    """Up special: a short intangible hop in the chosen 3D direction."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """No direction yet."""
        fighter.special_dir = ZERO3

    def on_frame(self, match: Match, fighter: Fighter) -> None:
        """Read the direction when the windup ends."""
        if fighter.state_frame == BLINK_WINDUP + 1:
            fighter.special_dir = direction_3d(fighter)

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Hang during the windup, blink along the direction, then fall."""
        frame = fighter.state_frame
        if frame <= BLINK_WINDUP:
            fighter.vel = ZERO3
            return True
        if frame <= BLINK_WINDUP + BLINK_FRAMES:
            fly(fighter, fighter.special_dir * BLINK_SPEED)
            return True
        if frame == BLINK_WINDUP + BLINK_FRAMES + 1:
            fighter.vel = fighter.special_dir * fighter.character.movement.air_speed
        return fall(fighter)


register_script("mote.neutral_special", EmberOrb())
register_script("mote.up_special", Blink())
