"""Art for the battle HUD: player cards, badges, the clock plate, KO feed rows, the KO sash,
off-screen bubbles and the big banners.

Plan note "13 - Game Modes UI and Flow" ("Battle HUD", decision D-061 item 9). Like the rest
of the UI kit everything is drawn with Pillow from :mod:`isofightr.ui.theme` colours (every
pixel a Resurrect 64 entry, tested), with the tiles' angled 2:1 corners, and painted in the
player's colour ramp (:func:`isofightr.ui.theme.player_ramp`). The banners (3, 2, 1, GO!,
GAME!, SUDDEN DEATH) are the logo's extruded lettering (:func:`isofightr.ui.logo.build_logo`).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from typing import Final

from PIL import Image, ImageChops, ImageDraw

from isofightr.ui import kit_art, logo, select_art, theme
from isofightr.ui.theme import Ramp, Rgb

CARD_ALPHA: Final[int] = 235
PLATE_LIP: Final[int] = 2
"""The lip of the HUD's small plates (clock, feed rows, combo)."""
CARD_LIP: Final[int] = 3
"""The card's front lip, in the player's dark shade (decision D-072)."""
BAND_LEFT: Final[int] = 38
"""Where the name band starts: just right of the bust's well (card-relative)."""
BAND_ROWS: Final[int] = 12
"""Rows of the name band, under the outline and the lit line; one more row is its edge."""
WELL_WIDTH: Final[int] = 58
WELL_RIGHT: Final[int] = 3
"""The damage number's well: this wide, this far from the card's right edge."""
BANNER_SCALE: Final[int] = 3
"""The countdown and GO! / GAME! letters are the display font this many times over."""
WIDE_BANNER_SCALE: Final[int] = 2
"""A long banner (SUDDEN DEATH, REPLAY END) is drawn smaller so it fits."""
WIDE_BANNER_LETTERS: Final[int] = 6
BANNER_COLORS: Final[dict[str, tuple[Rgb, Rgb, Rgb, Rgb]]] = {
    "gold": logo.GOLD_LETTERS,
    "red": (theme.RED, theme.SALMON, theme.CRIMSON, theme.MAROON),
    "mint": (theme.MINT, theme.WHITE, theme.AQUA, theme.DEEP_TEAL),
}
"""Banner palettes: face, lit rim, near depth, far depth."""


def card(
    width: int, height: int, ramp: Ramp, lit: bool = False, accent: Ramp | None = None
) -> Image.Image:
    """Return a player card's body (decision D-072): an ink block like the menus' blocks,
    its front lip in the player's dark shade, a band of the player's light shade across the
    top right where the name is written in ink, and a sunk well where the damage number
    sits. ``lit`` (the moment after a hit) turns the outline white; ``accent`` (the
    attacker's colours, the moment after a heavy launch: decision D-068) paints the band and
    the outline in them."""
    light, base, dark, _deep = ramp
    band, band_edge, outline = light, base, theme.WHITE if lit else theme.INK
    if accent is not None:
        band, band_edge, outline = accent[0], accent[1], accent[1]
    face = (*theme.NIGHT, CARD_ALPHA)
    image = kit_art.block(width, height, (face, theme.NAVY, dark, outline), CARD_LIP, theme.CORNER)
    rim = _pixels_of(image, outline)
    face_area = Image.new("L", (width, height), 0)
    face_area.paste(kit_art.shape_mask(width, height - CARD_LIP, theme.CORNER), (0, 0))
    top = 2  # under the outline and the lit line
    for colour, first, last in ((band, top, top + BAND_ROWS - 1), (band_edge, top + BAND_ROWS,
                                                                   top + BAND_ROWS)):  # fmt: skip
        rows = Image.new("L", (width, height), 0)
        rows.paste(255, (BAND_LEFT, first, width, last + 1))
        image.paste((*colour, 255), (0, 0), ImageChops.multiply(rows, face_area))
    image.paste((*outline, 255), (0, 0), rim)
    left = width - WELL_WIDTH - WELL_RIGHT
    well_top = top + BAND_ROWS + 2
    well = kit_art.filled(
        kit_art.shape_mask(WELL_WIDTH, height - CARD_LIP - 2 - well_top, 1), theme.INK, theme.NIGHT
    )
    image.alpha_composite(well, (left, well_top))
    return image


def _pixels_of(image: Image.Image, colour: Rgb) -> Image.Image:
    """Return a mask of the opaque pixels of ``image`` that are exactly ``colour``."""
    mask = Image.new("L", image.size, 0)
    source, target = image.load(), mask.load()
    assert source is not None and target is not None
    for y in range(image.height):
        for x in range(image.width):
            pixel = source[x, y]
            if pixel[3] and pixel[:3] == colour:
                target[x, y] = 255
    return mask


def bust_mask(size: int, inset: int = 0) -> Image.Image:
    """Return the shape of a bust's well, ``inset`` pixels in: a square with the angled
    corners every panel has (decision D-070), so the portrait is cut like the card it is on."""
    inner = size - 2 * inset
    mask = Image.new("L", (size, size), 0)
    mask.paste(kit_art.shape_mask(inner, inner, max(theme.CORNER - inset, 1)), (inset, inset))
    return mask


def bust_well(size: int, ramp: Ramp) -> Image.Image:
    """Return the dark well a bust sits in, ringed in the player's light shade, with the
    panels' angled corners."""
    return kit_art.filled(bust_mask(size), theme.INK, ramp[0])


def clip_bust(image: Image.Image, size: int) -> Image.Image:
    """Return a bust centred on a ``size`` square and cut to the inside of its well, so
    nothing of it shows past the well's angled corners."""
    canvas = Image.new("RGBA", (size, size), kit_art.TRANSPARENT)
    source = image.convert("RGBA")
    canvas.alpha_composite(
        source.crop((0, 0, min(source.width, size), min(source.height, size))),
        (max((size - source.width) // 2, 0), max((size - source.height) // 2, 0)),
    )
    blank = Image.new("RGBA", (size, size), kit_art.TRANSPARENT)
    return Image.composite(canvas, blank, bust_mask(size, 1))


STOCK_PIP: Final[tuple[int, int]] = (8, 7)
"""A stock pip: one small isometric tile."""


def stock_pip(ramp: Ramp, lost: bool = False) -> Image.Image:
    """Return a stock pip (decision D-070): a tiny isometric tile in the player's colours,
    lit on top, so stocks are counted at a glance; a ``lost`` one is the same shape in the
    player's deepest shade, an empty socket."""
    light, base, dark, deep = ramp
    width, height = STOCK_PIP
    image = Image.new("RGBA", (width, height), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    half, last = width // 2, width - 1
    top = [(0, 2), (half - 1, 0), (half, 0), (last, 2), (half, 4), (half - 1, 4)]
    left = [(0, 2), (half - 1, 4), (half - 1, height - 1), (0, height - 3)]
    right = [(last, 2), (half, 4), (half, height - 1), (last, height - 3)]
    if lost:
        for shape in (left, right, top):
            draw.polygon(shape, fill=deep)
        return image
    draw.polygon(left, fill=base)
    draw.polygon(right, fill=dark)
    draw.polygon(top, fill=light)
    return image


def badge(width: int, height: int, color: Rgb) -> Image.Image:
    """Return a small solid badge (CPU level, team) in a colour with an ink rim."""
    return kit_art.filled(
        kit_art.shape_mask(width, height, 1, kit_art.ALL_CORNERS), color, theme.INK
    )


def clock_plate(width: int, height: int, alarm: bool = False, glow: bool = False) -> Image.Image:
    """Return the plate behind the clock: an ink block (decision D-072), lit and lipped in
    red in the last 30 seconds (and red-faced on the pulse's bright half)."""
    fill = theme.CRIMSON if alarm and glow else theme.NIGHT
    light = theme.RED if alarm else theme.NAVY
    lip = theme.MAROON if alarm else theme.INK
    return kit_art.block(width, height, ((*fill, CARD_ALPHA), light, lip, theme.INK), PLATE_LIP)


def feed_row(width: int, height: int, color: Rgb) -> Image.Image:
    """Return one KO feed row: a low ink block with the KO'd player's colour on its left
    end (decision D-072)."""
    image = kit_art.block(
        width, height, ((*theme.NIGHT, CARD_ALPHA), theme.NAVY, theme.INK, theme.INK), PLATE_LIP
    )
    end = Image.new("L", image.size, 0)
    end.paste(kit_art.shape_mask(width, height - PLATE_LIP, theme.SMALL_CORNER).crop(
        (1, 1, 4, height - PLATE_LIP - 1)), (1, 1))  # fmt: skip
    image.paste((*color, 255), (0, 0), end)
    return image


def sash(width: int, height: int, ramp: Ramp) -> Image.Image:
    """Return the KO sash: a band in the KO'd player's colour with leaning ends, leaning
    stripes in its dark shade near both ends, an ink outline and a lit top line."""
    light, base, dark, _ = ramp
    mask = kit_art.slant_mask(width, height)
    image = kit_art.filled(mask, base, theme.INK)
    pixels = image.load()
    assert pixels is not None
    for y in range(1, height - 1):
        for x in range(width):
            inside = mask.getpixel((x, y)) and pixels[x, y][:3] == base
            near_end = x < 40 or x > width - 40
            if inside and near_end and (x + 2 * y) % 8 < 3:
                pixels[x, y] = (*dark, 255)
    for x in range(width):
        if mask.getpixel((x, 1)) and mask.getpixel((x, 0)):
            pixels[x, 1] = (*light, 255)
    return image


def combo_plate(width: int, height: int) -> Image.Image:
    """Return the plate the combo counter sits on: an ink block lit and lipped in gold."""
    return kit_art.block(
        width, height, ((*theme.NIGHT, CARD_ALPHA), theme.GOLD, theme.AMBER, theme.INK), PLATE_LIP
    )


def bubble(size: int, ramp: Ramp) -> Image.Image:
    """Return an off-screen bubble: an ink disc ringed in the player's colour, lit on its
    upper left."""
    image = Image.new("RGBA", (size, size), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, size - 1, size - 1), fill=theme.INK)
    draw.ellipse((1, 1, size - 2, size - 2), fill=ramp[1])
    draw.ellipse((3, 3, size - 4, size - 4), fill=theme.INK)
    draw.arc((1, 1, size - 2, size - 2), 190, 260, fill=ramp[0])
    return image


ARROW_SIZE: Final[int] = 9


def bubble_arrow(direction: int, ramp: Ramp) -> Image.Image:
    """Return the small arrow beside a bubble, pointing one of eight ways (0 = right, then
    anticlockwise in 45 degree steps; screen y up)."""
    size = ARROW_SIZE
    image = Image.new("RGBA", (size, size), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    middle = (size - 1) / 2
    angle = direction % 8 * math.pi / 4

    def point(along: float, across: float) -> tuple[float, float]:
        x = middle + along * math.cos(angle) - across * math.sin(angle)
        y = middle - (along * math.sin(angle) + across * math.cos(angle))
        return (x, y)

    outer = [point(4, 0), point(-3, 4), point(-3, -4)]
    inner = [point(2.5, 0), point(-2, 2.5), point(-2, -2.5)]
    draw.polygon(outer, fill=theme.INK)
    draw.polygon(inner, fill=ramp[1])
    return image


def banner(text: str, colors: str = "gold") -> Image.Image:
    """Return a big banner in the logo's lettering: the countdown, GO!, GAME!, SUDDEN DEATH.
    Long words are drawn smaller so they fit the screen."""
    scale = WIDE_BANNER_SCALE if len(text) > WIDE_BANNER_LETTERS else BANNER_SCALE
    return logo.build_logo(text, scale, BANNER_COLORS[colors])


def shards(image: Image.Image) -> list[tuple[Image.Image, tuple[int, int]]]:
    """Return a stock icon broken in four: each quarter and its offset from the icon's
    top-left corner, for the shatter when a stock is lost."""
    half_w, half_h = image.width // 2, image.height // 2
    pieces = []
    for left, top in ((0, 0), (half_w, 0), (0, half_h), (half_w, half_h)):
        piece = image.crop((left, top, left + max(half_w, 1), top + max(half_h, 1)))
        pieces.append((piece, (left, top)))
    return pieces


def dither_fade(image: Image.Image, density: float) -> Image.Image:
    """Return an image with only ``density`` of its pixels kept, in the ordered dither's
    pattern: a pixel-art fade with no new colours."""
    result = image.copy()
    pixels = result.load()
    assert pixels is not None
    for y in range(result.height):
        for x in range(result.width):
            if not select_art.lit(x, y, density):
                pixels[x, y] = kit_art.TRANSPARENT
    return result
