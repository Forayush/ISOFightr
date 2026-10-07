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

from PIL import Image, ImageDraw

from isofightr.ui import kit_art, logo, select_art, theme
from isofightr.ui.theme import Ramp, Rgb

CARD_ALPHA: Final[int] = 235
WEDGE_WIDTH: Final[int] = 36
"""The coloured wedge behind a card's bust, leaning at the tiles' slope on its right."""
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


def card(width: int, height: int, ramp: Ramp, lit: bool = False) -> Image.Image:
    """Return a player card's body: deep ink, a wedge of the player's dark shade behind the
    bust with leaning stripes, and a border in the player's colour (white when ``lit``, for
    the moment after a hit)."""
    light, base, dark, deep = ramp
    mask = kit_art.shape_mask(width, height, theme.CORNER)
    image = kit_art.filled(mask, (*theme.INK, CARD_ALPHA))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        reach = WEDGE_WIDTH + (height - 1 - y) // 8
        for x in range(min(reach, width)):
            if not mask.getpixel((x, y)):
                continue
            stripe = (x + 2 * y) % 8 < 2
            pixels[x, y] = (*(deep if stripe else dark), 255)
    edge = kit_art.panel(
        width, height, (0, 0, 0, 0), theme.WHITE if lit else base, theme.CORNER, light=light
    )
    image.alpha_composite(edge)
    return image


def bust_well(size: int, ramp: Ramp) -> Image.Image:
    """Return the dark square a bust sits in, ringed in the player's light shade."""
    image = Image.new("RGBA", (size, size), (*theme.INK, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size - 1, size - 1), outline=ramp[0])
    return image


def badge(width: int, height: int, color: Rgb) -> Image.Image:
    """Return a small solid badge (CPU level, team) in a colour with an ink rim."""
    return kit_art.filled(
        kit_art.shape_mask(width, height, 1, kit_art.ALL_CORNERS), color, theme.INK
    )


def clock_plate(width: int, height: int, alarm: bool = False, glow: bool = False) -> Image.Image:
    """Return the plate behind the clock: steel-rimmed, red-rimmed in the last 30 seconds
    (and red-filled on the pulse's bright half)."""
    border = theme.RED if alarm else theme.STEEL
    fill = theme.CRIMSON if alarm and glow else theme.INK
    return kit_art.panel(width, height, (*fill, CARD_ALPHA), border, theme.SMALL_CORNER)


def feed_row(width: int, height: int, color: Rgb) -> Image.Image:
    """Return one KO feed row: an ink strip with a block of the KO'd player's colour at its
    left end."""
    mask = kit_art.shape_mask(width, height, theme.SMALL_CORNER)
    image = kit_art.filled(mask, (*theme.INK, CARD_ALPHA))
    block = Image.new("L", mask.size, 0)
    block.paste(mask.crop((0, 0, 4, height)), (0, 0))
    image.paste((*color, 255), (0, 0), block)
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
    """Return the plate the combo counter sits on: ink, rimmed in gold."""
    return kit_art.filled(
        kit_art.shape_mask(width, height, theme.SMALL_CORNER), (*theme.INK, CARD_ALPHA), theme.GOLD
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
