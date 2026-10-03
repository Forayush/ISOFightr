"""Portraits cut from portrait renders: a bust for menus and a head icon for stocks.

Plan note "09 - Art Direction" ("Technical specs": stock icon, HUD portrait, CSS art). Both
are cut from a render of the character's ``portrait.toml`` pose facing the viewer; the icon is
rendered at half scale so the whole head fits a stock slot. They are indexed like the sheets,
so costumes recolour them the same way.
"""

from __future__ import annotations

from typing import Final

from PIL import Image

BUST_SIZE: Final[int] = 30
"""Bust portrait: head and shoulders, in native pixels (square)."""
ICON_SIZE: Final[int] = 12
"""Stock icon: the head at half scale, in native pixels (square)."""
ICON_SCALE: Final[float] = 0.5
PORTRAIT_FACING: Final[str] = "S"


def crop_top(image: Image.Image, size: int) -> Image.Image:
    """Return a ``size`` x ``size`` square from the top of a drawing, centred on what is
    drawn in it (the head, for a standing character). Empty space stays transparent."""
    box = image.point(lambda value: 255 if value else 0).getbbox()
    if box is None:
        return Image.new(image.mode, (size, size))
    top = box[1]
    band = image.crop((0, top, image.width, min(top + size, image.height)))
    columns = band.point(lambda value: 255 if value else 0).getbbox()
    assert columns is not None
    centre = (columns[0] + columns[2]) // 2
    left = centre - size // 2
    square = Image.new(image.mode, (size, size))
    square.paste(image.crop((left, top, left + size, top + size)), (0, 0))
    return square
