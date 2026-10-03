"""Final effect art: hit sparks, dust puffs, launch trail, shockwave rings and the KO blast.

Plan note "09 - Art Direction" ("VFX style"): sparks tiered by knockback (white, yellow,
orange-red, then a KO burst), chunky round dust, a smoke trail that turns fiery on KO-strength
launches, iso ground rings, and a coloured KO beam. Every colour is a Resurrect 64 entry.
Drawn with Pillow; textures are made from these images by ``effect_renderer``.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from typing import Final

from PIL import Image, ImageDraw

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render.iso import project
from isofightr.sim.math3d import Vec3

Rgba = tuple[int, int, int, int]


def _rgba(value: str) -> Rgba:
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


TRANSPARENT: Final[Rgba] = (0, 0, 0, 0)
WHITE: Final[Rgba] = _rgba("ffffff")
CLOUD: Final[Rgba] = _rgba("c7dcd0")
CLOUD_SHADOW: Final[Rgba] = _rgba("9babb2")
CLOUD_EDGE: Final[Rgba] = _rgba("7f708a")

# --- sparks ---------------------------------------------------------------------------------
SPARK_SIZES: Final[tuple[int, ...]] = (15, 23, 31, 43)
SPARK_FRAME_SCALE: Final[tuple[float, ...]] = (0.6, 1.0, 1.0)
SPARK_INNER_RATIO: Final[float] = 0.3
SPARK_CORE_RATIO: Final[float] = 0.6
SPARK_RAY_TIER: Final[int] = 2
"""From this tier up a spark also throws four diagonal rays."""
TIER_COLORS: Final[tuple[tuple[Rgba, Rgba], ...]] = (
    (WHITE, CLOUD),
    (_rgba("fbff86"), _rgba("f9c22b")),
    (_rgba("fbb954"), _rgba("ea4f36")),
    (WHITE, _rgba("e83b3b")),
)
"""``(core, edge)`` of a normal hit's spark by tier: white, yellow, orange-red, KO red."""
EFFECT_COLORS: Final[dict[str, tuple[Rgba, Rgba]]] = {
    "slash": (WHITE, _rgba("8fd3ff")),
    "fire": (_rgba("fbb954"), _rgba("ea4f36")),
    "electric": (WHITE, _rgba("30e1b9")),
    "ice": (WHITE, _rgba("8fd3ff")),
    "darkness": (_rgba("eaaded"), _rgba("905ea9")),
}


def spark_colors(effect: str, tier: int) -> tuple[Rgba, Rgba]:
    """Return a spark's ``(core, edge)``: by tier for normal hits, by element otherwise."""
    return EFFECT_COLORS.get(effect) or TIER_COLORS[min(tier, len(TIER_COLORS) - 1)]


def _star(centre: float, outer: float, inner: float) -> list[tuple[float, float]]:
    points = []
    for index in range(8):
        angle = math.pi / 4 * index - math.pi / 2
        radius = outer if index % 2 == 0 else inner
        points.append((centre + radius * math.cos(angle), centre + radius * math.sin(angle)))
    return points


def build_spark(tier: int, effect: str, frame: int) -> Image.Image:
    """Return one frame of a hit spark: a star that bursts, then leaves its outline."""
    size = SPARK_SIZES[min(tier, len(SPARK_SIZES) - 1)]
    core, edge = spark_colors(effect, tier)
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    centre = (size - 1) / 2
    outer = centre * SPARK_FRAME_SCALE[min(frame, len(SPARK_FRAME_SCALE) - 1)]
    inner = outer * SPARK_INNER_RATIO
    if tier >= SPARK_RAY_TIER and frame < 2:
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            reach = outer * 0.95
            draw.line(
                (
                    centre + dx * reach * 0.35,
                    centre + dy * reach * 0.35,
                    centre + dx * reach * 0.7,
                    centre + dy * reach * 0.7,
                ),
                fill=edge,
                width=1,
            )
    if frame >= len(SPARK_FRAME_SCALE) - 1:
        draw.polygon(_star(centre, outer, inner), outline=edge)
    else:
        draw.polygon(_star(centre, outer, inner), fill=edge)
        draw.polygon(_star(centre, outer * SPARK_CORE_RATIO, inner * SPARK_CORE_RATIO), fill=core)
    for flip in (Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM):
        image = Image.alpha_composite(image.transpose(flip), image)
    return image


# --- dust and trail -------------------------------------------------------------------------
PUFF_SIZES: Final[dict[str, tuple[int, ...]]] = {
    "small": (6, 9, 11, 8),
    "big": (10, 14, 16, 12),
}
"""Puff diameter in pixels for each animation frame."""
TRAIL_SIZES: Final[tuple[int, ...]] = (10, 8, 6, 4)
TRAIL_COLORS: Final[dict[bool, tuple[Rgba, Rgba]]] = {
    False: (CLOUD, CLOUD_SHADOW),
    True: (_rgba("fbb954"), _rgba("ea4f36")),
}
"""``(light, shade)`` of a trail puff; the fiery one marks a KO-strength launch."""


def _puff(diameter: int, light: Rgba, shade: Rgba, outline: Rgba | None) -> Image.Image:
    """A round chunky puff, lit from the top left, shaded at the bottom right."""
    size = diameter + 2
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    last = diameter
    draw.ellipse((1, 1, last, last), fill=shade, outline=outline)
    inset = max(1, diameter // 5)
    draw.ellipse((1 + inset // 2, 1 + inset // 2, last - inset, last - inset), fill=light)
    return image


def build_puff(size: str, frame: int) -> Image.Image:
    """Return one frame of a dust puff (``"small"`` or ``"big"``): two puffs side by side,
    squashed 2:1 so they sit on the iso ground."""
    diameters = PUFF_SIZES[size]
    diameter = diameters[min(frame, len(diameters) - 1)]
    puff = _puff(diameter, WHITE if frame < 2 else CLOUD, CLOUD_SHADOW, CLOUD_EDGE)
    image = Image.new("RGBA", (puff.width * 2, puff.height), TRANSPARENT)
    image.alpha_composite(puff, (0, 0))
    image.alpha_composite(puff, (puff.width, 0))
    return image.resize((image.width, max(2, image.height * 3 // 4)), Image.Resampling.NEAREST)


def build_trail(fiery: bool, frame: int) -> Image.Image:
    """Return one frame of a launch-trail puff; it shrinks as it fades."""
    light, shade = TRAIL_COLORS[fiery]
    diameter = TRAIL_SIZES[min(frame, len(TRAIL_SIZES) - 1)]
    return _puff(diameter, light, shade, None)


# --- shockwave ring -------------------------------------------------------------------------
RING_RADII: Final[tuple[int, ...]] = (6, 11, 16, 20)
"""Half-width of the ring on screen, per frame (it is half as tall: the iso ground)."""


def build_ring(frame: int) -> Image.Image:
    """Return one frame of a shockwave ring on the ground."""
    radius = RING_RADII[min(frame, len(RING_RADII) - 1)]
    width, height = radius * 2 + 1, radius + 1
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    color = WHITE if frame < 2 else CLOUD
    draw.ellipse((0, 0, width - 1, height - 1), outline=color, width=2 if frame < 2 else 1)
    return image


# --- KO blast -------------------------------------------------------------------------------
KO_BEAM_LENGTH: Final[int] = 180
KO_BEAM_WIDTHS: Final[tuple[int, ...]] = (10, 26, 20, 12, 6)
KO_BEAM_ANGLES: Final[int] = 16
"""The beam's direction is rounded to one of this many angles (one image each)."""


def build_ko_beam(color: Rgba, angle_index: int, frame: int) -> Image.Image:
    """Return one frame of a KO blast: a beam in the player's colour with a white core,
    pointing ``angle_index * 360 / KO_BEAM_ANGLES`` degrees counter-clockwise from screen
    right (back toward the stage), its base at the image centre."""
    width = KO_BEAM_WIDTHS[min(frame, len(KO_BEAM_WIDTHS) - 1)]
    side = KO_BEAM_LENGTH * 2 + 2
    image = Image.new("RGBA", (side, side), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    middle = side // 2
    # Drawn pointing right from the centre, tapering to a point, then rotated.
    draw.polygon(
        [(middle, middle - width), (middle + KO_BEAM_LENGTH, middle), (middle, middle + width)],
        fill=color,
    )
    core = max(1, width // 3)
    draw.polygon(
        [
            (middle, middle - core),
            (middle + KO_BEAM_LENGTH * 3 // 4, middle),
            (middle, middle + core),
        ],
        fill=WHITE,
    )
    draw.ellipse((middle - width, middle - width, middle + width, middle + width), fill=color)
    draw.ellipse(
        (middle - core * 2, middle - core * 2, middle + core * 2, middle + core * 2), fill=WHITE
    )
    angle = angle_index * 360 / KO_BEAM_ANGLES
    return image.rotate(angle, resample=Image.Resampling.NEAREST)


KO_BEAM_MARGIN = 20
"""How far inside the edge of the view a KO beam starts, in pixels."""


def ko_beam_placement(
    position: Vec3, normal: Vec3, camera_centre: tuple[int, int]
) -> tuple[int, tuple[float, float]]:
    """Return a KO beam's angle index and its base point in world pixels: where the fighter
    left, pulled inside the view, pointing back along the crossed face's normal."""
    sx, sy = project(position.x, position.y, position.z)
    left = camera_centre[0] - NATIVE_W / 2 + KO_BEAM_MARGIN
    right = camera_centre[0] + NATIVE_W / 2 - KO_BEAM_MARGIN
    bottom = camera_centre[1] - NATIVE_H / 2 + KO_BEAM_MARGIN
    top = camera_centre[1] + NATIVE_H / 2 - KO_BEAM_MARGIN
    base = (min(max(sx, left), right), min(max(sy, bottom), top))
    tip_x, tip_y = project(-normal.x, -normal.y, -normal.z)
    origin_x, origin_y = project(0.0, 0.0, 0.0)
    angle = math.atan2(tip_y - origin_y, tip_x - origin_x)
    step = 2 * math.pi / KO_BEAM_ANGLES
    return round(angle / step) % KO_BEAM_ANGLES, base
