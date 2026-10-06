"""The game's pixel font, drawn at exact native sizes with anti-aliasing off.

Plan note "13 - Game Modes UI and Flow" ("UI implementation notes") and decision D-061. The
faces are Departure Mono for body text, the Jersey family for headings and numbers, and
Tiny5 for fine print (all under the SIL Open Font License 1.1: the licence files are in
``assets/fonts/`` and the credits in ``assets/CREDITS.md``), each used only at a size where
its outlines land on whole pixels.
Pillow rasterises them (it is already a dependency); there is no text layout engine here,
just single lines. If a font file cannot be loaded the old built-in bitmap font is used,
enlarged by whole numbers, so the game still starts.

Besides the font's own characters a line may hold the four arrows ``← → ↑ ↓``, which are
drawn as triangles (the faces have none).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from isofightr.data.paths import ASSETS_DIR
from isofightr.ui.theme import TEXT, TEXT_SHADOW, Rgb, Rgba

LOG = logging.getLogger(__name__)

FONTS_DIR: Final[Path] = ASSETS_DIR / "fonts"
PRINTABLE: Final[str] = "".join(chr(code) for code in range(33, 127))
ARROW_LEFT, ARROW_RIGHT, ARROW_UP, ARROW_DOWN = "←", "→", "↑", "↓"
ARROWS: Final[str] = ARROW_LEFT + ARROW_RIGHT + ARROW_UP + ARROW_DOWN
ELLIPSIS: Final[str] = ".."
"""What :func:`fit` ends a shortened line with."""
SHADOW_OFFSET: Final[int] = 1
FALLBACK_HEIGHT: Final[int] = 11
"""Line height of Pillow's built-in bitmap font."""


class TextSize(Enum):
    """The sizes text comes in."""

    SMALL = "small"
    """Tags and fine print: capitals 5 px tall."""
    BODY = "body"
    """Labels, values and sentences: fixed width, capitals 8 px tall."""
    TITLE = "title"
    """Names and button captions: capitals 12 px tall."""
    DISPLAY = "display"
    """Headings and banners: capitals 16 px tall."""
    NUMERAL = "numeral"
    """The damage number: the small face tripled, 16 px tall and chunky."""


_SPECS: Final[dict[TextSize, tuple[str, int, int]]] = {
    TextSize.SMALL: ("Tiny5-Regular.ttf", 8, 1),
    TextSize.BODY: ("DepartureMono-Regular.otf", 11, 1),
    TextSize.TITLE: ("Jersey25-Regular.ttf", 20, 1),
    TextSize.DISPLAY: ("Jersey25-Regular.ttf", 25, 1),
    TextSize.NUMERAL: ("Jersey10-Regular.ttf", 30, 3),
}
"""File, pixel size and (for the fallback) the whole-number enlargement of the built-in font."""
FONT_FILES: Final[tuple[str, ...]] = tuple(sorted({spec[0] for spec in _SPECS.values()}))


@dataclass(frozen=True, slots=True)
class Face:
    """One loaded size: the font and the measurements text is laid out with."""

    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    fallback: bool
    """Whether this is the built-in bitmap font standing in for a missing file."""
    scale: int
    """Whole-number enlargement applied after drawing (1 for real font files)."""
    top: int
    """The font's own y of the highest pixel any printable character has."""
    height: int
    """Rows from the highest to the lowest pixel of any printable character."""
    cap_top: int
    """Rows from the top of a line image down to the top of a capital letter."""
    cap_height: int
    """Height of a capital letter in pixels."""

    @property
    def baseline(self) -> int:
        """Rows from the top of a line image down to the bottom of a capital letter."""
        return self.cap_top + self.cap_height

    @property
    def descent(self) -> int:
        """Rows a line image has below the bottom of its capital letters."""
        return self.height - self.baseline


_FACES: dict[tuple[TextSize, Path], Face] = {}


def _measure(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, scale: int) -> Face:
    boxes = [font.getbbox(character) for character in PRINTABLE]
    top = int(min(box[1] for box in boxes))
    bottom = int(max(box[3] for box in boxes))
    cap = font.getbbox("H")
    return Face(
        font=font,
        fallback=not isinstance(font, ImageFont.FreeTypeFont),
        scale=scale,
        top=top,
        height=(bottom - top) * scale,
        cap_top=(int(cap[1]) - top) * scale,
        cap_height=int(cap[3] - cap[1]) * scale,
    )


def face(size: TextSize, fonts_dir: Path = FONTS_DIR) -> Face:
    """Return the loaded face for a size (cached). A missing or broken font file gives the
    built-in bitmap font instead, enlarged to roughly the same height."""
    key = (size, fonts_dir)
    cached = _FACES.get(key)
    if cached is not None:
        return cached
    file_name, pixels, fallback_scale = _SPECS[size]
    try:
        loaded = _measure(ImageFont.truetype(str(fonts_dir / file_name), pixels), 1)
    except OSError as error:
        LOG.warning("font %s not loaded (%s): using the built-in font", file_name, error)
        loaded = _measure(ImageFont.load_default_imagefont(), fallback_scale)
    _FACES[key] = loaded
    return loaded


def using_fallback(fonts_dir: Path = FONTS_DIR) -> bool:
    """Return whether any size fell back to the built-in font."""
    return any(face(size, fonts_dir).fallback for size in TextSize)


def _runs(text: str) -> list[tuple[bool, str]]:
    """Split a line into runs of ordinary characters and single arrows."""
    runs: list[tuple[bool, str]] = []
    plain = ""
    for character in text:
        if character in ARROWS:
            if plain:
                runs.append((False, plain))
                plain = ""
            runs.append((True, character))
        else:
            plain += character
    if plain:
        runs.append((False, plain))
    return runs


def _arrow_size(loaded: Face) -> int:
    """Side of the square an arrow is drawn in: the capital height, made odd."""
    return loaded.cap_height | 1


def _run_width(loaded: Face, arrow: bool, run: str) -> int:
    if arrow:
        return _arrow_size(loaded) + loaded.scale
    return math.ceil(loaded.font.getlength(run)) * loaded.scale


def text_width(text: str, size: TextSize = TextSize.BODY, fonts_dir: Path = FONTS_DIR) -> int:
    """Return the width in pixels of a line of text, without its shadow."""
    loaded = face(size, fonts_dir)
    return sum(_run_width(loaded, arrow, run) for arrow, run in _runs(text))


def line_height(size: TextSize = TextSize.BODY, fonts_dir: Path = FONTS_DIR) -> int:
    """Return the height of a rendered line, without its shadow."""
    return face(size, fonts_dir).height


def cap_height(size: TextSize = TextSize.BODY, fonts_dir: Path = FONTS_DIR) -> int:
    """Return the height of a capital letter."""
    return face(size, fonts_dir).cap_height


def _arrow(character: str, side: int) -> Image.Image:
    """Return a solid triangle pointing the arrow's way, as a mask."""
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    half = side // 2
    first = (side - (half + 1)) // 2
    for step in range(half + 1):
        # Pointing right: the leftmost column is the full height, the tip is one pixel.
        reach = half - step
        draw.line((first + step, half - reach, first + step, half + reach), fill=255)
    if character == ARROW_LEFT:
        return mask.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if character == ARROW_UP:
        return mask.transpose(Image.Transpose.ROTATE_90)
    if character == ARROW_DOWN:
        return mask.transpose(Image.Transpose.ROTATE_270)
    return mask


def mask(text: str, size: TextSize = TextSize.BODY, fonts_dir: Path = FONTS_DIR) -> Image.Image:
    """Return a line of text as a mask: 255 where there is ink, 0 elsewhere. Capital letters
    start :attr:`Face.cap_top` rows down, whatever the text."""
    loaded = face(size, fonts_dir)
    width = max(text_width(text, size, fonts_dir), 1)
    image = Image.new("L", (width, loaded.height), 0)
    x = 0
    for arrow, run in _runs(text):
        run_width = _run_width(loaded, arrow, run)
        if arrow:
            side = _arrow_size(loaded)
            image.paste(_arrow(run, side), (x, loaded.cap_top + (loaded.cap_height - side) // 2))
        else:
            small = Image.new("L", (run_width // loaded.scale, loaded.height // loaded.scale), 0)
            draw = ImageDraw.Draw(small)
            draw.fontmode = "1"
            draw.text((0, -loaded.top), run, fill=255, font=loaded.font)
            if loaded.scale > 1:
                small = small.resize(
                    (small.width * loaded.scale, small.height * loaded.scale),
                    Image.Resampling.NEAREST,
                )
            image.paste(small, (x, 0))
        x += run_width
    return image


def render(
    text: str,
    size: TextSize = TextSize.BODY,
    color: Rgb | Rgba = TEXT,
    shadow: Rgb | Rgba | None = TEXT_SHADOW,
    fonts_dir: Path = FONTS_DIR,
) -> Image.Image:
    """Return a line of text as an image: solid ``color`` on a transparent background, with a
    1 px drop shadow down and to the right unless ``shadow`` is ``None``.

    The image is ``text_width`` by ``line_height`` pixels, plus one each way for the shadow.
    """
    ink = mask(text, size, fonts_dir)
    extra = SHADOW_OFFSET if shadow is not None else 0
    image = Image.new("RGBA", (ink.width + extra, ink.height + extra), (0, 0, 0, 0))
    if shadow is not None:
        image.paste((*shadow[:3], 255), (SHADOW_OFFSET, SHADOW_OFFSET), ink)
    image.paste((*color[:3], 255), (0, 0), ink)
    return image


def fit(text: str, width: int, size: TextSize = TextSize.BODY, fonts_dir: Path = FONTS_DIR) -> str:
    """Return the text, shortened with ".." if it is wider than ``width`` pixels."""
    if text_width(text, size, fonts_dir) <= width:
        return text
    while text and text_width(text + ELLIPSIS, size, fonts_dir) > width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def wrap(
    text: str, width: int, size: TextSize = TextSize.BODY, fonts_dir: Path = FONTS_DIR
) -> list[str]:
    """Break text into lines no wider than ``width`` pixels, at spaces. A single word that
    is too wide gets a line of its own."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if line and text_width(candidate, size, fonts_dir) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines
