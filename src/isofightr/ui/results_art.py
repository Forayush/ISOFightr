"""Art for the victory screen: confetti and the wavy banner's letters.

Plan note "13 - Game Modes UI and Flow" ("Results screen", decisions D-061 item 10 and
D-072). Drawn with Pillow from :mod:`isofightr.ui.theme` colours (every pixel a Resurrect 64
entry, tested). The banner's letters are the logo's extruded lettering, one picture each so
they can wave. Since D-072 the fighters stand on the Isle's ring, so the podium steps and
the spotlight are gone.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image

from isofightr.ui import logo, theme
from isofightr.ui.theme import Ramp, Rgb

BANNER_LETTER_SCALE: Final[int] = 2
SPACE_WIDTH: Final[int] = 16
LETTER_GAP: Final[int] = 5
"""Pixels between the banner's letters: room for each letter's depth."""
"""Width of the gap a space leaves in the banner."""


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
