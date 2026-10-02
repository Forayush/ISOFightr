"""``InputFrame``, ``InputBuffer`` and direction helpers.

Plan notes "08 - Controls and Input" and "07 - Fighter State Machine and Move Data".
M1 provides the direction helpers (``Dir8``, stick-to-world, facing quantization); ``InputFrame``
and ``InputBuffer`` arrive in M2.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from enum import IntEnum
from typing import Final

from isofightr.config import FACING_HYSTERESIS_DEGREES
from isofightr.sim.math3d import EPSILON, Vec2

SQRT2: Final[float] = math.sqrt(2.0)
DIR8_STEP_DEGREES: Final[float] = 45.0
FULL_TURN_DEGREES: Final[float] = 360.0


class Dir8(IntEnum):
    """The eight facings, named by **screen** compass, counter-clockwise from screen-right.

    The value times 45 degrees is the direction's angle in stick space (``u`` right, ``v`` up).
    """

    E = 0
    NE = 1
    N = 2
    NW = 3
    W = 4
    SW = 5
    S = 6
    SE = 7

    @property
    def stick_degrees(self) -> float:
        """The facing's angle in stick space, in degrees counter-clockwise from screen-right."""
        return self.value * DIR8_STEP_DEGREES

    @property
    def world(self) -> Vec2:
        """The facing as a unit vector on the world ground plane."""
        return _WORLD_VECTORS[self]


def stick_to_world(u: float, v: float) -> Vec2:
    """Convert a screen-relative stick vector (``u`` right, ``v`` up) to a world ground vector.

    Pushing right moves right on screen: screen-east is world ``(+1, -1)/sqrt(2)``. The
    transform is a pure rotation, so magnitude is preserved (plan note 08).
    """
    return Vec2((u - v) / SQRT2, (-u - v) / SQRT2)


def world_to_stick(world: Vec2) -> tuple[float, float]:
    """Inverse of :func:`stick_to_world`: a world ground vector as screen-relative ``(u, v)``."""
    return ((world.x - world.y) / SQRT2, (-world.x - world.y) / SQRT2)


def facing_from_move(move: Vec2, current: Dir8 | None = None) -> Dir8 | None:
    """Snap a world move vector to the nearest of the eight facings.

    With a ``current`` facing, the vector must point more than ``FACING_HYSTERESIS_DEGREES``
    past the 45-degree boundary before the facing changes, which stops jitter when the stick
    sits on a boundary. A zero vector keeps ``current``.
    """
    if move.length_squared() < EPSILON:
        return current
    u, v = world_to_stick(move)
    degrees = math.degrees(math.atan2(v, u))
    if current is not None:
        offset = _wrap_degrees(degrees - current.stick_degrees)
        if abs(offset) <= DIR8_STEP_DEGREES / 2 + FACING_HYSTERESIS_DEGREES:
            return current
    return Dir8(round(degrees / DIR8_STEP_DEGREES) % len(Dir8))


def _wrap_degrees(degrees: float) -> float:
    """Wrap an angle into ``[-180, 180)``."""
    half_turn = FULL_TURN_DEGREES / 2
    return (degrees + half_turn) % FULL_TURN_DEGREES - half_turn


_DIAGONAL: Final[float] = 1.0 / SQRT2

# The table from the plan note "03 - Isometric World and Rendering": stage edges are
# world-axis-aligned, so the four screen diagonals are the exact world axes.
_WORLD_VECTORS: Final[dict[Dir8, Vec2]] = {
    Dir8.E: Vec2(_DIAGONAL, -_DIAGONAL),
    Dir8.NE: Vec2(0.0, -1.0),
    Dir8.N: Vec2(-_DIAGONAL, -_DIAGONAL),
    Dir8.NW: Vec2(-1.0, 0.0),
    Dir8.W: Vec2(-_DIAGONAL, _DIAGONAL),
    Dir8.SW: Vec2(0.0, 1.0),
    Dir8.S: Vec2(_DIAGONAL, _DIAGONAL),
    Dir8.SE: Vec2(1.0, 0.0),
}
