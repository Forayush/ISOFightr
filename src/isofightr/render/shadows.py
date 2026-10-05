"""Clips a fighter's blob shadow to the surface it falls on.

Plan note "03 - Isometric World and Rendering" ("Shadows and readability"): the shadow and
player ring sit on the highest solid surface beneath the fighter. Near an edge, an unclipped
ellipse would hang in mid-air, so pixels that are not over that same surface are masked out.

Pure Python plus Pillow (no ``arcade``), so the clipping is unit tested without a window.
"""

import math
from functools import cache
from typing import Final

from PIL import Image, ImageChops

from isofightr.config import SURFACE_EPSILON
from isofightr.render.iso import unproject
from isofightr.render.placeholder_art import SHADOW_HEIGHT, SHADOW_WIDTH
from isofightr.sim.stage import Stage

EDGE_NUDGE_PX: Final[float] = 0.5
"""Sample each pixel this far toward the shadow centre, so a pixel that a tile's stair-step
edge includes is not clipped just because its exact centre falls outside the ideal edge."""


@cache
def full_mask(width: int, height: int) -> bytes:
    """The mask of a sprite that lies wholly on its surface (one shared object per size, so
    callers can compare with ``is``)."""
    return bytes([1]) * (width * height)


FULL_MASK: Final[bytes] = full_mask(SHADOW_WIDTH, SHADOW_HEIGHT)
"""The full mask of a fighter's shadow."""


def _on_surface(stage: Stage, x: float, y: float, surface_z: float) -> bool:
    support = stage.support_below(x, y, surface_z)
    return support is not None and abs(support - surface_z) <= SURFACE_EPSILON


def shadow_mask(
    stage: Stage,
    centre_x: float,
    centre_y: float,
    surface_z: float,
    width: int = SHADOW_WIDTH,
    height: int = SHADOW_HEIGHT,
) -> bytes:
    """Return one byte per pixel of a flat sprite (row-major, top row first): 1 = over the
    surface.

    ``centre_x``/``centre_y`` are the sprite's centre in world pixels (y up), ``surface_z``
    is the height of the surface it lies on, and ``width`` x ``height`` its size (a fighter's
    shadow by default; ground decals pass their own).
    """
    left = centre_x - width / 2
    top = centre_y + height / 2

    # Fast path: if every cell the sprite's corners can touch is part of the surface, so is
    # every pixel. The screen rectangle maps to a diamond in world space; its corners bound it.
    corners = [unproject(left + dx, top - dy, surface_z) for dx in (0, width) for dy in (0, height)]
    cell_xs = range(
        math.floor(min(x for x, _ in corners)), math.floor(max(x for x, _ in corners)) + 1
    )
    cell_ys = range(
        math.floor(min(y for _, y in corners)), math.floor(max(y for _, y in corners)) + 1
    )
    if all(_on_surface(stage, cx + 0.5, cy + 0.5, surface_z) for cx in cell_xs for cy in cell_ys):
        return full_mask(width, height)

    mask = bytearray(width * height)
    for row in range(height):
        sample_y = top - row - 0.5
        sample_y += math.copysign(EDGE_NUDGE_PX, centre_y - sample_y)
        for column in range(width):
            sample_x = left + column + 0.5
            sample_x += math.copysign(EDGE_NUDGE_PX, centre_x - sample_x)
            x, y = unproject(sample_x, sample_y, surface_z)
            mask[row * width + column] = _on_surface(stage, x, y, surface_z)
    return bytes(mask)


def apply_mask(image: Image.Image, mask: bytes) -> Image.Image:
    """Return a copy of a flat image with every masked-out pixel made transparent."""
    if mask == full_mask(image.width, image.height):
        return image
    keep = Image.frombytes("L", image.size, bytes(v * 255 for v in mask))
    clipped = image.copy()
    clipped.putalpha(ImageChops.multiply(image.getchannel("A"), keep))
    return clipped
