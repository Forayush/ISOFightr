"""Art for the character select screen: the plate under each fighter's spot at the ring,
the join bubble, name plates, the READY stamp, roster tiles and spawn markers.

Plan note "13 - Game Modes UI and Flow" ("Character select screen", decisions D-061 and
D-072). A player's art is painted in that player's colour ramp
(:data:`isofightr.ui.theme.PLAYER_RAMPS`); a slot nobody has joined is the same in greys.
Shading is ordered dithering, never blending, so every pixel is a Resurrect 64 entry
(tested). (The panel backdrops and the little isles of D-061 went with D-072: the fighters
stand on the Isle itself now.)

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


def lit(x: int, y: int, density: float) -> bool:
    """Return whether the ordered dither lights pixel ``(x, y)`` at ``density`` (0 to 1)."""
    return BAYER[y % 4][x % 4] < density * 16


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def name_plate(width: int, height: int, accent: Rgb) -> Image.Image:
    """Return the plate a fighter's name sits on: an ink bar leaning at the tiles' slope,
    edged in the player's colour, with a solid block of it at the left end."""
    mask = kit_art.slant_mask(width, height)
    image = kit_art.filled(mask, theme.INK, accent)
    block = Image.new("L", mask.size, 0)
    block.paste(mask.crop((0, 0, height, height)), (0, 0))
    image.paste((*accent, 255), (0, 0), block)
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


PLATE_TAG: Final[int] = 13
"""Height of the tag bar along the top of a podium plate."""


def podium_plate(
    width: int, height: int, ramp: Ramp, ready: bool = False, taken: bool = True
) -> Image.Image:
    """Return the plate under a fighter's spot at the ring (decision D-072): a stone block
    with a tag bar in the player's colours along its top, three leaning stripes at the bar's
    right end; its outline gold once the player is ready. An open slot is the same in
    greys."""
    light, base, dark, deep = ramp
    outline = theme.GOLD if ready else theme.INK
    face = theme.STONE.face if taken else theme.FOG
    image = kit_art.block(width, height, (face, theme.WHITE, dark, outline), theme.LIP)
    pixels = image.load()
    assert pixels is not None
    for y in range(1, PLATE_TAG + 1):
        for x in range(1, width - 1):
            if pixels[x, y][3] == 0 or pixels[x, y][:3] == outline:
                continue
            stripe = x > width - 30 and (x + 2 * y) % 8 < 3
            colour = light if y == 1 else dark if stripe else base
            pixels[x, y] = (*colour, 255)
    for x in range(1, width - 1):
        if pixels[x, PLATE_TAG + 1][3] and pixels[x, PLATE_TAG + 1][:3] != outline:
            pixels[x, PLATE_TAG + 1] = (*deep, 255)
    return image


def bubble(width: int, height: int) -> Image.Image:
    """Return the speech bubble over an empty spot at the ring that says how to join: a
    white slab with a stub pointing down at the spot."""
    stub = 5
    image = Image.new("RGBA", (width, height), kit_art.TRANSPARENT)
    body = kit_art.block(width, height - stub, (theme.WHITE, theme.WHITE, theme.MIST, theme.INK), 2)
    image.alpha_composite(body)
    draw = ImageDraw.Draw(image)
    middle = width // 2
    top = height - stub - 2
    draw.polygon(
        [(middle - stub, top), (middle + stub, top), (middle, height - 1)],
        fill=theme.MIST,
        outline=theme.INK,
    )
    draw.line((middle - stub + 1, top, middle + stub - 1, top), fill=theme.MIST)
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


def spawn_marker(width: int, ramp: Ramp) -> Image.Image:
    """Return the marker on a spawn point in the stage preview: a 2:1 diamond ring in the
    player's colour with a lit back edge and an ink rim, flat on the ground."""
    height = width // 2
    image = Image.new("RGBA", (width, height), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    half_w, half_h = (width - 1) / 2, (height - 1) / 2

    def diamond(inset: float) -> list[tuple[float, float]]:
        return [
            (half_w, inset / 2),
            (width - 1 - inset, half_h),
            (half_w, height - 1 - inset / 2),
            (inset, half_h),
        ]

    draw.polygon(diamond(0), fill=theme.INK)
    draw.polygon(diamond(2), fill=ramp[1])
    draw.polygon(diamond(6), fill=ramp[3])
    draw.line((2, half_h, half_w, 1), fill=ramp[0])
    draw.line((half_w, 1, width - 3, half_h), fill=ramp[0])
    return image
