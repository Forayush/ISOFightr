"""Art for the character select screen: player panel backdrops, the isle each fighter stands
on, name plates, the READY sash and roster tiles.

Plan note "13 - Game Modes UI and Flow" ("Character select screen", decision D-061). Each
player's panel is painted in that player's colour ramp (:data:`isofightr.ui.theme.PLAYER_RAMPS`):
a dithered glow behind the fighter, speed stripes at the tiles' 2:1 slope, and a little
floating isle with a checkered top, like the game's own islands. A slot nobody has joined is
the same art in greys. Shading is ordered dithering, never blending, so every pixel is a
Resurrect 64 entry (tested).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageDraw

from isofightr.ui import kit_art, theme
from isofightr.ui.theme import Ramp, Rgb

BAYER: Final[tuple[tuple[int, ...], ...]] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
"""The 4x4 ordered-dither matrix: a pixel is lit when its entry is below 16 x density."""
STRIPE_PERIOD: Final[int] = 14
STRIPE_WIDTH: Final[int] = 5
GLOW_DENSITY: Final[float] = 0.5
"""How much of the glow's centre is the dark shade."""
FLOOR_DENSITY: Final[float] = 0.6
"""How much of the panel's foot is the deep shade."""
ISLE_DEPTH: Final[int] = 6
"""Height of an isle's side faces."""
ISLE_ROOT: Final[int] = 12
"""How far the rock under an isle hangs below its side faces."""
ISLE_CHECKS: Final[int] = 3
"""An isle's top is checkered this many tiles to a side."""


def lit(x: int, y: int, density: float) -> bool:
    """Return whether the ordered dither lights pixel ``(x, y)`` at ``density`` (0 to 1)."""
    return BAYER[y % 4][x % 4] < density * 16


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def panel_backdrop(
    width: int, height: int, ramp: Ramp, border: Rgb | None = None, glow: bool = True
) -> Image.Image:
    """Return a player panel's body: the panel fill, the deep shade rising from the foot,
    stripes across the top half fading downward, a glow where the fighter stands (unless
    ``glow`` is off), and a border in the player's colour (or ``border``)."""
    light, base, dark, deep = ramp
    mask = kit_art.shape_mask(width, height, theme.CORNER)
    image = kit_art.filled(mask, theme.PANEL_FILL)
    pixels = image.load()
    assert pixels is not None
    centre_x, centre_y = width / 2, height * 0.42
    radius_x, radius_y = width * 0.46, height * 0.34
    for y in range(height):
        from_top = y / max(height - 1, 1)
        floor = _clamp((from_top - 0.45) / 0.55) * FLOOR_DENSITY
        stripes = _clamp(1.0 - from_top / 0.6) * 0.9
        for x in range(width):
            if not mask.getpixel((x, y)):
                continue
            reach = ((x - centre_x) / radius_x) ** 2 + ((y - centre_y) / radius_y) ** 2
            shine = _clamp(1.0 - reach) * GLOW_DENSITY if glow else 0.0
            stripe = (x + 2 * y) % STRIPE_PERIOD < STRIPE_WIDTH
            color: Rgb | None = None
            if lit(x, y, floor):
                color = deep
            if stripe and lit(x, y, stripes):
                color = deep
            if lit(x, y, shine):
                color = dark
            if color is not None:
                pixels[x, y] = (*color, theme.PANEL_ALPHA)
    edge = kit_art.panel(width, height, (0, 0, 0, 0), border or base, theme.CORNER, light=light)
    image.alpha_composite(edge)
    return image


def isle(width: int, ramp: Ramp) -> Image.Image:
    """Return the floating isle a fighter stands on: a 2:1 diamond top checkered in two
    shades, lit along its back edges, dark side faces, and rock hanging underneath. The
    image is ``width`` wide; the centre of the top face is ``width // 4`` pixels below its
    top edge."""
    light, base, dark, deep = ramp
    top_height = width // 2
    height = top_height + ISLE_DEPTH + ISLE_ROOT
    image = Image.new("RGBA", (width, height), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    half_w, half_h = (width - 1) / 2, (top_height - 1) / 2
    # Rock hanging from the side faces' lower edges down to a point.
    bottom_vertex = top_height - 1 + ISLE_DEPTH
    tip = height - 1
    for x in range(round(half_w * 0.3), round(half_w * 1.7) + 1):
        edge = bottom_vertex - abs(x - half_w) / 2
        reach = 1.0 - abs(x - half_w) / (half_w * 0.7)
        low = edge + (tip - edge) * reach
        for y in range(int(edge), int(low) + 1):
            draw.point((x, y), fill=theme.INK if x > half_w else deep)
    # Side faces: left in the deep shade, right in ink.
    for offset in range(ISLE_DEPTH):
        draw.line((0, half_h + offset, half_w, top_height - 1 + offset), fill=deep)
        draw.line((half_w, top_height - 1 + offset, width - 1, half_h + offset), fill=theme.INK)
    # The top face, checkered along the isometric axes.
    for y in range(top_height):
        for x in range(width):
            u = (x - half_w) / half_w + (y - half_h) / half_h
            v = -(x - half_w) / half_w + (y - half_h) / half_h
            if abs(x - half_w) / half_w + abs(y - half_h) / half_h > 1.0:
                continue
            cell_u = int((u + 1) / 2 * ISLE_CHECKS) if u < 1 else ISLE_CHECKS - 1
            cell_v = int((v + 1) / 2 * ISLE_CHECKS) if v < 1 else ISLE_CHECKS - 1
            draw.point((x, y), fill=base if (cell_u + cell_v) % 2 == 0 else dark)
    # Light along the two back edges, so the top reads against the panel.
    draw.line((0, half_h, half_w, 0), fill=light)
    draw.line((half_w, 0, width - 1, half_h), fill=light)
    return image


def name_plate(width: int, height: int, accent: Rgb) -> Image.Image:
    """Return the plate a fighter's name sits on: an ink bar leaning at the tiles' slope,
    edged in the player's colour, with a solid block of it at the left end."""
    mask = kit_art.slant_mask(width, height)
    image = kit_art.filled(mask, theme.INK, accent)
    block = Image.new("L", mask.size, 0)
    block.paste(mask.crop((0, 0, height, height)), (0, 0))
    image.paste((*accent, 255), (0, 0), block)
    return image


def strip(width: int, height: int, color: Rgb, dark: Rgb) -> Image.Image:
    """Return a panel's top strip: the player's colour with three leaning stripes in a
    darker shade near its right end."""
    mask = kit_art.shape_mask(width, height, theme.CORNER - 1, (True, False, False, False))
    image = kit_art.filled(mask, color)
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width - 34, width):
            if mask.getpixel((x, y)) and (x + 2 * y) % 8 < 3:
                pixels[x, y] = (*dark, 255)
    return image


def sash(width: int, height: int) -> Image.Image:
    """Return the READY sash laid across a panel: a gold band with leaning ends, an ink
    outline and a pale line along its top."""
    mask = kit_art.slant_mask(width, height)
    image = kit_art.filled(mask, theme.GOLD, theme.INK)
    pixels = image.load()
    assert pixels is not None
    for x in range(width):
        if mask.getpixel((x, 1)) and mask.getpixel((x, 0)):
            pixels[x, 1] = (*theme.PALE_GOLD, 255)
        if mask.getpixel((x, height - 2)) and mask.getpixel((x, height - 1)):
            pixels[x, height - 2] = (*theme.AMBER, 255)
    return image


def roster_tile(width: int, height: int, ramp: Ramp | None) -> Image.Image:
    """Return a roster tile's backing: navy with leaning stripes, or, under a player's
    cursor, that player's ramp."""
    fill, stripe, border = (theme.NIGHT, theme.NAVY, theme.STEEL)
    if ramp is not None:
        fill, stripe, border = ramp[3], ramp[2], ramp[1]
    mask = kit_art.shape_mask(width, height, theme.SMALL_CORNER)
    image = kit_art.filled(mask, fill, border)
    pixels = image.load()
    assert pixels is not None
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            inside = mask.getpixel((x, y)) and pixels[x, y][:3] == fill
            if inside and (x + 2 * y) % 10 < 3 and lit(x, y, 1.0 - y / height * 0.7):
                pixels[x, y] = (*stripe, 255)
    return image


def accent_bar(width: int, height: int, ramp: Ramp) -> Image.Image:
    """Return a short bar in a player's colour, lit on top: the mark beside the detail
    strip's name that says whose cursor it follows."""
    image = Image.new("RGBA", (width, height), (*ramp[1], 255))
    draw = ImageDraw.Draw(image)
    draw.line((0, 0, width - 1, 0), fill=ramp[0])
    draw.line((0, height - 1, width - 1, height - 1), fill=ramp[2])
    return image
