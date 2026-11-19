"""Art for the Fighters screen: the card under each fighter, and its costume chips.

Decision D-077. A card is a stone block like every menu's (decision D-072) with two things
in its archetype's colours (:data:`isofightr.ui.theme.ARCHETYPE_COLOURS`): a band across its
top, and its front lip. Every pixel is a Resurrect 64 entry (tested).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageChops, ImageDraw

from isofightr.ui import kit_art, theme
from isofightr.ui.theme import ArchetypeColours, Rgb

CARD_CORNER = theme.CORNER


def _lighter(colours: ArchetypeColours) -> Rgb:
    """Return the shade of the ramp just lighter than the band (its lit line)."""
    ramp = colours.ramp
    if colours.band in ramp:
        return ramp[max(ramp.index(colours.band) - 1, 0)]
    return ramp[0]


def fighter_card(
    width: int,
    height: int,
    colours: ArchetypeColours,
    band: int,
    dividers: Sequence[int] = (),
    focused: bool = False,
) -> Image.Image:
    """Return a card: a stone block with its lip in the archetype's colour, a band ``band``
    rows deep under its top outline in the band colour (lit along its top, a deep line
    under it), thin lines across it at ``dividers`` (rows from the bottom), and the gold rim
    of focus when ``focused``."""
    lip = theme.LIP
    face = theme.STONE.face
    image = kit_art.block(
        width,
        height,
        (face, theme.STONE.light, colours.ramp[1], theme.INK),
        lip,
        CARD_CORNER,
    )
    top = kit_art.shape_mask(width, height - lip, CARD_CORNER)
    inside = ImageChops.subtract(top, kit_art._edge(top))
    rows = Image.new("L", (width, height), 0)
    ImageDraw.Draw(rows).rectangle((0, 1, width - 1, band), fill=255)
    band_mask = ImageChops.multiply(inside, rows)
    image.paste(_solid(colours.band), (0, 0), band_mask)
    lit = Image.new("L", (width, height), 0)
    ImageDraw.Draw(lit).line((0, 1, width - 1, 1), fill=255)
    image.paste(_solid(_lighter(colours)), (0, 0), ImageChops.multiply(band_mask, lit))
    deep = Image.new("L", (width, height), 0)
    ImageDraw.Draw(deep).line((0, band + 1, width - 1, band + 1), fill=255)
    image.paste(_solid(colours.ramp[3]), (0, 0), ImageChops.multiply(inside, deep))
    draw = ImageDraw.Draw(image)
    inset = 6
    for row in dividers:
        y = height - 1 - row
        draw.line((inset, y, width - 1 - inset, y), fill=theme.MIST)
    if focused:
        rim = kit_art.focus_frame(width, height, theme.FOCUS, CARD_CORNER)
        image.alpha_composite(rim)
    return image


def costume_chip(size: int, color: Rgb, shown: bool = False) -> Image.Image:
    """Return a costume's chip on a card's band: its colour in an ink square; the costume
    on show is ringed in white, a pixel further out (the picture is ``size + 2`` then)."""
    if not shown:
        return kit_art.swatch(size, color)
    image = Image.new("RGBA", (size + 2, size + 2), kit_art.TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size + 1, size + 1), outline=theme.WHITE)
    image.paste(kit_art.swatch(size, color), (1, 1))
    return image


def _solid(color: Rgb) -> tuple[int, int, int, int]:
    return (color[0], color[1], color[2], 255)
