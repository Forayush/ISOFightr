"""Clips a fighter's blob shadow to the surface it falls on.

Plan note "03 - Isometric World and Rendering" ("Shadows and readability"): the shadow and
player ring sit on the highest solid surface beneath the fighter. Near an edge, an unclipped
ellipse would hang in mid-air, so pixels that are not over that same surface are masked out.

Pure Python plus Pillow (no ``arcade``), so the clipping is unit tested without a window.
"""

import math
from typing import Final

from PIL import Image, ImageChops

from isofightr.config import SURFACE_EPSILON
from isofightr.render.iso import unproject
from isofightr.render.placeholder_art import SHADOW_HEIGHT, SHADOW_WIDTH
from isofightr.sim.stage import Stage

EDGE_NUDGE_PX: Final[float] = 0.5
"""Sample each pixel this far toward the shadow centre, so a pixel that a tile's stair-step
edge includes is not clipped just because its exact centre falls outside the ideal edge."""

FULL_MASK: Final[bytes] = bytes([1]) * (SHADOW_WIDTH * SHADOW_HEIGHT)


def _on_surface(stage: Stage, x: float, y: float, surface_z: float) -> bool:
    support = stage.support_below(x, y, surface_z)
    return support is not None and abs(support - surface_z) <= SURFACE_EPSILON


def shadow_mask(stage: Stage, centre_x: int, centre_y: int, surface_z: float) -> bytes:
    """Return one byte per shadow pixel (row-major, top row first): 1 = over the surface.

    ``centre_x``/``centre_y`` are the shadow sprite's centre in whole world pixels (y up) and
    ``surface_z`` is the height of the surface the shadow lies on.
    """
    left = centre_x - SHADOW_WIDTH / 2
    top = centre_y + SHADOW_HEIGHT / 2

    # Fast path: if every cell the sprite's corners can touch is part of the surface, so is
    # every pixel. The screen rectangle maps to a diamond in world space; its corners bound it.
    corners = [
        unproject(left + dx, top - dy, surface_z)
        for dx in (0, SHADOW_WIDTH)
        for dy in (0, SHADOW_HEIGHT)
    ]
    cell_xs = range(
        math.floor(min(x for x, _ in corners)), math.floor(max(x for x, _ in corners)) + 1
    )
    cell_ys = range(
        math.floor(min(y for _, y in corners)), math.floor(max(y for _, y in corners)) + 1
    )
    if all(_on_surface(stage, cx + 0.5, cy + 0.5, surface_z) for cx in cell_xs for cy in cell_ys):
        return FULL_MASK

    mask = bytearray(SHADOW_WIDTH * SHADOW_HEIGHT)
    for row in range(SHADOW_HEIGHT):
        sample_y = top - row - 0.5
        sample_y += math.copysign(EDGE_NUDGE_PX, centre_y - sample_y)
        for column in range(SHADOW_WIDTH):
            sample_x = left + column + 0.5
            sample_x += math.copysign(EDGE_NUDGE_PX, centre_x - sample_x)
            x, y = unproject(sample_x, sample_y, surface_z)
            mask[row * SHADOW_WIDTH + column] = _on_surface(stage, x, y, surface_z)
    return bytes(mask)


def apply_mask(image: Image.Image, mask: bytes) -> Image.Image:
    """Return a copy of a shadow image with every masked-out pixel made transparent."""
    if mask == FULL_MASK:
        return image
    keep = Image.frombytes("L", (SHADOW_WIDTH, SHADOW_HEIGHT), bytes(v * 255 for v in mask))
    clipped = image.copy()
    clipped.putalpha(ImageChops.multiply(image.getchannel("A"), keep))
    return clipped
