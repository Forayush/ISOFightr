"""The drawing half of the UI widget kit: panels, text and widgets at native resolution.

Plan note "13 - Game Modes UI and Flow" ("UI implementation notes", decision D-061): a small
widget set drawn at native resolution, batched in a few ``SpriteList``s per layer. The art
comes from :mod:`isofightr.ui.kit_art`, the text from :mod:`isofightr.ui.font`, the menu
model and input from :mod:`isofightr.ui.menu` and :mod:`isofightr.ui.focus`.

Two generations live here. :class:`TextBlock` and :meth:`UiLayer.label` use the old
fixed-width debug font and are what the screens not yet rebuilt in M13 draw with;
:class:`TextLabel` and the widgets below it use the game's real font.
"""

from collections.abc import Callable, Hashable, Sequence

import arcade
from arcade.types import RGBOrA255
from PIL import Image

from isofightr.config import NATIVE_W
from isofightr.render import placeholder_art as art
from isofightr.ui import font, kit_art, theme
from isofightr.ui.anim import pulse
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.icons import load_icons
from isofightr.ui.kit_art import Look
from isofightr.ui.pixel_font import GLYPH_ADVANCE, GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

WHITE = (255, 255, 255)
HIGHLIGHT = (255, 232, 96)
"""Text color of the row under a menu cursor."""
MUTED = (170, 180, 205)


def centred_left(characters: int, scale: int = 1, width: int = NATIVE_W) -> int:
    """Return the left edge that centres ``characters`` glyphs in ``width`` pixels."""
    return (width - characters * GLYPH_ADVANCE * scale) // 2


class TextBlock:
    """Several lines of text, each its own label, stacked downward from a top edge."""

    def __init__(
        self,
        layer: "UiLayer",
        left: int,
        top: int,
        rows: int,
        capacity: int,
        scale: int = 1,
        spacing: int = 2,
    ) -> None:
        """Create ``rows`` empty lines of up to ``capacity`` characters."""
        height = GLYPH_HEIGHT * scale + spacing
        self.left, self.top, self.row_height = left, top, height
        self.width = capacity * GLYPH_ADVANCE * scale
        self.labels = [
            layer.label(left, top - (row + 1) * height, capacity, scale=scale)
            for row in range(rows)
        ]

    def row_at(self, x: float, y: float) -> int | None:
        """Return the row under a point in native pixels, or ``None`` (mouse hover)."""
        if not self.left <= x < self.left + self.width or y >= self.top:
            return None
        row = int((self.top - y) // self.row_height)
        return row if row < len(self.labels) else None

    def set_lines(self, lines: Sequence[str], highlight: int | None = None) -> None:
        """Show ``lines`` (extra rows are cleared), tinting the row at ``highlight``."""
        for index, label in enumerate(self.labels):
            label.text = lines[index] if index < len(lines) else ""
            label.color = HIGHLIGHT if index == highlight else WHITE


class UiLayer:
    """One batched layer of UI sprites: panels first, then text on top of them."""

    def __init__(self, glyphs: GlyphAtlas, surface: theme.Surface = theme.INKED) -> None:
        """Create an empty layer that builds its text from ``glyphs``. ``surface`` is what
        its blocks are made of unless a widget says otherwise (decision D-072): stone for a
        menu, ink for anything over a match."""
        self.glyphs = glyphs
        self.surface = surface
        self.panels: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self.shadows: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        """The drop shadows of :class:`TextLabel` text: under the text, over the panels."""
        self.text: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._textures: dict[object, arcade.Texture] = {}

    def panel(
        self,
        left: int,
        bottom: int,
        width: int,
        height: int,
        fill: art.Rgba = art.PANEL_FILL,
        border: art.Rgba = art.PANEL_BORDER,
    ) -> arcade.Sprite:
        """Add a bordered rectangle and return its sprite."""
        key = ("panel", width, height, fill, border)
        texture = self._textures.get(key)
        if texture is None:
            texture = arcade.Texture(art.build_panel(width, height, fill, border))
            self._textures[key] = texture
        sprite = arcade.Sprite(texture, center_x=left + width / 2, center_y=bottom + height / 2)
        self.panels.append(sprite)
        return sprite

    def image(self, texture: arcade.Texture, left: int, bottom: int) -> arcade.Sprite:
        """Add a picture with its bottom-left corner at ``(left, bottom)``."""
        sprite = arcade.Sprite(
            texture, center_x=left + texture.width / 2, center_y=bottom + texture.height / 2
        )
        self.panels.append(sprite)
        return sprite

    def label(
        self, left: int, bottom: int, capacity: int, color: RGBOrA255 = WHITE, scale: int = 1
    ) -> PixelLabel:
        """Add an empty text label."""
        return PixelLabel(self.glyphs, self.text, left, bottom, capacity, color, scale)

    def centred(
        self, text: str, bottom: int, color: RGBOrA255 = WHITE, scale: int = 1
    ) -> PixelLabel:
        """Add a label showing ``text``, centred on the screen."""
        label = self.label(centred_left(len(text), scale), bottom, len(text), color, scale)
        label.text = text
        return label

    def picture(
        self, key: Hashable, build: Callable[[], Image.Image], left: int, bottom: int
    ) -> arcade.Sprite:
        """Add a piece of widget art with its bottom-left corner at ``(left, bottom)``.

        ``key`` names the image (its kind and every argument it was built from); ``build``
        is only called the first time a key is seen.
        """
        return self.image(picture_texture(key, build), left, bottom)

    def write(
        self,
        text: str,
        x: int,
        bottom: int,
        size: TextSize = TextSize.BODY,
        color: theme.Rgb | None = None,
        align: "Align" = "left",
        shadow: bool | None = None,
    ) -> "TextLabel":
        """Add a line of text in the game's font. See :class:`TextLabel`. Without a
        ``color`` it is the surface's text colour; without ``shadow`` it has the ink drop
        shadow only where the surface's text is light."""
        return TextLabel(self, x, bottom, text, size, *self._ink(color, shadow, align))

    def _ink(
        self, color: theme.Rgb | None, shadow: bool | None, align: "Align"
    ) -> tuple[theme.Rgb, "Align", bool]:
        """Fill in a label's colour and shadow from the layer's surface."""
        return (
            self.surface.text if color is None else color,
            align,
            self.surface.shadow if shadow is None else shadow,
        )

    def write_in(
        self,
        rect: Rect,
        text: str,
        size: TextSize = TextSize.BODY,
        color: theme.Rgb | None = None,
        align: "Align" = "centre",
        shadow: bool | None = None,
        pad: int = theme.PAD,
    ) -> "TextLabel":
        """Add a line of text inside a rectangle, its capitals centred vertically. The text
        never runs out of the rectangle: one that is too wide is shortened with ".."
        (``pad`` kept clear on both sides when centred, on its own side otherwise)."""
        x = {
            "left": rect.left + pad,
            "centre": rect.left + rect.width // 2,
            "right": rect.right - pad,
        }[align]
        room = rect.width - (2 * pad if align == "centre" else pad + min(pad, theme.PAD))
        label = TextLabel(
            self, x, text_bottom(rect, size), "", size, *self._ink(color, shadow, align)
        )
        label.max_width = max(room, 0)
        label.text = text
        return label

    def icon(
        self, name: str, left: int, bottom: int, color: theme.Rgb | None = None
    ) -> arcade.Sprite | None:
        """Add a UI icon in a colour (its white parts take it; the surface's text colour if
        none is given), or nothing if the icon sheet has no such icon."""
        texture = icon_texture(name, self.surface.text if color is None else color)
        return None if texture is None else self.image(texture, left, bottom)

    def draw(self) -> None:
        """Draw the layer. Call inside ``pixel_buffer.drawing()`` without a world camera."""
        self.panels.draw(pixelated=True)
        self.shadows.draw(pixelated=True)
        self.text.draw(pixelated=True)


# --- the game's font and the widgets built on it (decision D-061) --------------------------

type Align = str
"""``"left"``, ``"centre"`` or ``"right"``: which point of a line of text its ``x`` is."""
FOCUS_PULSE_TICKS = 48
"""The focus frame breathes between gold and pale gold over this many ticks."""
ICON_GAP = 4
BOX = arcade.hitbox.algo_bounding_box
"""UI textures need no traced outline: nothing collides with them."""
"""Space between a widget's icon and its caption."""

_pictures: dict[Hashable, arcade.Texture] = {}
_glyphs: dict[tuple[TextSize, str], arcade.Texture | None] = {}
_icons: dict[str, Image.Image] | None = None


def picture_texture(key: Hashable, build: Callable[[], Image.Image]) -> arcade.Texture:
    """Return the texture for a piece of widget art, building it the first time. Textures
    are shared by every layer and scene."""
    texture = _pictures.get(key)
    if texture is None:
        texture = arcade.Texture(build(), hash=f"ui:{key!r}", hit_box_algorithm=BOX)
        _pictures[key] = texture
    return texture


def icon_image(name: str) -> Image.Image | None:
    """Return a UI icon as packed (white, to be recoloured), or ``None`` if there is none."""
    global _icons
    if _icons is None:
        _icons = load_icons()
    return _icons.get(name)


def icon_texture(name: str, color: theme.Rgb = theme.TEXT) -> arcade.Texture | None:
    """Return a UI icon's texture in a colour, or ``None`` if there is no such icon."""
    image = icon_image(name)
    if image is None:
        return None
    return picture_texture(("icon", name, color), lambda: kit_art.tint(image, color))


def glyph_texture(character: str, size: TextSize) -> arcade.Texture | None:
    """Return one character's texture (white, no shadow), or ``None`` for a space."""
    key = (size, character)
    if key not in _glyphs:
        mask = font.mask(character, size)
        if character.isspace() or mask.getbbox() is None:
            _glyphs[key] = None
        else:
            image = Image.new("RGBA", mask.size, (0, 0, 0, 0))
            image.paste((255, 255, 255, 255), (0, 0), mask)
            _glyphs[key] = arcade.Texture(
                image, hash=f"glyph:{size.value}:{ord(character)}", hit_box_algorithm=BOX
            )
    return _glyphs[key]


def text_bottom(rect: Rect, size: TextSize) -> int:
    """Return the ``bottom`` that centres a line's capital letters vertically in a rect."""
    face = font.face(size)
    return rect.bottom + (rect.height - face.cap_height) // 2 - face.descent


class TextLabel:
    """A line of text in the game's font, anchored at ``x`` on its left, centre or right.

    ``bottom`` is the bottom of the line's box (descenders included). One sprite per
    character, re-textured only when the text changes, so a number that changes every tick
    costs nothing but texture swaps. The drop shadow is a second set of sprites in the
    layer's ``shadows`` list, so the text can be any colour and the shadow stays ink.
    """

    def __init__(
        self,
        layer: UiLayer,
        x: int,
        bottom: int,
        text: str = "",
        size: TextSize = TextSize.BODY,
        color: theme.Rgb = theme.TEXT,
        align: Align = "left",
        shadow: bool = True,
    ) -> None:
        """Create the label showing ``text``."""
        self._layer = layer
        self.x = x
        self.bottom = bottom
        self.size = size
        self.align = align
        self._shadow = shadow
        self._color = color
        self._text = ""
        self._visible = True
        self._alpha = 255
        self._ink: list[arcade.Sprite] = []
        self._under: list[arcade.Sprite] = []
        self._max_width: int | None = None
        self.text = text

    @property
    def max_width(self) -> int | None:
        """The widest the label may be drawn (``None``: any width). Text wider than this is
        shown shortened with ".." (:attr:`shown`); :attr:`text` keeps what was set."""
        return self._max_width

    @max_width.setter
    def max_width(self, value: int | None) -> None:
        if value != self._max_width:
            self._max_width = value
            self._layout()

    @property
    def shown(self) -> str:
        """The text as drawn: :attr:`text`, shortened if it is wider than
        :attr:`max_width`."""
        if self._max_width is None:
            return self._text
        return font.fit(self._text, self._max_width, self.size)

    @property
    def width(self) -> int:
        """The width of the text as drawn, in pixels."""
        return font.text_width(self.shown, self.size)

    @property
    def left(self) -> int:
        """The left edge of the current text."""
        if self.align == "centre":
            return self.x - self.width // 2
        if self.align == "right":
            return self.x - self.width
        return self.x

    @property
    def text(self) -> str:
        """The text shown."""
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        if value == self._text and self._ink:
            return
        self._text = value
        self._layout()

    @property
    def color(self) -> theme.Rgb:
        """The colour of the text."""
        return self._color

    @color.setter
    def color(self, value: theme.Rgb) -> None:
        if value == self._color:
            return
        self._color = value
        for sprite in self._ink:
            sprite.color = (*value, self._alpha)

    @property
    def shadow(self) -> bool:
        """Whether the text has the ink drop shadow (off for ink text on a light strip)."""
        return self._shadow

    @shadow.setter
    def shadow(self, value: bool) -> None:
        if value != self._shadow:
            self._shadow = value
            self._layout()

    @property
    def visible(self) -> bool:
        """Whether the label is drawn."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        if value != self._visible:
            self._visible = value
            self._layout()

    @property
    def alpha(self) -> int:
        """Opacity, 0 to 255 (fades)."""
        return self._alpha

    @alpha.setter
    def alpha(self, value: int) -> None:
        value = min(max(int(value), 0), 255)
        if value != self._alpha:
            self._alpha = value
            for sprite in self._ink:
                sprite.color = (*self._color, value)
            for sprite in self._under:
                sprite.color = (*theme.TEXT_SHADOW[:3], value)

    def move_to(self, x: int, bottom: int) -> None:
        """Move the label's anchor."""
        if (x, bottom) != (self.x, self.bottom):
            self.x, self.bottom = x, bottom
            self._layout()

    def _layout(self) -> None:
        """Place one sprite per visible character, growing the pool when the text does."""
        height = font.line_height(self.size)
        x = self.left
        used = 0
        for character in self.shown:
            advance = font.text_width(character, self.size)
            texture = glyph_texture(character, self.size) if self._visible else None
            if texture is not None:
                if used == len(self._ink):
                    self._grow(texture)
                centre = (x + texture.width / 2, self.bottom + height / 2)
                ink = self._ink[used]
                ink.texture = texture
                ink.position = centre
                ink.visible = True
                if self._shadow:
                    if used == len(self._under):
                        self._grow_shadow(texture)
                    under = self._under[used]
                    under.texture = texture
                    under.position = (
                        centre[0] + font.SHADOW_OFFSET,
                        centre[1] - font.SHADOW_OFFSET,
                    )
                    under.visible = True
                used += 1
            x += advance
        for index in range(used, len(self._ink)):
            self._ink[index].visible = False
        # Without a shadow (it can be turned off on a label already shown) none is drawn.
        for index in range(used if self._shadow else 0, len(self._under)):
            self._under[index].visible = False

    def _grow(self, texture: arcade.Texture) -> None:
        ink = arcade.Sprite(texture)
        ink.color = (*self._color, self._alpha)
        self._layer.text.append(ink)
        self._ink.append(ink)

    def _grow_shadow(self, texture: arcade.Texture) -> None:
        under = arcade.Sprite(texture)
        under.color = (*theme.TEXT_SHADOW[:3], self._alpha)
        self._layer.shadows.append(under)
        self._under.append(under)


class Picture:
    """A piece of widget art that can be swapped for another of the same size."""

    def __init__(self, layer: UiLayer, rect: Rect) -> None:
        """Create an empty, hidden picture filling ``rect``."""
        self.rect = rect
        self._key: Hashable = None
        self._sprite = arcade.Sprite(
            center_x=rect.left + rect.width / 2, center_y=rect.bottom + rect.height / 2
        )
        self._sprite.visible = False
        layer.panels.append(self._sprite)

    def show(self, key: Hashable, build: Callable[[], Image.Image]) -> None:
        """Show the art named ``key`` (built on first use)."""
        if key != self._key:
            self._key = key
            self._sprite.texture = picture_texture(key, build)
        self._sprite.visible = True

    def hide(self) -> None:
        """Stop drawing it."""
        self._sprite.visible = False

    @property
    def sprite(self) -> arcade.Sprite:
        """The sprite, for effects (alpha, position)."""
        return self._sprite


def add_panel(
    layer: UiLayer,
    rect: Rect,
    fill: theme.Rgba = theme.PANEL_FILL,
    border: theme.Rgba = theme.PANEL_BORDER,
    corner: int = theme.CORNER,
) -> arcade.Sprite:
    """Add a themed panel with angled corners."""
    return layer.picture(
        ("panel", rect.width, rect.height, fill, border, corner),
        lambda: kit_art.panel(rect.width, rect.height, fill, border, corner),
        rect.left,
        rect.bottom,
    )


def add_slab(
    layer: UiLayer,
    rect: Rect,
    surface: theme.Surface | None = None,
    corner: int = theme.CORNER,
    corners: kit_art.Corners = kit_art.TILE_CORNERS,
    lip: int = theme.LIP,
) -> arcade.Sprite:
    """Add a slab (decision D-072): the block a group of things sits on. ``rect`` is the
    whole block; its top face is everything above the bottom ``lip`` rows."""
    surface = surface or layer.surface
    return layer.picture(
        ("slab", rect.width, rect.height, surface.name, corner, corners, lip),
        lambda: kit_art.slab(rect.width, rect.height, surface, corner, corners, lip),
        rect.left,
        rect.bottom,
    )


def slab_face(rect: Rect, lip: int = theme.LIP) -> Rect:
    """Return a slab's top face: where things are laid out on it."""
    return Rect(rect.left, rect.bottom + lip, rect.width, rect.height - lip)


def add_plate(layer: UiLayer, rect: Rect, surface: theme.Surface | None = None) -> arcade.Sprite:
    """Add a header plate: a slab with turf along its top."""
    surface = surface or layer.surface
    return layer.picture(
        ("plate", rect.width, rect.height, surface.name),
        lambda: kit_art.plate(rect.width, rect.height, surface),
        rect.left,
        rect.bottom,
    )


PRESS_TICKS = 4
"""How long a pressed block stays sunk."""


class Button:
    """A captioned button, optionally with an icon on its left: a block (decision D-072).

    ``rect`` is the block at rest, lip included. Under the cursor its face stands
    ``theme.RAISE`` higher (the picture grows upward, past ``rect.top``); for
    :data:`PRESS_TICKS` after :meth:`press` it is sunk into its lip.
    """

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        caption: str,
        icon: str | None = None,
        size: TextSize = TextSize.BODY,
        look: Look = Look.NORMAL,
        align: Align = "centre",
        surface: theme.Surface | None = None,
    ) -> None:
        """Create the button in its resting look."""
        self.rect = rect
        self.rest = look
        """The look when the cursor is elsewhere (``NORMAL``, or ``CAUTION`` for DEFAULT)."""
        self.surface = surface or layer.surface
        self.size = size
        self._layer = layer
        self._body = arcade.Sprite()
        layer.panels.append(self._body)
        self._icon_name = icon if icon_image(icon or "") is not None else None
        self._icon: arcade.Sprite | None = None
        inset = theme.PAD + (theme.ICON_SIZE + ICON_GAP if self._icon_name else 0)
        if self._icon_name is not None:
            self._icon = arcade.Sprite(
                icon_texture(self._icon_name),
                center_x=rect.left + theme.PAD + theme.ICON_SIZE / 2,
                center_y=rect.bottom + rect.height / 2,
            )
            layer.panels.append(self._icon)
        self.label = layer.write_in(rect, caption, size, align=align, shadow=False, pad=inset)
        self._look: Look | None = None
        self._pressed_until = -1
        self._lift: int | None = None
        self._low = False
        self.look = look

    @property
    def look(self) -> Look:
        """How the button is shown right now."""
        assert self._look is not None
        return self._look

    @look.setter
    def look(self, value: Look) -> None:
        if value is self._look:
            return
        self._look = value
        self._show(pressed=False)

    @property
    def lift(self) -> int:
        """How far the face stands above (or, pressed, below) its resting place."""
        assert self._lift is not None
        return self._lift

    @property
    def face(self) -> Rect:
        """The button's top face as it stands now: where its caption is."""
        rows, tall = kit_art.face_span(self.rect.height, self.lift)
        return Rect(self.rect.left, self.rect.bottom + rows, self.rect.width, tall)

    @property
    def low(self) -> bool:
        """Whether the button lies sunk at rest, its caption second-rank: a tab that is not
        the page on show."""
        return self._low

    @low.setter
    def low(self, value: bool) -> None:
        if value != self._low:
            self._low = value
            self._show(pressed=False)

    def _show(self, pressed: bool) -> None:
        look = self.look
        lift = kit_art.lift_of(look, pressed or (self._low and look is Look.NORMAL))
        self._lift = lift
        width, height, surface = self.rect.width, self.rect.height, self.surface
        texture = picture_texture(
            ("block-button", width, height, look, surface.name, lift),
            lambda: kit_art.block_button(width, height, look, surface, lift),
        )
        self._body.texture = texture
        self._body.position = (
            self.rect.left + width / 2,
            self.rect.bottom + texture.height / 2,
        )
        face = self.face
        color = kit_art.look_text(look, surface)
        if self._low and look is Look.NORMAL:
            color = surface.text_muted
        self.label.color = color
        self.label.move_to(self.label.x, text_bottom(face, self.size))
        if self._icon is not None and self._icon_name is not None:
            texture = icon_texture(self._icon_name, color)
            assert texture is not None
            self._icon.texture = texture
            self._icon.center_y = face.bottom + face.height / 2

    def focus(self, focused: bool) -> None:
        """Show the button under the cursor, or back at rest. A button that overwrites
        things (``CAUTION`` at rest) turns red under the cursor instead of gold."""
        lit = Look.DANGER if self.rest is Look.CAUTION else Look.FOCUS
        self.look = lit if focused else self.rest

    def press(self, tick: int) -> None:
        """Sink the button for a few ticks: it was pressed on ``tick``. What the press
        does happens at once; this is only how it looks. Call :meth:`settle` every tick."""
        self._pressed_until = tick + PRESS_TICKS
        self._show(pressed=True)

    def settle(self, tick: int) -> None:
        """Let a pressed button come back up when its time is over."""
        if self._pressed_until >= 0 and tick >= self._pressed_until:
            self._pressed_until = -1
            self._show(pressed=False)

    @property
    def pressed(self) -> bool:
        """Whether the button is shown sunk right now."""
        return self._pressed_until >= 0


class BigButton:
    """A button with a caption and a line under it saying what it leads to: an entry of
    the main menu or of the options. A block like any other; its two lines ride its face."""

    CAPTION_UP = 19
    """Rows from the face's bottom to the caption's line box."""
    TEXT_UP = 5

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        caption: str,
        text: str,
        icon: str | None = None,
        surface: theme.Surface | None = None,
    ) -> None:
        """Create the button at rest."""
        self.rect = rect
        self.button = Button(layer, rect, "", icon, TextSize.TITLE, surface=surface)
        self.surface = self.button.surface
        left = rect.left + theme.PAD + (theme.ICON_SIZE + theme.PAD if icon else 0)
        self.caption = layer.write(caption, left, 0, TextSize.TITLE, shadow=False)
        self.text = layer.write(text, left, 0, TextSize.TEXT, shadow=False)
        self._shown: tuple[Look, int] | None = None
        self.focus(False)

    def focus(self, focused: bool) -> None:
        """Show the button under the cursor, or at rest."""
        self.button.focus(focused)
        self._place()

    def press(self, tick: int) -> None:
        """Sink the button for a few ticks (see :meth:`Button.press`)."""
        self.button.press(tick)
        self._place()

    def settle(self, tick: int) -> None:
        """Let a pressed button come back up."""
        self.button.settle(tick)
        self._place()

    def _place(self) -> None:
        look, lift = self.button.look, self.button.lift
        if (look, lift) == self._shown:
            return
        self._shown = (look, lift)
        face = self.button.face
        self.caption.color = kit_art.look_text(look, self.surface)
        self.caption.move_to(self.caption.x, face.bottom + self.CAPTION_UP)
        lit = look in (Look.FOCUS, Look.DANGER)
        self.text.color = kit_art.look_text(look, self.surface) if lit else self.surface.text_muted
        self.text.move_to(self.text.x, face.bottom + self.TEXT_UP)


class Toggle:
    """An ON/OFF switch."""

    ON_TEXT, OFF_TEXT = "ON", "OFF"

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        on: bool = False,
        surface: theme.Surface | None = None,
        block: bool = False,
    ) -> None:
        """Create the switch. With ``block`` it is a block (decision D-072): standing up
        and mint when on, sunk into its lip when off; without, the flat switch of D-061."""
        self.rect = rect
        self.surface = surface or layer.surface
        self.block = block
        self._body = Picture(layer, rect)
        self.label = layer.write_in(rect, "", TextSize.BODY, shadow=False, pad=0)
        self._state: tuple[bool, bool] | None = None
        self.set(on, False)

    def set(self, on: bool, focused: bool = False) -> None:
        """Show the switch on or off, with or without the cursor on it."""
        if (on, focused) == self._state:
            return
        self._state = (on, focused)
        width, height = self.rect.width, self.rect.height
        self.label.text = self.ON_TEXT if on else self.OFF_TEXT
        if not self.block:
            self._body.show(
                ("toggle", width, height, on, focused),
                lambda: kit_art.toggle(width, height, on, focused),
            )
            self.label.color = theme.TEXT_ON_FOCUS if on else theme.TEXT_MUTED
            return
        surface = self.surface
        self._body.show(
            ("toggle-block", width, height, on, focused, surface.name),
            lambda: kit_art.toggle_block(width, height, on, focused, surface),
        )
        rows, tall = kit_art.face_span(height, 0 if on else kit_art.lift_of(Look.NORMAL, True))
        face = Rect(self.rect.left, self.rect.bottom + rows, width, tall)
        self.label.color = kit_art.toggle_text(on, surface)
        self.label.move_to(self.label.x, text_bottom(face, TextSize.BODY))

    @property
    def on(self) -> bool:
        """Whether the switch shows ON."""
        return self._state is not None and self._state[0]


class Stepper:
    """A ``< value >`` chooser: a well with the value in it and an arrow at each end."""

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        text: str = "",
        surface: theme.Surface | None = None,
    ) -> None:
        """Create the stepper. On the stone surface its well is pale and its value ink."""
        self.rect = rect
        self.surface = surface or layer.surface
        self._body = Picture(layer, rect)
        middle = rect.bottom + (rect.height - theme.ICON_SIZE) // 2
        self._arrows = [
            Picture(layer, Rect(rect.left + 2, middle, theme.ICON_SIZE, theme.ICON_SIZE)),
            Picture(
                layer,
                Rect(rect.right - 2 - theme.ICON_SIZE, middle, theme.ICON_SIZE, theme.ICON_SIZE),
            ),
        ]
        self.label = layer.write_in(rect, text, TextSize.BODY, shadow=False, pad=0)
        # The value stays between the arrows at the ends.
        self.label.max_width = max(rect.width - 2 * (theme.ICON_SIZE + 2), 0)
        self._focused: bool | None = None
        self.set(text, False)

    def set(self, text: str, focused: bool = False) -> None:
        """Show a value, with or without the cursor on it."""
        self.label.text = text
        if focused == self._focused:
            return
        self._focused = focused
        width, height = self.rect.width, self.rect.height
        surface = self.surface
        if surface is theme.STONE:
            self._body.show(
                ("stepper-well", width, height, focused, surface.name),
                lambda: kit_art.well(width, height, surface, focused),
            )
            color = surface.text if focused else surface.text_dim
            self.label.color = surface.text
        else:
            self._body.show(
                ("stepper", width, height, focused),
                lambda: kit_art.stepper(width, height, focused),
            )
            color = theme.FOCUS if focused else theme.TEXT_DIM
            self.label.color = theme.TEXT if not focused else theme.FOCUS_GLOW
        for picture, name in zip(self._arrows, ("arrow_left", "arrow_right"), strict=True):
            image = icon_image(name)
            if image is None:
                picture.hide()
            else:
                picture.show(("icon", name, color), lambda image=image: kit_art.tint(image, color))


class Gauge:
    """A bar that fills from the left."""

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        value: float = 0.0,
        fill: theme.Rgb | theme.Rgba = theme.GAUGE_FILL,
        segmented: bool = False,
    ) -> None:
        """Create the bar filled to ``value`` (0 to 1)."""
        self.rect = rect
        self.fill = fill
        self.segmented = segmented
        self._body = Picture(layer, rect)
        self._value = -1.0
        self.value = value

    @property
    def value(self) -> float:
        """How full the bar is, 0 to 1."""
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        value = min(max(value, 0.0), 1.0)
        self._value = value
        width, height = self.rect.width, self.rect.height
        lit = round((width - 2) * value)
        self._body.show(
            ("gauge", width, height, lit, self.fill, self.segmented),
            lambda: kit_art.gauge(
                width, height, lit / max(width - 2, 1), self.fill, self.segmented
            ),
        )


class KeyCap:
    """A key cap or button tile: the control's name on a raised cap."""

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        caption: str = "",
        look: Look = Look.NORMAL,
        size: TextSize = TextSize.TITLE,
        surface: theme.Surface | None = None,
    ) -> None:
        """Create the cap."""
        self.rect = rect
        self.surface = surface or layer.surface
        self._body = Picture(layer, rect)
        face = Rect(
            rect.left, rect.bottom + kit_art.KEY_LIP, rect.width, rect.height - kit_art.KEY_LIP
        )
        self._sizes = (size, TextSize.BODY, TextSize.SMALL)
        self._face = face
        self._layer = layer
        self._labels = {
            each: layer.write_in(face, "", each, shadow=False, pad=0) for each in self._sizes
        }
        self._state: tuple[str, Look] | None = None
        self.set(caption, look)

    def set(self, caption: str, look: Look = Look.NORMAL) -> None:
        """Show a caption in a look. The caption is drawn in the biggest size that fits."""
        if (caption, look) == self._state:
            return
        self._state = (caption, look)
        width, height = self.rect.width, self.rect.height
        surface = self.surface
        self._body.show(
            ("key-block", width, height, look, surface.name),
            lambda: kit_art.block_button(width, height, look, surface, corners=kit_art.ALL_CORNERS),
        )
        room = width - 4
        chosen = next(
            (each for each in self._sizes if font.text_width(caption, each) <= room),
            self._sizes[-1],
        )
        for each, label in self._labels.items():
            label.text = font.fit(caption, room, each) if each is chosen else ""
            label.color = kit_art.look_text(look, surface)


class Tab:
    """One tab of a tab bar, in its own colour (a player's)."""

    def __init__(
        self, layer: UiLayer, rect: Rect, caption: str, color: theme.Rgb, active: bool = False
    ) -> None:
        """Create the tab."""
        self.rect = rect
        self.color = color
        self._body = Picture(layer, rect)
        self.label = layer.write_in(rect, caption, TextSize.TITLE, shadow=False, pad=0)
        self._active: bool | None = None
        self.active = active

    @property
    def active(self) -> bool:
        """Whether this is the tab being shown."""
        return bool(self._active)

    @active.setter
    def active(self, value: bool) -> None:
        if value == self._active:
            return
        self._active = value
        width, height, color = self.rect.width, self.rect.height, self.color
        self._body.show(
            ("tab", width, height, color, value), lambda: kit_art.tab(width, height, color, value)
        )
        self.label.color = theme.TEXT_ON_FOCUS if value else color


class Checkbox:
    """A tick box."""

    def __init__(self, layer: UiLayer, left: int, bottom: int, size: int = 11) -> None:
        """Create an empty box."""
        self.rect = Rect(left, bottom, size, size)
        self._body = Picture(layer, self.rect)
        self.set(False)

    def set(self, checked: bool, focused: bool = False) -> None:
        """Tick or clear the box."""
        size = self.rect.width
        self._body.show(
            ("checkbox", size, checked, focused), lambda: kit_art.checkbox(size, checked, focused)
        )


class FocusFrame:
    """The frame around whatever the cursor is on. It breathes, so the eye finds it."""

    def __init__(self, layer: UiLayer, grow: int = 2) -> None:
        """Create a hidden frame that sits ``grow`` pixels outside the rect it marks."""
        self.grow = grow
        self._sprite = arcade.Sprite()
        self._sprite.visible = False
        self._rect: Rect | None = None
        layer.text.append(self._sprite)

    def show(self, rect: Rect, tick: int = 0, color: theme.Rgb = theme.FOCUS) -> None:
        """Put the frame around ``rect``."""
        outer = rect.inset(-self.grow)
        if outer != self._rect:
            self._rect = outer
            width, height = outer.width, outer.height
            self._sprite.texture = picture_texture(
                ("focus", width, height), lambda: kit_art.focus_frame(width, height, theme.WHITE)
            )
            self._sprite.position = (outer.left + width / 2, outer.bottom + height / 2)
        glow = pulse(tick, FOCUS_PULSE_TICKS)
        other = theme.FOCUS_GLOW if color == theme.FOCUS else theme.WHITE
        self._sprite.color = other if glow > 0.5 else color
        self._sprite.visible = True

    def hide(self) -> None:
        """Hide the frame."""
        self._sprite.visible = False


class SlideGroup:
    """Everything added to a layer inside a ``with`` block, movable as one (a card that
    slides in from the side)::

        with SlideGroup(layer) as card:
            add_panel(layer, rect)
            layer.write("ROOK", ...)
        card.offset(-200, 0)   # off to the left; offset(0, 0) puts it back

    Text whose content changes after the block lays itself out again where it was made, so
    keep changing labels out of a group, or change them only while it rests.
    """

    def __init__(self, layer: UiLayer) -> None:
        """Remember what the layer holds so far."""
        self._lists = (layer.panels, layer.shadows, layer.text)
        self._before = [len(sprites) for sprites in self._lists]
        self._sprites: list[arcade.Sprite] = []
        self._home: list[tuple[float, float]] = []
        self._offset = (0, 0)

    def __enter__(self) -> "SlideGroup":
        """Start collecting."""
        self._before = [len(sprites) for sprites in self._lists]
        return self

    def __exit__(self, *exc: object) -> None:
        """Take every sprite added since, at its resting place."""
        for sprites, before in zip(self._lists, self._before, strict=True):
            self._sprites.extend(sprites[index] for index in range(before, len(sprites)))
        self._home = [(sprite.center_x, sprite.center_y) for sprite in self._sprites]

    def place(self, sprite: arcade.Sprite, x: float, y: float) -> None:
        """Give one of the group's sprites a new resting place (its centre); it keeps
        moving with the group from there."""
        index = self._sprites.index(sprite)
        self._home[index] = (x, y)
        sprite.position = (x + self._offset[0], y + self._offset[1])

    def offset(self, dx: int, dy: int) -> None:
        """Move the whole group ``(dx, dy)`` pixels from where it was made."""
        if (dx, dy) == self._offset:
            return
        self._offset = (dx, dy)
        for sprite, (x, y) in zip(self._sprites, self._home, strict=True):
            sprite.position = (x + dx, y + dy)


# --- the block kit's own widgets (decision D-072) ------------------------------------------

SIGN_LIP = 2
PROMPT_GAP = 12
"""Pixels between two prompts of a prompt bar."""
PROMPT_MIN_GAP = 5
PROMPT_CAP_GAP = 3
"""Pixels between a prompt's cap and its word."""
PROMPT_CAP_PAD = 4
"""Pixels of cap either side of a control's name."""


class Sign:
    """A line of help on a plate of its own: a note, not a button."""

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        text: str = "",
        surface: theme.Surface | None = None,
        size: TextSize = TextSize.TEXT,
    ) -> None:
        """Create the sign showing ``text`` (shortened if it is too wide)."""
        self.rect = rect
        self.size = size
        surface = surface or layer.surface
        layer.picture(
            ("sign", rect.width, rect.height, surface.name),
            lambda: kit_art.sign(rect.width, rect.height, surface),
            rect.left,
            rect.bottom,
        )
        face = Rect(rect.left, rect.bottom + SIGN_LIP, rect.width, rect.height - SIGN_LIP)
        self.label = layer.write_in(face, "", size, surface.text, shadow=False)
        self._line: str | None = None
        """The line last asked for, before shortening: fitting it again costs a font
        measurement, so an unchanged line is not."""
        self.text = text

    @property
    def text(self) -> str:
        """The line shown."""
        return self.label.text

    @text.setter
    def text(self, value: str) -> None:
        if value == self._line:
            return
        self._line = value
        self.label.text = font.fit(value, self.rect.width - 2 * theme.PAD, self.size)


class PipGauge:
    """A gauge that counts: a row of pips, some of them lit."""

    def __init__(
        self,
        layer: UiLayer,
        left: int,
        bottom: int,
        count: int,
        lit: int = 0,
        ramp: theme.Ramp = kit_art.GOLD_RAMP,
    ) -> None:
        """Create a row of ``count`` pips with the first ``lit`` lit."""
        self.count = count
        self.ramp = ramp
        self.rect = Rect(left, bottom, kit_art.pips_width(count), kit_art.PIP_SIZE[1])
        self._body = Picture(layer, self.rect)
        self._lit = -1
        self.lit = lit

    @property
    def lit(self) -> int:
        """How many pips are lit."""
        return self._lit

    @lit.setter
    def lit(self, value: int) -> None:
        value = min(max(int(value), 0), self.count)
        if value == self._lit:
            return
        self._lit = value
        count, ramp = self.count, self.ramp
        self._body.show(("pips", count, value, ramp), lambda: kit_art.pips(count, value, ramp))


class PromptBar:
    """A row of prompts: each a key cap (or a gamepad button) and a word or two.

    It shows a filled hint line such as ``"J: pick   K: back"`` (see
    :func:`isofightr.ui.hints.prompts`), so a screen still writes its hints as one template
    and a test still reads them as one string (:attr:`text`). A line with no controls in it
    (a message) is shown as plain text.
    """

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        surface: theme.Surface | None = None,
        strip: bool = True,
    ) -> None:
        """Create an empty bar centred in ``rect``. With ``strip`` it stands on a ledge of
        its surface that fills the rect."""
        from isofightr.ui.hints import prompts

        self._parse = prompts
        self.rect = rect
        self.surface = surface or layer.surface
        self._layer = layer
        self._ledge: arcade.Sprite | None = None
        """The stone tab the prompts stand on: as wide as they are (decision D-072), so
        the world shows either side of it."""
        if strip:
            self._ledge = arcade.Sprite()
            self._ledge.visible = False
            layer.panels.append(self._ledge)
        self._caps: list[arcade.Sprite] = []
        self._cap_labels: list[TextLabel] = []
        self._words: list[TextLabel] = []
        self._state: tuple[str, bool, theme.Rgb | None] | None = None
        self.set("")

    @property
    def text(self) -> str:
        """The hint line shown."""
        return self._state[0] if self._state is not None else ""

    @text.setter
    def text(self, value: str) -> None:
        self.set(value, self.pad, self.color)

    @property
    def pad(self) -> bool:
        """Whether controls are drawn as gamepad buttons."""
        return self._state is not None and self._state[1]

    @property
    def color(self) -> theme.Rgb | None:
        """The colour of the words (``None``: the surface's second-rank text colour)."""
        return self._state[2] if self._state is not None else None

    @color.setter
    def color(self, value: theme.Rgb | None) -> None:
        self.set(self.text, self.pad, value)

    def widths(self, text: str, pad: bool = False) -> list[tuple[int, int]]:
        """Return each prompt's ``(cap width, word width)`` for a line (0 = it has none)."""
        return [
            (self._cap_width(control, pad), font.text_width(words, TextSize.TEXT))
            for control, words in self._parse(text)
        ]

    @staticmethod
    def _disc(control: str, pad: bool) -> bool:
        return pad and control.upper() in kit_art.PAD_BUTTON_COLOURS

    def _cap_width(self, control: str, pad: bool) -> int:
        if not control:
            return 0
        if self._disc(control, pad):
            return kit_art.PAD_BUTTON
        return max(
            font.text_width(control, TextSize.BODY) + 2 * PROMPT_CAP_PAD, theme.PROMPT_HEIGHT
        )

    def set(self, text: str, pad: bool = False, color: theme.Rgb | None = None) -> None:
        """Show a hint line, with keyboard caps or (``pad``) gamepad buttons."""
        state = (text, pad, color)
        if state == self._state:
            return
        self._state = state
        items = self._parse(text)
        sizes = self.widths(text, pad)
        widths = [cap + (PROMPT_CAP_GAP if cap and word else 0) + word for cap, word in sizes]
        room = self.rect.width - 2 * theme.PAD
        gaps = max(len(items) - 1, 0)
        gap = PROMPT_GAP
        if gaps and sum(widths) + gap * gaps > room:
            gap = max((room - sum(widths)) // gaps, PROMPT_MIN_GAP)
        x = self.rect.left + (self.rect.width - sum(widths) - gap * gaps) // 2
        bottom = self.rect.bottom + (self.rect.height - theme.PROMPT_HEIGHT) // 2
        face = Rect(0, bottom + theme.PROMPT_LIP, 1, theme.PROMPT_HEIGHT - theme.PROMPT_LIP)
        surface = self.surface
        words_color = surface.text_muted if color is None else color
        used = 0
        for index, ((control, words), (cap, _)) in enumerate(zip(items, sizes, strict=True)):
            while index >= len(self._words):
                self._words.append(self._layer.write("", 0, 0, TextSize.TEXT, shadow=False))
            if control:
                if used == len(self._caps):
                    sprite = arcade.Sprite()
                    self._layer.panels.append(sprite)
                    self._caps.append(sprite)
                    self._cap_labels.append(
                        self._layer.write("", 0, 0, TextSize.BODY, align="centre", shadow=False)
                    )
                sprite, label = self._caps[used], self._cap_labels[used]
                if self._disc(control, pad):
                    sprite.texture = picture_texture(
                        ("pad-button", control.upper()),
                        lambda control=control: kit_art.pad_button(control),
                    )
                    label.color = kit_art.pad_button_text(control)
                    centre = Rect(0, bottom, 1, theme.PROMPT_HEIGHT)
                else:
                    sprite.texture = picture_texture(
                        ("prompt-cap", cap, surface.name),
                        lambda cap=cap: kit_art.block(
                            cap,
                            theme.PROMPT_HEIGHT,
                            kit_art.look_colours(Look.NORMAL, surface),
                            theme.PROMPT_LIP,
                            1,
                            kit_art.ALL_CORNERS,
                        ),
                    )
                    label.color = kit_art.look_text(Look.NORMAL, surface)
                    centre = face
                sprite.position = (x + cap / 2, bottom + theme.PROMPT_HEIGHT / 2)
                sprite.visible = True
                label.text = control
                label.move_to(x + cap // 2, text_bottom(centre, TextSize.BODY))
                used += 1
                x += cap + (PROMPT_CAP_GAP if words else 0)
            word = self._words[index]
            word.text = words
            word.color = words_color
            word.move_to(x, text_bottom(face, TextSize.TEXT))
            x += font.text_width(words, TextSize.TEXT) + gap
        for index in range(used, len(self._caps)):
            self._caps[index].visible = False
            self._cap_labels[index].text = ""
        for index in range(len(items), len(self._words)):
            self._words[index].text = ""
        self._fit_ledge()

    def _fit_ledge(self) -> None:
        """Size the ledge to what is shown, with a margin each side."""
        if self._ledge is None:
            return
        if not self.text:
            self._ledge.visible = False
            return
        margin = theme.MARGIN + 2
        left = max(self.left - margin, self.rect.left - 1)
        right = min(self.right + margin, self.rect.right + 1)
        width, height = right - left, self.rect.height + 1
        band = self.surface
        self._ledge.texture = picture_texture(
            ("prompt-ledge", width, height, band.name),
            lambda: kit_art.block(
                width,
                height,
                (band.face, band.light, band.lip, band.outline),
                0,
                theme.CORNER,
                (True, True, False, False),
            ),
        )
        self._ledge.position = (left + width / 2, self.rect.bottom - 1 + height / 2)
        self._ledge.visible = True

    @property
    def shown(self) -> list[tuple[str, str]]:
        """The prompts on show, as ``(control, words)``: what a player reads."""
        return self._parse(self.text)

    @property
    def right(self) -> int:
        """The right edge of the last thing drawn (tests: nothing runs off the bar)."""
        edges = [label.left + label.width for label in self._words if label.text]
        edges += [round(cap.right) for cap in self._caps if cap.visible]
        return max(edges, default=self.rect.left)

    @property
    def left(self) -> int:
        """The left edge of the first thing drawn."""
        edges = [label.left for label in self._words if label.text]
        edges += [round(cap.left) for cap in self._caps if cap.visible]
        return min(edges, default=self.rect.left)


TAB_GAP = 2


class TabStrip:
    """A row of block tabs, one of them the page on show (decision D-072).

    The page's tab stands up, pale; under the cursor (the strip is focused) it is the gold
    block. The others lie low. A tab's width follows its caption.
    """

    def __init__(
        self,
        layer: UiLayer,
        left: int,
        bottom: int,
        names: Sequence[str],
        height: int = theme.BUTTON_HEIGHT,
        surface: theme.Surface | None = None,
        size: TextSize = TextSize.TITLE,
    ) -> None:
        """Create the strip with its first tab on show."""
        self.names = tuple(names)
        self.rects: list[Rect] = []
        self._buttons: list[Button] = []
        x = left
        for name in self.names:
            width = font.text_width(name, size) + 2 * theme.PAD + 4
            rect = Rect(x, bottom, width, height)
            self.rects.append(rect)
            self._buttons.append(Button(layer, rect, name, size=size, surface=surface))
            x += width + TAB_GAP
        self.rect = Rect(left, bottom, x - TAB_GAP - left, height)
        self._state: tuple[int, bool] | None = None
        self.set(0, False)

    def set(self, active: int, focused: bool = False) -> None:
        """Show tab ``active`` as the page on show, with or without the cursor on the
        strip."""
        active = min(max(active, 0), len(self.names) - 1)
        if (active, focused) == self._state:
            return
        self._state = (active, focused)
        for index, button in enumerate(self._buttons):
            button.low = index != active
            button.look = Look.FOCUS if focused and index == active else Look.NORMAL

    @property
    def active(self) -> int:
        """The index of the page on show."""
        return self._state[0] if self._state is not None else 0

    @property
    def focused(self) -> bool:
        """Whether the cursor is on the strip."""
        return self._state is not None and self._state[1]

    def at(self, x: float, y: float) -> int | None:
        """Return the tab under a native pixel, or ``None`` (the mouse)."""
        for index, rect in enumerate(self.rects):
            if rect.contains(x, y):
                return index
        return None
