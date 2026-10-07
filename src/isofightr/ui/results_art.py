"""Art for the victory screen: podium steps, the spotlight cone, confetti and the wavy banner's
letters.

Plan note "13 - Game Modes UI and Flow" ("Results screen", decision D-061 item 10). Drawn
with Pillow from :mod:`isofightr.ui.theme` colours (every pixel a Resurrect 64 entry,
tested), shaded by ordered dithering, in the player's colour ramp. A podium step is a
column seen like the game's tiles: a 2:1 diamond top checkered in the player's colour over
two side faces. The banner's letters are the logo's extruded lettering, one picture each so
they can wave.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageDraw

from isofightr.ui import kit_art, logo, select_art, theme
from isofightr.ui.theme import Ramp, Rgb

STEP_CHECKS: Final[int] = 2
BANNER_LETTER_SCALE: Final[int] = 2
SPACE_WIDTH: Final[int] = 16
LETTER_GAP: Final[int] = 5
"""Pixels between the banner's letters: room for each letter's depth."""
"""Width of the gap a space leaves in the banner."""
CONE_DENSITY: Final[float] = 0.125
CORE_DENSITY: Final[float] = 0.125


def podium_step(width: int, height: int, ramp: Ramp) -> Image.Image:
    """Return a podium step ``height`` tall: a diamond top ``width`` wide (half as tall),
    checkered in the player's base and dark shades and lit along its back edges, over a left
    face in the deep shade and a right face in ink, each with a lighter band under the top.
    The middle of the top face is ``width // 4`` pixels below the image's top."""
    light, base, dark, deep = ramp
    top_height = width // 2
    image = Image.new("RGBA", (width, top_height + height), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    half_w, half_h = (width - 1) / 2, (top_height - 1) / 2
    for offset in range(height):
        left = dark if offset < 3 else deep
        right = theme.SLATE if offset < 3 else theme.INK
        draw.line((0, half_h + offset, half_w, top_height - 1 + offset), fill=left)
        draw.line((half_w, top_height - 1 + offset, width - 1, half_h + offset), fill=right)
    for y in range(top_height):
        for x in range(width):
            if abs(x - half_w) / half_w + abs(y - half_h) / half_h > 1.0:
                continue
            u = (x - half_w) / half_w + (y - half_h) / half_h
            v = -(x - half_w) / half_w + (y - half_h) / half_h
            cell_u = min(int((u + 1) / 2 * STEP_CHECKS), STEP_CHECKS - 1)
            cell_v = min(int((v + 1) / 2 * STEP_CHECKS), STEP_CHECKS - 1)
            draw.point((x, y), fill=base if (cell_u + cell_v) % 2 == 0 else dark)
    draw.line((0, half_h, half_w, 0), fill=light)
    draw.line((half_w, 0, width - 1, half_h), fill=light)
    return image


def spotlight(width: int, height: int, color: Rgb = theme.PALE_GOLD) -> Image.Image:
    """Return the spotlight cone: a triangle from a point at the top to the full width at
    the bottom, dithered so the backdrop shows through, with a denser core."""
    image = Image.new("RGBA", (width, height), kit_art.TRANSPARENT)
    pixels = image.load()
    assert pixels is not None
    middle = (width - 1) / 2
    for y in range(height):
        reach = middle * (y + 1) / height
        for x in range(width):
            off = abs(x - middle)
            if off > reach:
                continue
            core = off <= reach * 0.45
            density = CONE_DENSITY + (CORE_DENSITY if core else 0.0)
            if select_art.lit(x, y, density):
                pixels[x, y] = (*color, 255)
    return image


def confetti_piece(color: Rgb, wide: bool) -> Image.Image:
    """Return one piece of confetti: 4x3 on its wide side, 2x4 edge on."""
    size = (4, 3) if wide else (2, 4)
    return Image.new("RGBA", size, (*color, 255))


def confetti_colours(ramp: Ramp) -> tuple[Rgb, Rgb, Rgb, Rgb]:
    """Return the colours confetti comes in for a winner: light, base, dark and white."""
    return (ramp[0], ramp[1], ramp[2], theme.WHITE)


def banner_letters(text: str, ramp: Ramp) -> list[tuple[Image.Image | None, int]]:
    """Return the banner one letter at a time, in the logo's lettering and the winner's
    colours: each letter's picture (``None`` for a space) and how far the next one starts
    after it."""
    light, base, dark, deep = ramp
    letters: list[tuple[Image.Image | None, int]] = []
    for character in text:
        if character == " ":
            letters.append((None, SPACE_WIDTH))
            continue
        picture = logo.build_logo(character, BANNER_LETTER_SCALE, (base, light, dark, deep))
        advance = logo.letter_mask(character, BANNER_LETTER_SCALE).width + LETTER_GAP
        letters.append((picture, advance))
    return letters


def banner_width(letters: list[tuple[Image.Image | None, int]]) -> int:
    """Return the width of a banner laid out from its letters."""
    return sum(advance for _, advance in letters)


def place_plate(width: int, height: int, ramp: Ramp) -> Image.Image:
    """Return the small plate a placement ("1ST") is written on, in the player's colour."""
    return kit_art.filled(
        kit_art.shape_mask(width, height, 1, kit_art.ALL_CORNERS), ramp[1], theme.INK
    )
