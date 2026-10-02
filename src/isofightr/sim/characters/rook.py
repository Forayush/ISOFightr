"""Rook's special-move scripts (plan note "12 - Roster").

- Crescent Wave (neutral): the charge makes the wave last longer, so it travels further.
- Lunge (side): a dash-stab aimed with the stick in any of eight directions; in the air it
  holds its height while it dashes.
- Rising Spin (up): a spinning climb that can be steered a little.

Riposte (down) is a plain counter and needs no script.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from isofightr.sim import physics
from isofightr.sim.characters import MoveScript, register_script
from isofightr.sim.fighter import GroundKind
from isofightr.sim.input_frame import facing_from_move
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.stage import NO_PLATFORM

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter
    from isofightr.sim.match import Match
    from isofightr.sim.projectile import Projectile

WAVE_CHARGE_LIFETIME_MULT: Final[float] = 2.5
"""A fully charged Crescent Wave lasts this many times as long as an uncharged one."""
LUNGE_FRAMES: Final[tuple[int, int]] = (8, 19)
"""Move frames during which Lunge travels."""
LUNGE_SPEED: Final[float] = 0.19
RISING_SPIN_FRAMES: Final[tuple[int, int]] = (6, 27)
"""Move frames during which Rising Spin climbs."""
RISING_SPIN_RISE: Final[float] = 0.2
RISING_SPIN_STEER: Final[float] = 0.045
"""Horizontal speed at full stick while climbing."""


def _stick(fighter: Fighter) -> Vec3:
    move = fighter.buffer.move if fighter.buffer.stick_active else None
    return ZERO3 if move is None else Vec3(move.x, move.y, 0.0)


class CrescentWave(MoveScript):
    """Neutral special: charge extends the projectile's life."""

    def on_projectile(self, match: Match, fighter: Fighter, projectile: Projectile) -> None:
        """Scale the lifetime by how long the special button was held."""
        charge = fighter.move.charge if fighter.move is not None else None
        if charge is None:
            return
        charged = fighter.charge_frames / charge.max_frames
        projectile.lifetime = round(
            projectile.lifetime * (1.0 + (WAVE_CHARGE_LIFETIME_MULT - 1.0) * charged)
        )


class Lunge(MoveScript):
    """Side special: turn to the stick, then dash straight that way."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Aim with the stick (eight ways); with no direction held, lunge forward."""
        if fighter.buffer.stick_active:
            facing = facing_from_move(fighter.buffer.move)
            if facing is not None:
                fighter.facing = facing

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Dash along the facing; in the air the dash holds its height."""
        first, last = LUNGE_FRAMES
        if first <= fighter.state_frame <= last:
            dash = fighter.facing.world * LUNGE_SPEED
            fighter.vel = Vec3(dash.x, dash.y, 0.0)
            fighter.fast_falling = False
            return True
        if fighter.state_frame < first:
            # Winding up: hang in place rather than keep falling or sliding.
            fighter.vel = ZERO3
            return True
        if fighter.grounded:
            return False
        if fighter.state_frame == last + 1:
            # Coming out of an air dash: keep only a little of its speed.
            slow = fighter.facing.world * fighter.character.movement.air_speed
            fighter.vel = Vec3(slow.x, slow.y, 0.0)
        physics.apply_gravity(fighter)
        return True


class RisingSpin(MoveScript):
    """Up special: leave the ground and climb, steering with the stick."""

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Climb at a fixed rate during the spin, then fall with weak drift."""
        first, last = RISING_SPIN_FRAMES
        frame = fighter.state_frame
        if frame < first:
            fighter.vel = ZERO3
            return True
        if frame <= last:
            if fighter.grounded:
                fighter.ground = GroundKind.NONE
                fighter.platform = NO_PLATFORM
            steer = _stick(fighter) * RISING_SPIN_STEER
            fighter.vel = Vec3(steer.x, steer.y, RISING_SPIN_RISE)
            fighter.fast_falling = False
            return True
        if fighter.grounded:
            return False
        physics.apply_gravity(fighter)
        physics.apply_air_drift(fighter)
        return True


register_script("rook.neutral_special", CrescentWave())
register_script("rook.side_special", Lunge())
register_script("rook.up_special", RisingSpin())
