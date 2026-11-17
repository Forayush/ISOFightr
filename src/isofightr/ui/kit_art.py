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
    """An unbound control, or a button that overwrites things while the cursor is on it."""
    CAUTION = "caution"
    """A button that overwrites things (DEFAULT), at rest: dark with a red rim, so it does
    not shout while nobody is about to press it (decision D-070)."""
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
    Look.CAUTION: (theme.CAUTION_FILL, theme.CAUTION_BORDER),
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
    if look is Look.CAUTION:
        return theme.CAUTION_TEXT
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


def level_bar(
    width: int, height: int, lit: int, fill: Rgb | Rgba = theme.GAUGE_FILL
) -> Image.Image:
    """Return an upright bar lit ``lit`` pixels up from its foot (the sound test's meter)."""
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (0, 0, width - 1, height - 1), fill=theme.GAUGE_TRACK, outline=theme.BUTTON_BORDER
    )
    lit = min(max(lit, 0), height - 2)
    if lit > 0:
        draw.rectangle((1, height - 1 - lit, width - 2, height - 2), fill=_solid(fill))
    return image


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


def mechanic_badge(size: int, on: bool) -> Image.Image:
    """Return the mark on a stage tile whose stage has a mechanic: a bolt in a box, gold
    while the "stage hazards" rule is on and grey while it is off (decision D-063)."""
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    color = theme.FOCUS if on else theme.TEXT_MUTED
    draw.rectangle((0, 0, size - 1, size - 1), fill=theme.GAUGE_TRACK, outline=color)
    middle = size // 2
    draw.line((middle + 1, 2, middle - 1, middle), fill=color, width=1)
    draw.line((middle - 1, middle, middle + 1, middle), fill=color, width=1)
    draw.line((middle + 1, middle, middle - 1, size - 3), fill=color, width=1)
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


# --- the block kit (decision D-072) ----------------------------------------------------------
#
# Every widget is a block seen like a tile: a top face, a front lip under it, a 1 px outline
# and the tiles' 2:1 corners. A block comes in one of two surfaces (stone for menus, ink over
# a match) and one of the looks above; the cursor's block stands ``theme.RAISE`` higher.

PIP_SIZE: Final[tuple[int, int]] = (8, 7)
"""A pip: one small isometric tile (gauges, steppers and the HUD's stocks count in them)."""
PIP_STEP: Final[int] = 9
TURF_ROWS: Final[int] = 4
"""Rows of grass along the top of a header plate."""
TURF_TUFTS: Final[tuple[int, ...]] = (0, 1, 0, 2, 1, 0, 0, 1, 2, 0, 1, 0, 0, 2, 0, 1)
"""How much further the turf hangs down, column by column (a fixed pattern: no shimmer)."""
PAD_BUTTON: Final[int] = 13
"""Diameter of a gamepad button's disc in a prompt."""
PAD_BUTTON_COLOURS: Final[dict[str, Rgb]] = {
    "A": theme.GREEN,
    "B": theme.RED,
    "X": theme.SKY,
    "Y": theme.GOLD,
}
"""Face buttons in the colours players know them by; every other control is a plain cap."""

BlockColours = tuple[Rgb | Rgba, Rgb, Rgb, Rgb]
"""A block's face, the lit line along its top, its lip and its outline."""


def block(
    width: int,
    height: int,
    colours: BlockColours,
    lip: int = theme.LIP,
    corner: int = theme.SMALL_CORNER,
    corners: Corners = TILE_CORNERS,
) -> Image.Image:
    """Return a block: its top face over a front lip ``lip`` pixels tall, all inside an
    outline. The picture is ``width`` by ``height``; the face is its top ``height - lip``
    rows."""
    face, light, lip_colour, outline = colours
    width, height = max(width, 3), max(height, 3)
    lip = min(max(lip, 0), height - 3)
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    base = shape_mask(width, height, corner, corners)
    image.paste(_solid(lip_colour), (0, 0), base)
    image.paste(_solid(outline), (0, 0), _edge(base))
    top = Image.new("L", (width, height), 0)
    top.paste(shape_mask(width, height - lip, corner, corners), (0, 0))
    rim = _edge(top)
    inside = ImageChops.subtract(top, rim)
    # Replace, not blend: a translucent face must not show its own lip through.
    image.paste(_solid(face), (0, 0), inside)
    image.paste(_solid(outline), (0, 0), rim)
    # The lit line: the face's pixels that have the outline right above them.
    above = Image.new("L", top.size, 0)
    above.paste(inside, (0, 1))
    image.paste(_solid(light), (0, 0), ImageChops.subtract(inside, above))
    return image


def look_colours(look: Look, surface: theme.Surface) -> BlockColours:
    """Return the colours of a button or key cap in a look, on a surface."""
    if look is Look.FOCUS:
        return (theme.GOLD, theme.PALE_GOLD, theme.AMBER, theme.INK)
    if look is Look.DANGER:
        return (theme.CRIMSON, theme.RED, theme.MAROON, theme.INK)
    if look is Look.LIT:
        return (theme.AQUA, theme.MINT, theme.TEAL, theme.INK)
    if look is Look.CAUTION:
        if surface is theme.STONE:
            return (surface.button, surface.button_light, surface.button_lip, theme.CRIMSON)
        return (theme.INK, theme.SLATE, theme.MAROON, theme.CRIMSON)
    if look is Look.DISABLED:
        if surface is theme.STONE:
            return (theme.MIST, theme.FOG, theme.DUST, theme.ASH)
        return (theme.SLATE, theme.ASH, theme.INK, theme.INK)
    return (surface.button, surface.button_light, surface.button_lip, surface.outline)


def look_text(look: Look, surface: theme.Surface) -> Rgb:
    """Return the colour of the caption on a block in a look, on a surface."""
    if look in (Look.FOCUS, Look.LIT):
        return theme.INK
    if look is Look.DANGER:
        return theme.WHITE
    if look is Look.CAUTION:
        return surface.warning
    if look is Look.DISABLED:
        return surface.text_dim
    return surface.text


def lift_of(look: Look, pressed: bool = False) -> int:
    """Return how far a block's face stands from its resting place: up by ``theme.RAISE``
    under the cursor, down by all but one row of its lip while it is pressed."""
    if pressed:
        return -(theme.LIP - 1)
    return theme.RAISE if look in (Look.FOCUS, Look.DANGER) else 0


def block_button(
    width: int,
    height: int,
    look: Look = Look.NORMAL,
    surface: theme.Surface = theme.STONE,
    lift: int = 0,
    corner: int = theme.SMALL_CORNER,
    corners: Corners = TILE_CORNERS,
) -> Image.Image:
    """Return a button as a block. ``lift`` above 0 makes the picture that many rows taller
    (the face rises and the lip grows: the cursor's block); below 0 the face sinks into its
    lip (a pressed block) and the picture keeps its size, empty along the top."""
    return _lifted(width, height, look_colours(look, surface), lift, corner, corners)


def _lifted(
    width: int, height: int, colours: BlockColours, lift: int, corner: int, corners: Corners
) -> Image.Image:
    if lift >= 0:
        return block(width, height + lift, colours, theme.LIP + lift, corner, corners)
    sunk = block(width, height + lift, colours, theme.LIP + lift, corner, corners)
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    image.paste(sunk, (0, -lift))
    return image


def toggle_block(
    width: int, height: int, on: bool, focused: bool, surface: theme.Surface = theme.STONE
) -> Image.Image:
    """Return an ON/OFF switch as a block: standing and mint when on, sunk into its lip and
    dull when off, so the state shows in the shape as well as the colour and the word. Its
    outline is gold under the cursor."""
    outline = theme.FOCUS if focused else surface.outline
    if on:
        colours: BlockColours = (theme.MINT, theme.WHITE, theme.AQUA, outline)
        return _lifted(width, height, colours, 0, theme.SMALL_CORNER, TILE_CORNERS)
    face = theme.MIST if surface is theme.STONE else theme.SLATE
    lip = theme.DUST if surface is theme.STONE else theme.INK
    return _lifted(
        width, height, (face, face, lip, outline), lift_of(Look.NORMAL, True),
        theme.SMALL_CORNER, TILE_CORNERS,
    )  # fmt: skip


def row_strip(
    width: int, height: int, focused: bool = False, surface: theme.Surface = theme.STONE
) -> Image.Image:
    """Return the strip behind one row of a list on a slab (the rules, a settings page):
    the surface's well at rest, gold under the cursor."""
    if focused:
        return filled(shape_mask(width, height, theme.SMALL_CORNER), theme.GOLD, theme.INK)
    return filled(shape_mask(width, height, theme.SMALL_CORNER), surface.well, surface.well_edge)


def toggle_text(on: bool, surface: theme.Surface) -> Rgb:
    """Return the colour of the word on a block switch."""
    if on or surface is theme.STONE:
        return theme.INK
    return theme.MIST


def face_span(height: int, lift: int = 0) -> tuple[int, int]:
    """Return a block button's face as ``(rows above the button's bottom, its height)``:
    where its caption is centred at rest, raised or pressed."""
    lip = theme.LIP + lift
    return (lip, height + lift - lip)


def slab(
    width: int,
    height: int,
    surface: theme.Surface = theme.STONE,
    corner: int = theme.CORNER,
    corners: Corners = TILE_CORNERS,
    lip: int = theme.LIP,
) -> Image.Image:
    """Return a slab: the block a group of things sits on (a panel, in the block kit)."""
    colours = (surface.face, surface.light, surface.lip, surface.outline)
    return block(width, height, colours, lip, corner, corners)


def well(
    width: int,
    height: int,
    surface: theme.Surface = theme.STONE,
    focused: bool = False,
    corner: int = theme.SMALL_CORNER,
) -> Image.Image:
    """Return something sunk into a slab (a stepper's value): flat, with an edge that turns
    gold under the cursor."""
    edge = theme.FOCUS if focused else surface.well_edge
    return filled(shape_mask(width, height, corner), surface.well, edge)


def sign(width: int, height: int, surface: theme.Surface = theme.STONE) -> Image.Image:
    """Return the plate a line of help is written on: a thin block of its own in the
    surface's well colours, so it reads as a note and not as a button."""
    colours = (surface.well, _solid(surface.well)[:3], surface.well_edge, surface.outline)
    return block(width, height, colours, 2, theme.SMALL_CORNER)


def plate(width: int, height: int, surface: theme.Surface = theme.STONE) -> Image.Image:
    """Return a header plate: a slab with turf along its top, like the Isle's rim. The turf
    hangs over the face in tufts."""
    image = slab(width, height, surface, theme.CORNER)
    top = Image.new("L", (width, height), 0)
    top.paste(shape_mask(width, height - theme.LIP, theme.CORNER), (0, 0))
    inside = ImageChops.subtract(top, _edge(top))
    turf = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(turf)
    for x in range(width):
        first = _first_row(inside, x)
        depth = TURF_ROWS + TURF_TUFTS[x % len(TURF_TUFTS)]
        for row in range(depth):
            if row < 2:
                colour = theme.GRASS_LIGHT
            elif row < depth - 1:
                colour = theme.GRASS
            else:
                colour = theme.GRASS_DARK
            if first + row < height:
                draw.point((x, first + row), fill=_solid(colour))
    image.paste(turf, (0, 0), ImageChops.multiply(inside, turf.getchannel("A")))
    return image


def _first_row(mask: Image.Image, x: int) -> int:
    """Return the first row of a mask that is set in column ``x`` (its height if none)."""
    for y in range(mask.height):
        if mask.getpixel((x, y)):
            return y
    return mask.height


def pip(ramp: theme.Ramp, lit: bool = True) -> Image.Image:
    """Return a pip: a tiny isometric tile in a colour ramp, lit on top; an unlit one is the
    same shape in the ramp's deepest shade, an empty socket."""
    light, base, dark, deep = ramp
    width, height = PIP_SIZE
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    half, last = width // 2, width - 1
    top = [(0, 2), (half - 1, 0), (half, 0), (last, 2), (half, 4), (half - 1, 4)]
    left = [(0, 2), (half - 1, 4), (half - 1, height - 1), (0, height - 3)]
    right = [(last, 2), (half, 4), (half, height - 1), (last, height - 3)]
    if not lit:
        for shape in (left, right, top):
            draw.polygon(shape, fill=deep)
        return image
    draw.polygon(left, fill=base)
    draw.polygon(right, fill=dark)
    draw.polygon(top, fill=light)
    return image


GOLD_RAMP: Final[theme.Ramp] = (theme.PALE_GOLD, theme.GOLD, theme.AMBER, theme.DUST)
"""The pips of a gauge that is nobody's in particular (a volume, a stat)."""


def pips(count: int, lit: int, ramp: theme.Ramp = GOLD_RAMP) -> Image.Image:
    """Return a row of ``count`` pips, the first ``lit`` of them lit: a gauge to count."""
    count = max(count, 1)
    image = Image.new("RGBA", (pips_width(count), PIP_SIZE[1]), TRANSPARENT)
    for index in range(count):
        image.alpha_composite(pip(ramp, index < lit), (index * PIP_STEP, 0))
    return image


def pips_width(count: int) -> int:
    """Return the width of a row of ``count`` pips."""
    return PIP_STEP * (max(count, 1) - 1) + PIP_SIZE[0]


def pad_button(label: str, size: int = PAD_BUTTON) -> Image.Image:
    """Return the disc of a gamepad button for a prompt: in its usual colour for a face
    button, slate otherwise. The widget draws the letter over it."""
    colour = PAD_BUTTON_COLOURS.get(label.upper(), theme.SLATE)
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, size - 1, size - 1), fill=_solid(colour), outline=_solid(theme.INK))
    return image


def pad_button_text(label: str) -> Rgb:
    """Return the colour of the letter on a gamepad button's disc."""
    return theme.INK if label.upper() == "Y" else theme.WHITE
