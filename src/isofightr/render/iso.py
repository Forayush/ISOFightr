"""World-to-screen projection (2:1 dimetric) and its inverse.

Implements "Projection" and the depth key in the plan note "03 - Isometric World and
Rendering". This is the only place world units become pixels. Screen space here is y-up and
unbounded ("world pixels"); the camera later shifts it into the 640x360 native buffer.

Whole-number screen coordinates are pixel *boundaries*: pixel ``k`` covers ``[k, k + 1)``. A tile
corner at integer world coordinates therefore lands exactly on a pixel corner.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from typing import Final

from isofightr.config import TILE_H, TILE_W, Z_PX
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage

HALF_TILE_W: Final[float] = TILE_W / 2
HALF_TILE_H: Final[float] = TILE_H / 2


def project(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
    """Project a world point to screen pixels ``(sx, sy)`` with y up."""
    return ((x - y) * HALF_TILE_W, -(x + y) * HALF_TILE_H + z * Z_PX)


def project_point(point: Vec3) -> tuple[float, float]:
    """Project a world-space :class:`Vec3` to screen pixels."""
    return project(point.x, point.y, point.z)


def unproject(sx: float, sy: float, z: float = 0.0) -> tuple[float, float]:
    """Return the world ``(x, y)`` on the horizontal plane at height ``z`` under a screen point."""
    difference = sx / HALF_TILE_W  # x - y
    total = -(sy - z * Z_PX) / HALF_TILE_H  # x + y
    return ((difference + total) / 2, (total - difference) / 2)


def depth_key(x: float, y: float) -> float:
    """Return the depth key of a ground position: larger is nearer the camera, drawn later."""
    return x + y


def stage_screen_centre(stage: Stage) -> tuple[float, float]:
    """Return the middle of everything a stage draws (its ground, its sides down to the
    underside, and its platforms), in world pixels: where to point a camera to frame it."""
    points = []
    bottom = stage.underside
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None:
                continue
            for x, y in ((cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1)):
                points.append(project(x, y, cell.top))
                points.append(project(x, y, bottom))
    for platform in stage.soft_platforms:
        for x, y in ((platform.x0, platform.y0), (platform.x1, platform.y1)):
            points.append(project(x, y, platform.z))
    if not points:
        return (0.0, 0.0)
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
