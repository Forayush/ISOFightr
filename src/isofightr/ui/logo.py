"""The game's logo: its name in extruded isometric lettering.

Plan note "09 - Art Direction" ("UI theme", decision D-061): original art, drawn with Pillow
from the display font. Each letter is a slab seen from above and to the left: a gold face,
lit along its top edge, with its depth running down and to the right at the tiles' 2:1
slope, in two darker bands, all inside an ink outline. Every colour is a Resurrect 64 entry.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageChops, ImageFilter

from isofightr.config import WINDOW_TITLE
from isofightr.ui import font, theme
from isofightr.ui.font import TextSize
from isofightr.ui.theme import Rgb

LOGO_TEXT: Final[str] = WINDOW_TITLE.upper()
LETTER_SCALE: Final[int] = 3
"""The display font is enlarged by this whole number for the logo's letters."""
LETTER_GAP: Final[int] = 2
"""Extra pixels between letters (before enlarging), so their sides do not run together."""
DEPTH: Final[int] = 6
"""How many 2:1 steps deep the letters are: 12 pixels across, 6 down."""
OUTLINE: Final[int] = 1
FACE: Final[Rgb] = theme.GOLD
FACE_LIGHT: Final[Rgb] = theme.PALE_GOLD
SIDE: Final[Rgb] = theme.AMBER
SIDE_DEEP: Final[Rgb] = theme.CRIMSON
EDGE: Final[Rgb] = theme.INK
LIGHT_ROWS: Final[int] = 2
"""Rows of lighter gold along the top of each letter's face, after enlarging."""


def letter_mask(text: str = LOGO_TEXT, scale: int = LETTER_SCALE) -> Image.Image:
    """Return the logo's letters as a flat mask, enlarged ``scale`` times, with wider
    letter spacing."""
    letters = [font.mask(character, TextSize.DISPLAY) for character in text]
    width = sum(letter.width for letter in letters) + LETTER_GAP * (len(letters) - 1)
    face = font.face(TextSize.DISPLAY)
    row = Image.new("L", (max(width, 1), face.cap_height), 0)
    x = 0
    for letter in letters:
        row.paste(letter.crop((0, face.cap_top, letter.width, face.baseline)), (x, 0))
        x += letter.width + LETTER_GAP
    return row.resize((row.width * scale, row.height * scale), Image.Resampling.NEAREST)


GOLD_LETTERS: Final[tuple[Rgb, Rgb, Rgb, Rgb]] = (FACE, FACE_LIGHT, SIDE, SIDE_DEEP)
"""Face, its lit rim, the near depth and the far depth: the logo's colours."""


def build_logo(
    text: str = LOGO_TEXT,
    scale: int = LETTER_SCALE,
    colors: tuple[Rgb, Rgb, Rgb, Rgb] = GOLD_LETTERS,
) -> Image.Image:
    """Return the logo (or any word in its lettering, such as the countdown's): letters
    with their depth and an ink outline, on transparency. ``colors`` are the face, its lit
    rim, the near depth and the far depth."""
    face_color, light_color, side_color, deep_color = colors
    letters = letter_mask(text, scale)
    pad = OUTLINE
    size = (letters.width + 2 * DEPTH + 2 * pad, letters.height + DEPTH + 2 * pad)
    face = Image.new("L", size, 0)
    face.paste(letters, (pad, pad))

    # The depth: the face repeated down and to the right, two pixels across per pixel down.
    near = Image.new("L", size, 0)
    far = Image.new("L", size, 0)
    for step in range(1, DEPTH + 1):
        layer = far if step > DEPTH // 2 else near
        layer.paste(255, (pad + 2 * step, pad + step), letters)
        layer.paste(255, (pad + 2 * step - 1, pad + step), letters)
    solid = ImageChops.lighter(face, ImageChops.lighter(near, far))
    outline = solid.filter(ImageFilter.MaxFilter(3))

    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((*EDGE, 255), (0, 0), outline)
    image.paste((*deep_color, 255), (0, 0), far)
    image.paste((*side_color, 255), (0, 0), near)
    image.paste((*face_color, 255), (0, 0), face)
    # A lit rim along the top of every stroke: face pixels with nothing just above them.
    above = Image.new("L", size, 0)
    above.paste(face, (0, LIGHT_ROWS))
    rim = ImageChops.subtract(face, above)
    image.paste((*light_color, 255), (0, 0), rim)
    return _with_seam(image, face)


def _with_seam(image: Image.Image, face: Image.Image) -> Image.Image:
    """Draw a 1 px ink edge down the right and along the bottom of the letter faces, where
    a face meets its own side, so the letters read against their depth."""
    shifted_right = Image.new("L", face.size, 0)
    shifted_right.paste(face, (1, 0))
    shifted_down = Image.new("L", face.size, 0)
    shifted_down.paste(face, (0, 1))
    edge = ImageChops.subtract(ImageChops.lighter(shifted_right, shifted_down), face)
    image.paste((*EDGE, 255), (0, 0), edge)
    return image


def logo_size(text: str = LOGO_TEXT) -> tuple[int, int]:
    """Return the logo's size in pixels."""
    return build_logo(text).size
