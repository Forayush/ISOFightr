"""Widget art: panels, buttons, tabs, toggles, key caps, gauges and the focus frame.

Plan note "09 - Art Direction" ("UI theme", decision D-061). Everything is drawn with Pillow
from :mod:`isofightr.ui.theme` colours, so every pixel is a Resurrect 64 entry (tested).
Shapes have the angled 2:1 corners of the isometric tiles: a corner ``c`` pixels tall is
``2c`` wide. Text is not drawn here; :mod:`isofightr.ui.widgets` lays it over the art.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from isofightr.ui import theme
from isofightr.ui.theme import Rgb, Rgba

TRANSPARENT: Final[Rgba] = (0, 0, 0, 0)
Corners = tuple[bool, bool, bool, bool]
"""Which corners are angled: top-left, top-right, bottom-left, bottom-right."""
TILE_CORNERS: Final[Corners] = (True, False, False, True)
"""The default: the top-left and bottom-right corners, like a tile seen from above."""
ALL_CORNERS: Final[Corners] = (True, True, True, True)
NO_CORNERS: Final[Corners] = (False, False, False, False)
KEY_LIP: Final[int] = 3
"""Height of the front face under a key cap's top."""
FOCUS_THICKNESS: Final[int] = 2
GAUGE_SEGMENT: Final[int] = 4
"""A gauge fills in steps this wide, with a 1 px notch between them."""


class Look(Enum):
    """How a button or key cap is shown."""

    NORMAL = "normal"
    FOCUS = "focus"
    """Under the cursor."""
    DANGER = "danger"
    """Something that overwrites (DEFAULT), or an unbound control."""
    LIT = "lit"
    """Held right now (the live test)."""
    DISABLED = "disabled"


def _solid(color: Rgb | Rgba) -> Rgba:
    return (color[0], color[1], color[2], color[3] if len(color) == 4 else 255)  # type: ignore[misc]


def shape_mask(
    width: int, height: int, corner: int = theme.CORNER, corners: Corners = TILE_CORNERS
) -> Image.Image:
    """Return the mask of a rectangle with angled 2:1 corners (255 inside)."""
    width, height = max(width, 1), max(height, 1)
    corner = max(min(corner, height // 2, width // 4), 0)
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    top_left, top_right, bottom_left, bottom_right = corners
    for y in range(height):
        from_top, from_bottom = corner - y, corner - (height - 1 - y)
        left = max(2 * from_top if top_left else 0, 2 * from_bottom if bottom_left else 0, 0)
        right = max(2 * from_top if top_right else 0, 2 * from_bottom if bottom_right else 0, 0)
        if left <= width - 1 - right:
            draw.line((left, y, width - 1 - right, y), fill=255)
    return mask


def slant_mask(width: int, height: int) -> Image.Image:
    """Return the mask of a parallelogram leaning right at the tiles' 2:1 slope (tabs)."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    reach = (height - 1) // 2
    for y in range(height):
        shift = (height - 1 - y) // 2  # the top edge sits furthest right
        draw.line((shift, y, width - 1 - (reach - shift), y), fill=255)
    return mask


def _edge(mask: Image.Image, thickness: int = 1) -> Image.Image:
    """Return the mask's outer rim, ``thickness`` pixels deep."""
    inner = mask
    for _ in range(thickness):
        # Pad first so the image border counts as outside.
        padded = Image.new("L", (mask.width + 2, mask.height + 2), 0)
        padded.paste(inner, (1, 1))
        inner = padded.filter(ImageFilter.MinFilter(3)).crop(
            (1, 1, mask.width + 1, mask.height + 1)
        )
    return ImageChops.subtract(mask, inner)


def filled(
    mask: Image.Image,
    fill: Rgb | Rgba,
    border: Rgb | Rgba | None = None,
    thickness: int = 1,
) -> Image.Image:
    """Return a mask painted with a fill and, optionally, a border along its rim."""
    image = Image.new("RGBA", mask.size, TRANSPARENT)
    image.paste(_solid(fill), (0, 0), mask)
    if border is not None:
        image.paste(_solid(border), (0, 0), _edge(mask, thickness))
    return image


def panel(
    width: int,
    height: int,
    fill: Rgb | Rgba = theme.PANEL_FILL,
    border: Rgb | Rgba = theme.PANEL_BORDER,
    corner: int = theme.CORNER,
    corners: Corners = TILE_CORNERS,
    light: Rgb | Rgba | None = theme.PANEL_LIGHT,
) -> Image.Image:
    """Return a panel: a translucent body, a border, and a lit line under its top edge."""
    mask = shape_mask(width, height, corner, corners)
    image = filled(mask, fill, border)
    if light is not None and height > 4:
        rim = _edge(mask, 2)
        inner = ImageChops.subtract(rim, _edge(mask, 1))
        top_only = Image.new("L", mask.size, 0)
        top_only.paste(inner.crop((0, 0, width, 2)), (0, 0))
        image.paste(_solid(light), (0, 0), top_only)
    return image


_BUTTON_LOOKS: Final[dict[Look, tuple[Rgba, Rgba]]] = {
    Look.NORMAL: (theme.BUTTON_FILL, theme.BUTTON_BORDER),
    Look.FOCUS: (theme.BUTTON_FOCUS_FILL, theme.BUTTON_FOCUS_BORDER),
    Look.DANGER: (theme.DANGER_FILL, theme.DANGER_BORDER),
    Look.LIT: (theme.with_alpha(theme.AQUA, 255), theme.with_alpha(theme.MINT, 255)),
    Look.DISABLED: (theme.with_alpha(theme.SLATE, 255), theme.with_alpha(theme.DUST, 255)),
}
"""``(fill, border)`` of a button in each look."""


def button(width: int, height: int, look: Look = Look.NORMAL) -> Image.Image:
    """Return a button body."""
    fill, border = _BUTTON_LOOKS[look]
    return filled(shape_mask(width, height, theme.SMALL_CORNER), fill, border)


def text_color(look: Look) -> Rgb:
    """Return the colour of the caption on a button or key cap in a look."""
    if look is Look.FOCUS:
        return theme.TEXT_ON_FOCUS
    if look is Look.DISABLED:
        return theme.TEXT_DIM
    return theme.TEXT


def tab(width: int, height: int, color: Rgb, active: bool) -> Image.Image:
    """Return a tab: a leaning parallelogram, filled with its colour when active and only
    outlined in it otherwise."""
    mask = slant_mask(width, height)
    if active:
        return filled(mask, color, theme.WHITE)
    return filled(mask, theme.PANEL_DEEP, color)


def key_cap(width: int, height: int, look: Look = Look.NORMAL) -> Image.Image:
    """Return a key cap: a raised top face over a darker front lip."""
    fill, border = _BUTTON_LOOKS[look]
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    base = shape_mask(width, height, theme.SMALL_CORNER, ALL_CORNERS)
    image.paste(_solid(theme.INK), (0, 0), base)
    image.paste(_solid(border), (0, 0), _edge(base))
    top = filled(shape_mask(width, height - KEY_LIP, theme.SMALL_CORNER, ALL_CORNERS), fill, border)
    image.alpha_composite(top, (0, 0))
    return image


def toggle(width: int, height: int, on: bool, focused: bool = False) -> Image.Image:
    """Return an ON/OFF switch body: bright when on, sunk when off."""
    fill = theme.ON if on else theme.SLATE
    border = theme.FOCUS_GLOW if focused else (theme.FOG if on else theme.DUST)
    return filled(shape_mask(width, height, theme.SMALL_CORNER), fill, border)


def stepper(width: int, height: int, focused: bool = False) -> Image.Image:
    """Return the well a ``< value >`` stepper's value sits in."""
    border = theme.FOCUS if focused else theme.BUTTON_BORDER
    return filled(shape_mask(width, height, theme.SMALL_CORNER), theme.PANEL_DEEP, border)


def list_row(width: int, height: int, focused: bool = False) -> Image.Image:
    """Return the strip behind one row of a list (rules, stages): dark at rest, lit and
    ringed in the focus colour under the cursor."""
    if focused:
        return filled(shape_mask(width, height, theme.SMALL_CORNER), theme.BUTTON_FILL, theme.FOCUS)
    return filled(shape_mask(width, height, theme.SMALL_CORNER), theme.PANEL_DEEP)


def tag_plate(width: int, height: int, color: Rgb) -> Image.Image:
    """Return the dark plate behind a fighter's name tag, edged in the player's colour, so
    the name reads over any stage."""
    return filled(shape_mask(width, height, 1, ALL_CORNERS), theme.PANEL_DEEP, color)


def gauge(
    width: int,
    height: int,
    fraction: float,
    fill: Rgb | Rgba = theme.GAUGE_FILL,
    segmented: bool = False,
) -> Image.Image:
    """Return a bar filled to ``fraction`` (0 to 1) of its width."""
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (0, 0, width - 1, height - 1), fill=theme.GAUGE_TRACK, outline=theme.BUTTON_BORDER
    )
    inner = width - 2
    lit = round(inner * min(max(fraction, 0.0), 1.0))
    if lit > 0:
        draw.rectangle((1, 1, lit, height - 2), fill=_solid(fill))
        if segmented:
            for x in range(GAUGE_SEGMENT, lit, GAUGE_SEGMENT + 1):
                draw.line((x, 1, x, height - 2), fill=theme.GAUGE_TRACK)
    return image


def checkbox(size: int, checked: bool, focused: bool = False) -> Image.Image:
    """Return a checkbox; the tick is two strokes in the focus colour."""
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    border = theme.FOCUS if focused else theme.BUTTON_BORDER
    draw.rectangle((0, 0, size - 1, size - 1), fill=theme.GAUGE_TRACK, outline=border)
    if checked:
        low = size - 4
        draw.line((2, size // 2, size // 2 - 1, low), fill=theme.ON, width=1)
        draw.line((size // 2 - 1, low, size - 3, 2), fill=theme.ON, width=1)
    return image


def swatch(size: int, color: Rgb, selected: bool = False) -> Image.Image:
    """Return a colour swatch (costumes, teams), ringed when it is the chosen one."""
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size - 1, size - 1), fill=color, outline=theme.INK)
    if selected:
        draw.rectangle((0, 0, size - 1, size - 1), outline=theme.FOCUS_GLOW)
    return image


def focus_frame(
    width: int,
    height: int,
    color: Rgb = theme.FOCUS,
    corner: int = theme.SMALL_CORNER,
    corners: Corners = TILE_CORNERS,
) -> Image.Image:
    """Return a hollow frame to lay over whatever the cursor is on."""
    mask = shape_mask(width, height, corner, corners)
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    image.paste(_solid(color), (0, 0), _edge(mask, FOCUS_THICKNESS))
    return image


def divider(width: int) -> Image.Image:
    """Return a 1 px rule that fades out at both ends (by getting sparser, not paler)."""
    image = Image.new("RGBA", (width, 1), TRANSPARENT)
    fade = max(width // 6, 1)
    for x in range(width):
        from_end = min(x, width - 1 - x)
        if from_end >= fade or from_end % 2 == 0:
            image.putpixel((x, 0), _solid(theme.STEEL))
    return image


def tint(image: Image.Image, color: Rgb) -> Image.Image:
    """Return a white-and-grey image (an icon) recoloured: white becomes ``color``, and the
    other pixels keep their own colour."""
    result = image.copy()
    white = Image.new("L", image.size, 0)
    pixels = image.load()
    assert pixels is not None
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y] == (255, 255, 255, 255):
                white.putpixel((x, y), 255)
    result.paste(_solid(color), (0, 0), white)
    return result
