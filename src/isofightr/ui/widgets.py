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

    def __init__(self, glyphs: GlyphAtlas) -> None:
        """Create an empty layer that builds its text from ``glyphs``."""
        self.glyphs = glyphs
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
        color: theme.Rgb = theme.TEXT,
        align: "Align" = "left",
        shadow: bool = True,
    ) -> "TextLabel":
        """Add a line of text in the game's font. See :class:`TextLabel`."""
        return TextLabel(self, x, bottom, text, size, color, align, shadow)

    def write_in(
        self,
        rect: Rect,
        text: str,
        size: TextSize = TextSize.BODY,
        color: theme.Rgb = theme.TEXT,
        align: "Align" = "centre",
        shadow: bool = True,
        pad: int = theme.PAD,
    ) -> "TextLabel":
        """Add a line of text inside a rectangle, its capitals centred vertically."""
        x = {
            "left": rect.left + pad,
            "centre": rect.left + rect.width // 2,
            "right": rect.right - pad,
        }[align]
        return TextLabel(self, x, text_bottom(rect, size), text, size, color, align, shadow)

    def icon(
        self, name: str, left: int, bottom: int, color: theme.Rgb = theme.TEXT
    ) -> arcade.Sprite | None:
        """Add a UI icon in a colour (its white parts take it), or nothing if the icon sheet
        has no such icon."""
        texture = icon_texture(name, color)
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
        self.text = text

    @property
    def width(self) -> int:
        """The width of the current text in pixels."""
        return font.text_width(self._text, self.size)

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
        for character in self._text:
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
            if self._shadow:
                self._under[index].visible = False

    def _grow(self, texture: arcade.Texture) -> None:
        ink = arcade.Sprite(texture)
        ink.color = (*self._color, self._alpha)
        self._layer.text.append(ink)
        self._ink.append(ink)
        if self._shadow:
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


class Button:
    """A captioned button, optionally with an icon on its left."""

    def __init__(
        self,
        layer: UiLayer,
        rect: Rect,
        caption: str,
        icon: str | None = None,
        size: TextSize = TextSize.BODY,
        look: Look = Look.NORMAL,
        align: Align = "centre",
    ) -> None:
        """Create the button in its resting look."""
        self.rect = rect
        self.rest = look
        """The look when the cursor is elsewhere (``NORMAL``, or ``DANGER`` for DEFAULT)."""
        self._layer = layer
        self._body = Picture(layer, rect)
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
        width, height = self.rect.width, self.rect.height
        self._body.show(
            ("button", width, height, value), lambda: kit_art.button(width, height, value)
        )
        color = kit_art.text_color(value)
        self.label.color = color
        if self._icon is not None and self._icon_name is not None:
            texture = icon_texture(self._icon_name, color)
            assert texture is not None
            self._icon.texture = texture

    def focus(self, focused: bool) -> None:
        """Show the button under the cursor, or back at rest."""
        self.look = Look.FOCUS if focused else self.rest


class Toggle:
    """An ON/OFF switch."""

    ON_TEXT, OFF_TEXT = "ON", "OFF"

    def __init__(self, layer: UiLayer, rect: Rect, on: bool = False) -> None:
        """Create the switch."""
        self.rect = rect
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
        self._body.show(
            ("toggle", width, height, on, focused),
            lambda: kit_art.toggle(width, height, on, focused),
        )
        self.label.text = self.ON_TEXT if on else self.OFF_TEXT
        self.label.color = theme.TEXT_ON_FOCUS if on else theme.TEXT_MUTED

    @property
    def on(self) -> bool:
        """Whether the switch shows ON."""
        return self._state is not None and self._state[0]


class Stepper:
    """A ``< value >`` chooser: a well with the value in it and an arrow at each end."""

    def __init__(self, layer: UiLayer, rect: Rect, text: str = "") -> None:
        """Create the stepper."""
        self.rect = rect
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
        self._focused: bool | None = None
        self.set(text, False)

    def set(self, text: str, focused: bool = False) -> None:
        """Show a value, with or without the cursor on it."""
        self.label.text = text
        if focused == self._focused:
            return
        self._focused = focused
        width, height = self.rect.width, self.rect.height
        self._body.show(
            ("stepper", width, height, focused), lambda: kit_art.stepper(width, height, focused)
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
    ) -> None:
        """Create the cap."""
        self.rect = rect
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
        self._body.show(("key", width, height, look), lambda: kit_art.key_cap(width, height, look))
        room = width - 4
        chosen = next(
            (each for each in self._sizes if font.text_width(caption, each) <= room),
            self._sizes[-1],
        )
        for each, label in self._labels.items():
            label.text = font.fit(caption, room, each) if each is chosen else ""
            label.color = kit_art.text_color(look)


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
