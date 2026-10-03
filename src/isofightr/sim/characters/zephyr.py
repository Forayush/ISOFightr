"""Zephyr's special-move scripts (plan note "12 - Roster").

- Feather Darts (neutral): plain data, three quick weak projectiles.
- Slipstream (side): a dash along the stick, intangible in the middle, that hits on the way
  out.
- Gust Hop (up): after a short windup, a burst in any 3D direction (stick plus the up/down
  modifiers; straight up with nothing held), then helpless.
- Whirl (down): a spinning reflector that slows a fall.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from isofightr.sim.characters import MoveScript, register_script
from isofightr.sim.characters.common import aim_with_stick, dash_motion, direction_3d, fall, fly
from isofightr.sim.math3d import ZERO3, Vec3

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter
    from isofightr.sim.match import Match

SLIPSTREAM_FRAMES: Final[tuple[int, int]] = (6, 18)
SLIPSTREAM_SPEED: Final[float] = 0.24

GUST_WINDUP: Final[int] = 6
"""Gust Hop picks its direction on the frame after this windup."""
GUST_FRAMES: Final[int] = 16
GUST_SPEED: Final[float] = 0.30

WHIRL_GRAVITY_MULT: Final[float] = 0.3
WHIRL_MAX_FALL: Final[float] = 0.06


class Slipstream(MoveScript):
    """Side special: dash through opponents along the stick."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Aim with the stick."""
        aim_with_stick(fighter)

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Dash along the facing, holding height in the air."""
        return dash_motion(fighter, SLIPSTREAM_FRAMES, SLIPSTREAM_SPEED)


class GustHop(MoveScript):
    """Up special: a 3D burst in the chosen direction."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """No direction yet."""
        fighter.special_dir = ZERO3

    def on_frame(self, match: Match, fighter: Fighter) -> None:
        """Read the direction when the windup ends."""
        if fighter.state_frame == GUST_WINDUP + 1:
            fighter.special_dir = direction_3d(fighter)

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Hang during the windup, burst along the direction, then fall."""
        frame = fighter.state_frame
        if frame <= GUST_WINDUP:
            fighter.vel = ZERO3
            return True
        if frame <= GUST_WINDUP + GUST_FRAMES:
            fly(fighter, fighter.special_dir * GUST_SPEED)
            return True
        return fall(fighter)


class Whirl(MoveScript):
    """Down special: spinning in the air slows the fall."""

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Light gravity and a low fall speed while airborne."""
        if fighter.grounded:
            return False
        gravity = fighter.character.movement.gravity * WHIRL_GRAVITY_MULT
        vel = fighter.vel
        fighter.vel = Vec3(vel.x, vel.y, max(vel.z - gravity, -WHIRL_MAX_FALL))
        fighter.fast_falling = False
        return True


register_script("zephyr.side_special", Slipstream())
register_script("zephyr.up_special", GustHop())
register_script("zephyr.down_special", Whirl())
