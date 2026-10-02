"""A tiny fixed-width pixel font for debug text, drawn at native resolution.

Plan note "13 - Game Modes UI and Flow" asks for a bitmap font rendered at native resolution
(window-resolution text would break the pixel scale). The real font and widget kit arrive in
M6; until then debug overlays use Pillow's built-in 6x11 bitmap font, drawn into glyph
images at runtime (no font file is shipped).

This module is pure Pillow. :mod:`isofightr.ui.pixel_text` turns glyphs into sprites.
"""

from typing import Final

from PIL import Image, ImageDraw, ImageFont

GLYPH_ADVANCE: Final[int] = 6
"""Horizontal distance from one character to the next, in pixels."""
GLYPH_WIDTH: Final[int] = 8
GLYPH_HEIGHT: Final[int] = 12
"""Glyph image size: the 6x11 character plus room for a 1 px drop shadow. Both are even so
a sprite centred on whole pixels stays pixel-aligned."""
PRINTABLE: Final[str] = "".join(chr(code) for code in range(33, 127))

_SHADOW: Final[tuple[int, int, int, int]] = (16, 16, 28, 255)
_INK: Final[tuple[int, int, int, int]] = (255, 255, 255, 255)


def build_glyph(character: str) -> Image.Image:
    """Return a white character with a dark 1 px drop shadow on a transparent background.

    White lets the sprite color tint it. The shadow keeps text readable over any tile.
    """
    font = ImageFont.load_default_imagefont()
    image = Image.new("RGBA", (GLYPH_WIDTH, GLYPH_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((1, 1), character, fill=_SHADOW, font=font)
    draw.text((0, 0), character, fill=_INK, font=font)
    return image


def text_width(text: str) -> int:
    """Return the width in pixels of a single line of text."""
    return len(text) * GLYPH_ADVANCE
