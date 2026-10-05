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

from PIL import Image, ImageChops, ImageDraw

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
SPARK_SIZES: Final[tuple[int, ...]] = (19, 23, 31, 43)
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


# --- launch streaks -------------------------------------------------------------------------
STREAK_SIZE: Final[int] = 33
STREAK_ANGLES: Final[int] = 16
STREAK_LINES: Final[tuple[tuple[float, int], ...]] = ((-5.0, 6), (0.0, 8), (5.0, 5))
"""``(sideways offset, length)`` of each speed line, in pixels."""
STREAK_START: Final[tuple[float, ...]] = (5.0, 9.0)
"""How far from the centre the lines start, by animation frame: they fly outward."""
STREAK_COLORS: Final[tuple[Rgba, ...]] = (WHITE, CLOUD)


def build_streak(angle: int, frame: int) -> Image.Image:
    """Return speed lines for a launch: three short strokes pointing along screen direction
    ``angle`` (of ``STREAK_ANGLES``, counter-clockwise from right), 1 px wide so they never
    hide the fighter behind them. The second frame is further out and fainter."""
    image = Image.new("RGBA", (STREAK_SIZE, STREAK_SIZE), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    turn = 2.0 * math.pi * (angle % STREAK_ANGLES) / STREAK_ANGLES
    along = (math.cos(turn), -math.sin(turn))  # image y runs down
    across = (-along[1], along[0])
    centre = (STREAK_SIZE - 1) / 2
    start = STREAK_START[min(frame, len(STREAK_START) - 1)]
    color = STREAK_COLORS[min(frame, len(STREAK_COLORS) - 1)]
    for sideways, length in STREAK_LINES:
        shorter = length - 2 * min(frame, 1)
        x0 = centre + across[0] * sideways + along[0] * start
        y0 = centre + across[1] * sideways + along[1] * start
        x1 = x0 + along[0] * shorter
        y1 = y0 + along[1] * shorter
        draw.line((round(x0), round(y0), round(x1), round(y1)), fill=color, width=1)
    return image


# --- move effects (decision D-060) ----------------------------------------------------------
FAMILIES: Final[dict[str, tuple[Rgba, Rgba, Rgba]]] = {
    "pale": (WHITE, _rgba("8fd3ff"), _rgba("4d9be6")),
    "stone": (CLOUD, CLOUD_SHADOW, CLOUD_EDGE),
    "wind": (WHITE, _rgba("8ff8e2"), _rgba("30e1b9")),
    "fire": (_rgba("fbff86"), _rgba("f9c22b"), _rgba("ea4f36")),
    "rune": (_rgba("eaaded"), _rgba("a884f3"), _rgba("905ea9")),
    "gold": (WHITE, _rgba("fbff86"), _rgba("f9c22b")),
    "vine": (_rgba("91db69"), _rgba("1ebc73"), _rgba("239063")),
}
"""``(core, mid, edge)`` colours of an effect by family: what kind of move made it."""
Family = tuple[Rgba, Rgba, Rgba]


def _with_alpha(color: Rgba, alpha: int) -> Rgba:
    return (color[0], color[1], color[2], alpha)


def _ring_dots(
    draw: ImageDraw.ImageDraw, centre: float, radius: float, count: int, color: Rgba, turn: float
) -> None:
    for index in range(count):
        angle = turn + 2.0 * math.pi * index / count
        x = centre + math.cos(angle) * radius
        y = centre + math.sin(angle) * radius
        draw.point((round(x), round(y)), fill=color)


def _circle(
    draw: ImageDraw.ImageDraw,
    centre: float,
    radius: float,
    fill: Rgba | None = None,
    outline: Rgba | None = None,
) -> None:
    box = (centre - radius, centre - radius, centre + radius, centre + radius)
    draw.ellipse(box, fill=fill, outline=outline)


def _canvas(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw, float]:
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    return image, ImageDraw.Draw(image), (size - 1) / 2


def _muzzle(colors: Family, variant: int, frame: int) -> Image.Image:
    image, draw, centre = _canvas(17)
    core, mid, edge = colors
    if frame == 0:
        draw.polygon(_star(centre, 5.0, 1.8), fill=core)
    elif frame == 1:
        _circle(draw, centre, 5.0, outline=mid)
        draw.polygon(_star(centre, 3.0, 1.2), fill=core)
    else:
        _ring_dots(draw, centre, 7.0, 8, edge, 0.3)
    return image


def _burst_hit(colors: Family, variant: int, frame: int) -> Image.Image:
    image, draw, centre = _canvas(29)
    core, mid, edge = colors
    if frame == 0:
        draw.polygon(_star(centre, 8.0, 3.0), fill=mid)
        draw.polygon(_star(centre, 5.0, 2.0), fill=core)
    elif frame == 1:
        _circle(draw, centre, 8.0, outline=mid)
        for index in range(8):
            angle = math.pi / 4 * index + 0.4
            x0, y0 = centre + math.cos(angle) * 9, centre + math.sin(angle) * 9
            x1, y1 = centre + math.cos(angle) * 12, centre + math.sin(angle) * 12
            draw.line((round(x0), round(y0), round(x1), round(y1)), fill=core)
    elif frame == 2:
        _ring_dots(draw, centre, 11.0, 16, edge, 0.0)
    else:
        _ring_dots(draw, centre, 13.0, 8, edge, 0.4)
    return image


def _burst_fade(colors: Family, variant: int, frame: int) -> Image.Image:
    image, draw, centre = _canvas(21)
    core, mid, edge = colors
    if frame == 0:
        _circle(draw, centre, 4.0, fill=_with_alpha(mid, 160))
        _circle(draw, centre, 2.0, fill=core)
    elif frame == 1:
        _circle(draw, centre, 6.0, outline=mid)
    else:
        _ring_dots(draw, centre, 8.0, 6, edge, 0.5)
    return image


def _burst_ground(colors: Family, variant: int, frame: int) -> Image.Image:
    width, height = 33, 21
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    core, mid, edge = colors
    cx, base = (width - 1) / 2, height - 6
    reach = 6 + frame * 4
    draw.ellipse((cx - reach, base - reach / 2, cx + reach, base + reach / 2), outline=mid)
    chips = ((-7, 3), (-2, 6), (4, 5), (8, 2), (0, 9))
    for index, (dx, up) in enumerate(chips):
        rise = up + frame * 2 - frame * frame
        color = core if index % 2 == 0 else edge
        x, y = round(cx + dx * (1 + frame * 0.3)), round(base - rise)
        draw.rectangle((x, y, x + 1, y + 1), fill=color)
    return image


def _glow(colors: Family, variant: int, frame: int) -> Image.Image:
    level, pulse = divmod(variant, 2)
    radius = 3 + level * 2 + pulse
    image, draw, centre = _canvas(2 * (radius + 2) + 1)
    core, mid, edge = colors
    _circle(draw, centre, radius, fill=_with_alpha(edge, 70))
    _circle(draw, centre, radius * 0.6, fill=_with_alpha(mid, 150))
    _circle(draw, centre, max(1.0, radius * 0.25), fill=core)
    _ring_dots(draw, centre, radius + 1, 3 + level, core, pulse * 0.9 + level)
    return image


def _pop(colors: Family, variant: int, frame: int) -> Image.Image:
    image, draw, centre = _canvas(35)
    core, mid, _ = colors
    _circle(draw, centre, 8.0 + frame * 4, outline=core if frame == 0 else mid)
    if frame < 2:
        _ring_dots(draw, centre, 5.0 + frame * 5, 8, core, 0.2)
    return image


def _ember(colors: Family, variant: int, frame: int) -> Image.Image:
    image = Image.new("RGBA", (3, 3), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    if frame == 0:
        draw.rectangle((0, 0, 1, 1), fill=colors[0])
    else:
        draw.point((1, 1), fill=colors[min(frame, 2)])
    return image


def _ribbon(colors: Family, variant: int, frame: int) -> Image.Image:
    image = Image.new("RGBA", (5, 5), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    radius = (2.0, 1.5, 1.0)[min(frame, 2)]
    alpha = (255, 190, 120)[min(frame, 2)]
    _circle(draw, 2.0, radius, fill=_with_alpha(colors[2], alpha))
    if frame < 2:
        draw.point((2, 2), fill=_with_alpha(colors[0], alpha))
    return image


FX_KINDS: Final[dict[str, tuple[int, int]]] = {
    "muzzle": (3, 2),
    "burst_hit": (4, 3),
    "burst_fade": (3, 3),
    "burst_ground": (3, 4),
    "glow": (1, 1),
    "pop": (3, 3),
    "ember": (3, 5),
    "ribbon": (3, 6),
}
"""``(frames, ticks per frame)`` of each effect kind."""
_FX_BUILDERS = {
    "muzzle": _muzzle,
    "burst_hit": _burst_hit,
    "burst_fade": _burst_fade,
    "burst_ground": _burst_ground,
    "glow": _glow,
    "pop": _pop,
    "ember": _ember,
    "ribbon": _ribbon,
}


def fx_lifetime(kind: str) -> int:
    """Return how many ticks an effect of ``kind`` lasts."""
    frames, ticks = FX_KINDS[kind]
    return frames * ticks


def build_fx(kind: str, family: str, variant: int, frame: int) -> Image.Image:
    """Return one frame of a move effect: ``kind`` is its shape, ``family`` its colours,
    ``variant`` a size or direction that depends on the kind."""
    frames, _ = FX_KINDS[kind]
    return _FX_BUILDERS[kind](FAMILIES[family], variant, min(frame, frames - 1))


# --- special-move effects (decision D-060, group 3) -----------------------------------------
WHIRL_FRAMES: Final[int] = 4
CRACK_SIZE: Final[tuple[int, int]] = (45, 23)
CRACK_ALPHAS: Final[tuple[int, ...]] = (255, 200, 130, 70)
"""Opacity of the ground crack as it fades out."""
CRACK_COLOR: Final[Rgba] = _rgba("3e3546")
CRACK_EDGE: Final[Rgba] = _rgba("625565")
CRACK_LINES: Final[tuple[tuple[tuple[float, float], ...], ...]] = (
    ((0.0, 0.0), (0.22, -0.1), (0.45, 0.02), (0.8, -0.12), (0.98, -0.02)),
    ((0.0, 0.0), (-0.25, 0.08), (-0.5, -0.05), (-0.78, 0.1), (-0.97, 0.0)),
    ((0.0, 0.0), (0.12, 0.35), (0.3, 0.55), (0.42, 0.9)),
    ((0.0, 0.0), (-0.1, -0.4), (-0.32, -0.6), (-0.4, -0.92)),
    ((0.0, 0.0), (0.3, -0.45), (0.55, -0.7)),
    ((0.0, 0.0), (-0.3, 0.5), (-0.6, 0.72)),
)
"""Crack branches from the centre, in units of the ellipse's half width and half height."""


def _whirl(colors: Family, variant: int, frame: int) -> Image.Image:
    """A wind ring around the body: two arcs of an ellipse that turn with ``variant``."""
    width, height = 43, 31
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    core, mid, edge = colors
    turn = (variant % WHIRL_FRAMES) * 45
    for box, color, offset in (
        ((1, 6, width - 2, height - 7), mid, 0),
        ((6, 10, width - 7, height - 11), core, 90),
    ):
        for start in (turn + offset, turn + offset + 180):
            draw.arc(box, start, start + 110, fill=color)
    _ring_dots(draw, (width - 1) / 2, 14.0, 3, _with_alpha(edge, 200), turn / 30.0)
    return image


def _glint(colors: Family, variant: int, frame: int) -> Image.Image:
    """A four-point sparkle; ``variant`` 1 is its bigger pulse."""
    image, draw, centre = _canvas(11)
    reach = 3 + (variant % 2) * 2
    draw.line((centre - reach, centre, centre + reach, centre), fill=colors[0])
    draw.line((centre, centre - reach, centre, centre + reach), fill=colors[0])
    draw.point((centre, centre), fill=colors[1])
    return image


def _vine(colors: Family, variant: int, frame: int) -> Image.Image:
    """One link of a vine: a knot, with a leaf on every other link."""
    image, draw, centre = _canvas(5)
    core, mid, edge = colors
    draw.rectangle((centre - 1, centre - 1, centre, centre), fill=mid)
    draw.point((centre, centre), fill=edge)
    if variant % 2:
        draw.point((centre + 1, centre - 2), fill=core)
        draw.point((centre - 2, centre + 1), fill=core)
    return image


def _streak_down(colors: Family, variant: int, frame: int) -> Image.Image:
    """Three short vertical strokes above a diving fighter."""
    image = Image.new("RGBA", (15, 11), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    color = colors[0] if frame == 0 else colors[1]
    for x, top, length in ((2, 2, 6), (7, 0, 8), (12, 3, 5)):
        draw.line((x, top + frame * 2, x, top + length), fill=color)
    return image


FX_KINDS.update({"whirl": (1, 1), "glint": (1, 1), "vine": (1, 1), "streak_down": (2, 3)})
_FX_BUILDERS.update({"whirl": _whirl, "glint": _glint, "vine": _vine, "streak_down": _streak_down})


def build_crack(stage_of_fade: int) -> Image.Image:
    """Return the ground crack left by a heavy landing: jagged branches inside an iso
    ellipse, drawn flat on the ground and fading out over ``CRACK_ALPHAS``."""
    width, height = CRACK_SIZE
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    alpha = CRACK_ALPHAS[min(stage_of_fade, len(CRACK_ALPHAS) - 1)]
    cx, cy = (width - 1) / 2, (height - 1) / 2
    for index, branch in enumerate(CRACK_LINES):
        points = [(cx + x * (cx - 1), cy + y * (cy - 1)) for x, y in branch]
        color = CRACK_COLOR if index < 4 else CRACK_EDGE
        draw.line(points, fill=_with_alpha(color, alpha), width=1)
    draw.ellipse((cx - 2, cy - 1, cx + 2, cy + 1), fill=_with_alpha(CRACK_COLOR, alpha))
    return image


# --- shield bubble and small extras (decision D-060, groups 4 and 5) ------------------------
SHIELD_FILL_ALPHA: Final[int] = 78
SHIELD_FACET_ALPHA: Final[int] = 120
SHIELD_RIM_ALPHA: Final[int] = 230
SHIELD_SHIMMER_FRAMES: Final[int] = 2


def build_shield(color: Rgba, width: int, height: int, frame: int) -> Image.Image:
    """Return the shield bubble: a faceted, translucent dome in the player's colour with a
    bright rim and a highlight that shimmers between two frames. Its size is the shield's,
    so it visibly shrinks as the shield wears down."""
    width, height = max(width, 5), max(height, 5)
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    box = (0, 0, width - 1, height - 1)
    draw.ellipse(box, fill=_with_alpha(color, SHIELD_FILL_ALPHA))
    facets = Image.new("RGBA", (width, height), TRANSPARENT)
    lines = ImageDraw.Draw(facets)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    ring = [
        (cx + math.cos(math.pi / 3 * i + frame * 0.5) * cx * 0.55,
         cy + math.sin(math.pi / 3 * i + frame * 0.5) * cy * 0.55)
        for i in range(6)
    ]  # fmt: skip
    facet = _with_alpha(WHITE, SHIELD_FACET_ALPHA)
    lines.polygon(ring, outline=facet)
    for index, (x, y) in enumerate(ring):
        angle = math.pi / 3 * index + frame * 0.5
        lines.line((x, y, cx + math.cos(angle) * cx, cy + math.sin(angle) * cy), fill=facet)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    # Replace, never blend: every pixel keeps a palette colour.
    drawn = facets.getchannel("A").point(lambda value: 255 if value else 0)
    image.paste(facets, (0, 0), ImageChops.multiply(mask, drawn))
    draw.ellipse(box, outline=_with_alpha(color, 255))
    start = 200 + frame * 25
    draw.arc(
        (1, 1, width - 2, height - 2), start, start + 60, fill=_with_alpha(WHITE, SHIELD_RIM_ALPHA)
    )
    return image


def _ripple(colors: Family, variant: int, frame: int) -> Image.Image:
    """A ring spreading over a shield where a hit landed."""
    image, draw, centre = _canvas(23)
    _circle(draw, centre, 3.0 + frame * 3.5, outline=colors[0] if frame == 0 else colors[1])
    if frame == 0:
        _circle(draw, centre, 1.5, fill=colors[0])
    return image


def _air_ring(colors: Family, variant: int, frame: int) -> Image.Image:
    """A flat ring under the feet of an air jump, with a few feathers of wind."""
    width, height = 27, 15
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    reach = 5 + frame * 3
    color = colors[0] if frame == 0 else colors[1]
    draw.ellipse((cx - reach, cy - reach / 2, cx + reach, cy + reach / 2), outline=color)
    for dx in (-reach - 1, reach + 1):
        draw.line((cx + dx, cy, cx + dx, cy + 2 + frame), fill=colors[2])
    return image


def _slash(colors: Family, variant: int, frame: int) -> Image.Image:
    """A cut line across a slashing hit."""
    image, draw, centre = _canvas(27)
    reach = 8 + frame * 3
    draw.line(
        (centre - reach, centre + reach * 0.6, centre + reach, centre - reach * 0.6), fill=colors[0]
    )
    if frame == 0:
        draw.line(
            (
                centre - reach + 1,
                centre + reach * 0.6 + 1,
                centre + reach - 1,
                centre - reach * 0.6 + 1,
            ),
            fill=colors[1],
        )
    return image


def _implode(colors: Family, variant: int, frame: int) -> Image.Image:
    """A ring pulling inward (a darkness hit): it shrinks from frame to frame."""
    image, draw, centre = _canvas(27)
    _circle(draw, centre, 11.0 - frame * 4, outline=colors[1 if frame < 2 else 0])
    _ring_dots(draw, centre, 12.0 - frame * 4, 6, colors[2], frame * 0.5)
    return image


FX_KINDS.update({"ripple": (3, 3), "air_ring": (3, 3), "slash": (2, 3), "implode": (3, 3)})
_FX_BUILDERS.update(
    {"ripple": _ripple, "air_ring": _air_ring, "slash": _slash, "implode": _implode}
)
