"""Projectile art: a look for each projectile instead of one placeholder ball.

Plan note "09 - Art Direction" ("VFX style") and decision D-060. A projectile's style is
chosen from the character and move that fire it (:func:`style_of`); one without a style falls
back to the old ball, so a new character is never blocked on art. Every style is drawn with
Pillow in Resurrect 64 colours, for the eight screen headings where the shape points
somewhere, with a few animation frames, and in up to three sizes for charged shots.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageChops, ImageDraw

from isofightr.render.iso import project
from isofightr.render.placeholder_art import SHADOW_HEIGHT, SHADOW_WIDTH, player_color
from isofightr.sim.math3d import Vec3

Rgba = tuple[int, int, int, int]


def _rgba(value: str, alpha: int = 255) -> Rgba:
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


TRANSPARENT: Final[Rgba] = (0, 0, 0, 0)
INK: Final[Rgba] = _rgba("2e222f")
WHITE: Final[Rgba] = _rgba("ffffff")
CLOUD: Final[Rgba] = _rgba("c7dcd0")
SKY: Final[Rgba] = _rgba("8fd3ff")
BLUE: Final[Rgba] = _rgba("4d9be6")
STONE_LIGHT: Final[Rgba] = _rgba("9babb2")
STONE: Final[Rgba] = _rgba("7f708a")
STONE_DARK: Final[Rgba] = _rgba("625565")
MOSS: Final[Rgba] = _rgba("1ebc73")
MOSS_DARK: Final[Rgba] = _rgba("239063")
MINT: Final[Rgba] = _rgba("8ff8e2")
TEAL: Final[Rgba] = _rgba("30e1b9")
FLAME_CORE: Final[Rgba] = _rgba("fbff86")
FLAME_MID: Final[Rgba] = _rgba("f9c22b")
FLAME_OUTER: Final[Rgba] = _rgba("f57d4a")
FLAME_EDGE: Final[Rgba] = _rgba("ea4f36")
LAMP_FRAME: Final[Rgba] = _rgba("3e3546")
RUNE: Final[Rgba] = _rgba("a884f3")
RUNE_DARK: Final[Rgba] = _rgba("905ea9")
RUNE_LIGHT: Final[Rgba] = _rgba("eaaded")
HALO_ALPHA: Final[int] = 96
SHADOW_ALPHA: Final[int] = 110
GLYPH_FILL_ALPHA: Final[int] = 80

HEADINGS: Final[int] = 8
"""Screen directions a pointed projectile is drawn for, counter-clockwise from right."""
CHARGE_STEPS: Final[tuple[float, ...]] = (1.15, 1.5)
"""Damage over base damage at which a charged shot is drawn one and two sizes bigger."""
CHARGE_GROWTH: Final[int] = 6
"""Pixels each charge size adds to the art."""


@dataclass(frozen=True, slots=True)
class Style:
    """How one kind of projectile is drawn."""

    name: str
    size: int
    """Width and height of the art at its base size, in pixels (odd, so it centres)."""
    frames: int
    frame_ticks: int
    """Ticks each animation frame is shown."""
    headed: bool = True
    """Whether the art points along its heading (a spinning rock does not)."""
    charged: bool = False
    """Whether a charged shot is drawn bigger."""
    decal: bool = False
    """A flat mark on the ground (drawn in the world's depth order, with no shadow)."""
    height: int = 0
    """Height of a decal's art (its ``size`` is the width)."""


CRESCENT: Final[Style] = Style("crescent", 21, 2, 3, charged=True)
BOULDER: Final[Style] = Style("boulder", 25, 4, 4, headed=False)
DART: Final[Style] = Style("dart", 15, 2, 3)
EMBER: Final[Style] = Style("ember", 19, 3, 3, charged=True)
LAMP: Final[Style] = Style("lamp", 23, 4, 3, headed=False)
GLYPH: Final[Style] = Style("glyph", 39, 4, 8, headed=False, decal=True, height=19)

STYLES: Final[dict[tuple[str, str], Style]] = {
    ("rook", "nspecial"): CRESCENT,
    ("bramble", "nspecial"): BOULDER,
    ("zephyr", "nspecial"): DART,
    ("mote", "nspecial"): EMBER,
    ("mote", "sspecial"): LAMP,
    ("mote", "dspecial"): GLYPH,
}
"""Which style the projectiles of a (character, move) get."""


def style_of(character_id: str, move_id: str) -> Style | None:
    """Return the style for a character's move, or ``None`` (draw the plain ball)."""
    return STYLES.get((character_id, move_id))


def heading_of(velocity: Vec3) -> int:
    """Return the screen heading index (0 to 7, counter-clockwise from right) of a world
    velocity; 0 for something that is not moving."""
    screen_x, screen_y = project(velocity.x, velocity.y, velocity.z)
    if screen_x == 0.0 and screen_y == 0.0:
        return 0
    return round(math.atan2(screen_y, screen_x) / (2.0 * math.pi) * HEADINGS) % HEADINGS


def charge_step(damage: float, base_damage: float) -> int:
    """Return how many sizes bigger a shot is drawn: 0, 1 or 2 by its damage over base."""
    if base_damage <= 0.0:
        return 0
    ratio = damage / base_damage
    return sum(ratio >= step for step in CHARGE_STEPS)


def frame_of(style: Style, age: int) -> int:
    """Return the animation frame of a projectile that has flown for ``age`` ticks."""
    return (age // style.frame_ticks) % style.frames


def _direction(heading: int) -> tuple[float, float]:
    """Unit vector of a heading in image space (y down)."""
    turn = 2.0 * math.pi * (heading % HEADINGS) / HEADINGS
    return (math.cos(turn), -math.sin(turn))


def _disc(size: int, cx: float, cy: float, radius: float) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    return mask


def _paint(image: Image.Image, mask: Image.Image, color: Rgba) -> None:
    image.paste(Image.new("RGBA", image.size, color), (0, 0), mask)


def build_crescent(heading: int, frame: int, step: int, player_index: int) -> Image.Image:
    """A pale crescent slash-wave, convex side forward, with a short fading tail."""
    size = CRESCENT.size + step * CHARGE_GROWTH
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    dx, dy = _direction(heading)
    centre = (size - 1) / 2
    radius = size / 2 - 2
    # A crescent is a disc with a second disc, set back along the heading, cut out of it.
    for inset, back, color in ((0.0, 0.42, BLUE), (1.0, 0.5, SKY), (2.0, 0.62, WHITE)):
        outer = _disc(size, centre, centre, radius - inset)
        cut_x = centre - dx * radius * back
        cut_y = centre - dy * radius * back
        cut = _disc(size, cut_x, cut_y, radius - inset * 0.3)
        _paint(image, ImageChops.subtract(outer, cut), color)
    draw = ImageDraw.Draw(image)
    tail = _rgba("c7dcd0") if frame == 0 else SKY
    across = (-dy, dx)
    for sideways in (-0.45, 0.0, 0.45):
        start = radius * (0.25 + 0.1 * frame)
        x0 = centre + across[0] * radius * sideways - dx * start
        y0 = centre + across[1] * radius * sideways - dy * start
        length = 3 + step
        draw.line(
            (round(x0), round(y0), round(x0 - dx * length), round(y0 - dy * length)), fill=tail
        )
    tip = player_color(player_index)
    for sign in (-1, 1):
        px = centre + across[0] * (radius - 1) * sign - dx * radius * 0.15
        py = centre + across[1] * (radius - 1) * sign - dy * radius * 0.15
        draw.point((round(px), round(py)), fill=tip)
    return image


def build_boulder(frame: int) -> Image.Image:
    """A chunky mossy rock; its facets and moss turn from frame to frame so it spins."""
    size = BOULDER.size
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    centre = (size - 1) / 2
    spin = frame * math.pi / 8
    radii = (1.0, 0.82, 0.96, 0.78, 1.0, 0.86, 0.94, 0.8)

    def ring(scale: float) -> list[tuple[float, float]]:
        points = []
        for index, lump in enumerate(radii):
            angle = spin + index * math.pi / 4
            reach = (size / 2 - 1.5) * lump * scale
            points.append((centre + math.cos(angle) * reach, centre + math.sin(angle) * reach))
        return points

    draw.polygon(ring(1.0), fill=STONE, outline=INK)
    shade = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shade).polygon(ring(0.86), fill=255)
    low = Image.new("L", (size, size), 0)
    ImageDraw.Draw(low).rectangle((0, centre + 2, size, size), fill=255)
    _paint(image, ImageChops.multiply(shade, low), STONE_DARK)
    high = Image.new("L", (size, size), 0)
    ImageDraw.Draw(high).ellipse((centre - 7, centre - 8, centre + 1, centre - 2), fill=255)
    _paint(image, ImageChops.multiply(shade, high), STONE_LIGHT)
    for index, color in ((1, MOSS), (4, MOSS_DARK), (6, MOSS)):
        angle = spin + index * math.pi / 4 + 0.3
        mx = centre + math.cos(angle) * size * 0.24
        my = centre + math.sin(angle) * size * 0.24
        draw.ellipse((mx - 2, my - 1.5, mx + 2, my + 1.5), fill=color)
    return image


def build_dart(heading: int, frame: int, player_index: int) -> Image.Image:
    """A small feathered dart pointing along its heading, with a short wind streak."""
    size = DART.size
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    dx, dy = _direction(heading)
    centre = (size - 1) / 2
    across = (-dy, dx)

    def at(along: float, sideways: float = 0.0) -> tuple[int, int]:
        return (
            round(centre + dx * along + across[0] * sideways),
            round(centre + dy * along + across[1] * sideways),
        )

    streak = CLOUD if frame == 0 else WHITE
    draw.line((*at(-6.0 - frame), *at(-3.0)), fill=streak)
    draw.line((*at(-3.0), *at(4.0)), fill=TEAL, width=2)
    draw.line((*at(1.0), *at(5.0)), fill=MINT)
    draw.point(at(6.0), fill=WHITE)
    feather = player_color(player_index)
    for sideways in (-2.0, 2.0):
        draw.line((*at(-2.0), *at(-4.0, sideways)), fill=feather)
    return image


def build_ember(heading: int, frame: int, step: int) -> Image.Image:
    """A flickering flame orb with a tail of fire trailing behind its heading."""
    size = EMBER.size + step * CHARGE_GROWTH
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    dx, dy = _direction(heading)
    centre = (size - 1) / 2
    radius = size / 2 - 3
    flicker = (0.0, 1.0, -1.0)[frame % 3]
    across = (-dy, dx)
    tail_tip = (
        centre - dx * (radius + 2.5 + flicker),
        centre - dy * (radius + 2.5 + flicker),
    )
    for scale, color in ((1.0, FLAME_EDGE), (0.7, FLAME_OUTER)):
        half = radius * 0.8 * scale
        draw.polygon(
            [
                (centre + across[0] * half, centre + across[1] * half),
                (centre - across[0] * half, centre - across[1] * half),
                tail_tip,
            ],
            fill=color,
        )
    bands = ((1.0, FLAME_EDGE), (0.8, FLAME_OUTER), (0.58, FLAME_MID), (0.3, FLAME_CORE))
    for scale, color in bands:
        reach = radius * scale
        ox = centre + dx * (radius - reach) * 0.5
        oy = centre + dy * (radius - reach) * 0.5
        draw.ellipse((ox - reach, oy - reach, ox + reach, oy + reach), fill=color)
    spark = (
        centre - dx * (radius + 1) + across[0] * (2.0 + flicker),
        centre - dy * (radius + 1) + across[1] * (2.0 + flicker),
    )
    draw.point((round(spark[0]), round(spark[1])), fill=FLAME_MID)
    return image


def build_lamp(frame: int, player_index: int) -> Image.Image:
    """A spinning lantern in a soft halo. Its width changes from frame to frame (the spin)."""
    size = LAMP.size
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    centre = (size - 1) // 2
    halo = 9 + frame % 2
    red, green, blue, _ = FLAME_CORE
    draw.ellipse(
        (centre - halo, centre - halo, centre + halo, centre + halo),
        fill=(red, green, blue, HALO_ALPHA),
    )
    half = (4, 3, 1, 3)[frame % 4]
    top, bottom = centre - 6, centre + 6
    draw.polygon(
        [(centre, top), (centre + half, centre - 2), (centre + half, centre + 3), (centre, bottom),
         (centre - half, centre + 3), (centre - half, centre - 2)],
        fill=FLAME_MID,
        outline=LAMP_FRAME,
    )  # fmt: skip
    if half > 1:
        draw.rectangle(
            (centre - half + 1, centre - 1, centre + half - 1, centre + 1), fill=FLAME_CORE
        )
    draw.line((centre, top - 2, centre, top), fill=LAMP_FRAME)
    draw.point((centre, bottom + 1), fill=player_color(player_index))
    draw.point((centre, top - 3), fill=player_color(player_index))
    return image


def build_glyph(frame: int, player_index: int) -> Image.Image:
    """A ground rune: an iso ellipse of arcane lines that pulses while it waits."""
    width, height = GLYPH.size, GLYPH.height
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    pulse = frame % GLYPH.frames
    ring = (RUNE_DARK, RUNE, RUNE_LIGHT, RUNE)[pulse]
    inner = (RUNE, RUNE_LIGHT, RUNE, RUNE_DARK)[pulse]
    red, green, blue, _ = RUNE_DARK
    draw.ellipse((0, 0, width - 1, height - 1), fill=(red, green, blue, GLYPH_FILL_ALPHA))
    draw.ellipse((0, 0, width - 1, height - 1), outline=ring)
    draw.ellipse((5, 3, width - 6, height - 4), outline=inner)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    points = []
    for index in range(5):
        angle = -math.pi / 2 + index * 4 * math.pi / 5
        points.append(
            (cx + math.cos(angle) * (width / 2 - 8), cy + math.sin(angle) * (height / 2 - 5))
        )
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        draw.line((*start, *end), fill=RUNE_LIGHT if (index + pulse) % 2 == 0 else RUNE)
    owner = player_color(player_index)
    for x, y in ((0, cy), (width - 1, cy), (cx, 0), (cx, height - 1)):
        draw.point((round(x), round(y)), fill=owner)
    return image


def build(style: Style, heading: int, frame: int, step: int, player_index: int) -> Image.Image:
    """Return the art of one projectile frame.

    Args:
        style: which projectile.
        heading: screen heading, 0 to 7 (ignored by styles that do not point).
        frame: animation frame, 0 to ``style.frames`` - 1.
        step: charge size, 0 to 2 (ignored by styles that are not charged).
        player_index: whose colour its accents take.
    """
    if style is CRESCENT:
        return build_crescent(heading, frame, step, player_index)
    if style is BOULDER:
        return build_boulder(frame)
    if style is DART:
        return build_dart(heading, frame, player_index)
    if style is EMBER:
        return build_ember(heading, frame, step)
    if style is LAMP:
        return build_lamp(frame, player_index)
    if style is GLYPH:
        return build_glyph(frame, player_index)
    raise ValueError(f"no art for style {style.name!r}")


SHADOW_SIZES: Final[tuple[tuple[int, int], ...]] = ((10, 5), (8, 4), (6, 3))
"""Blob size of a projectile's ground shadow: near the ground, higher, high up."""
SHADOW_HEIGHTS: Final[tuple[float, ...]] = (1.0, 2.5)
"""Heights above the surface at which the shadow steps down a size."""


def shadow_step(height_above_surface: float) -> int:
    """Return which shadow size applies at a height above the surface."""
    return sum(height_above_surface > limit for limit in SHADOW_HEIGHTS)


def build_shadow(step: int) -> Image.Image:
    """Return a projectile's ground shadow: a small dark blob with no player ring, on the same
    canvas as a fighter's shadow so the same clipping applies."""
    image = Image.new("RGBA", (SHADOW_WIDTH, SHADOW_HEIGHT), TRANSPARENT)
    width, height = SHADOW_SIZES[min(step, len(SHADOW_SIZES) - 1)]
    left = (SHADOW_WIDTH - width) // 2
    top = (SHADOW_HEIGHT - height) // 2
    red, green, blue, _ = INK
    ImageDraw.Draw(image).ellipse(
        (left, top, left + width - 1, top + height - 1), fill=(red, green, blue, SHADOW_ALPHA)
    )
    return image
