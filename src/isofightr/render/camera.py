"""Fixed-zoom follow camera: where the 640x360 view sits in world pixels.

Implements "Camera" in the plan note "03 - Isometric World and Rendering": centre on the
bounding box of the tracked positions, clamp to the stage's camera bounds, pan at about 0.1
per tick. Zoom stays at 1.0 for the MVP (decision D-012).

The centre is tracked as floats and rounded to whole pixels only when drawing, so everything
on screen shifts together and pixel art never shimmers.

Pure Python (no ``arcade``), so the maths is unit tested without a window.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from isofightr.config import CAMERA_LERP, NATIVE_H, NATIVE_W
from isofightr.render.depth import ScreenRect
from isofightr.render.iso import project_point
from isofightr.sim.math3d import Box3, Vec3


def snap(value: float) -> int:
    """Round to the nearest whole pixel, halves up (Python's ``round`` goes to even)."""
    return math.floor(value + 0.5)


def bounds_on_screen(bounds: Box3) -> ScreenRect:
    """Return the screen rectangle that encloses a world-space box."""
    points = [project_point(corner) for corner in bounds.corners()]
    return ScreenRect(
        left=min(sx for sx, _ in points),
        bottom=min(sy for _, sy in points),
        right=max(sx for sx, _ in points),
        top=max(sy for _, sy in points),
    )


def follow_target(positions: Sequence[Vec3]) -> tuple[float, float]:
    """Return the centre of the bounding box of the projected positions."""
    points = [project_point(position) for position in positions]
    xs = [sx for sx, _ in points]
    ys = [sy for _, sy in points]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def clamp_centre(
    centre: tuple[float, float],
    limits: ScreenRect,
    view_width: float = NATIVE_W,
    view_height: float = NATIVE_H,
) -> tuple[float, float]:
    """Keep the view rectangle inside ``limits``.

    On an axis where the limits are narrower than the view, the camera locks to their centre.
    """
    return (
        _clamp_axis(centre[0], limits.left, limits.right, view_width),
        _clamp_axis(centre[1], limits.bottom, limits.top, view_height),
    )


def _clamp_axis(value: float, low: float, high: float, view: float) -> float:
    if high - low <= view:
        return (low + high) / 2
    return min(max(value, low + view / 2), high - view / 2)


@dataclass(slots=True)
class FollowCamera:
    """The camera centre in world pixels, panning smoothly toward what it follows."""

    limits: ScreenRect
    x: float = 0.0
    y: float = 0.0
    clamped: bool = True
    """Debug switch: when off, the camera follows its target past the stage bounds."""

    def target(self, positions: Sequence[Vec3]) -> tuple[float, float]:
        """Return where the camera wants to be for these positions."""
        wanted = follow_target(positions)
        return clamp_centre(wanted, self.limits) if self.clamped else wanted

    def snap_to(self, positions: Sequence[Vec3]) -> None:
        """Jump straight to the target (stage load, reset)."""
        self.x, self.y = self.target(positions)

    def update(self, positions: Sequence[Vec3]) -> None:
        """Pan one tick toward the target."""
        target_x, target_y = self.target(positions)
        self.x += (target_x - self.x) * CAMERA_LERP
        self.y += (target_y - self.y) * CAMERA_LERP

    @property
    def pixel_centre(self) -> tuple[int, int]:
        """The centre rounded to whole pixels, which is what drawing uses."""
        return (snap(self.x), snap(self.y))
