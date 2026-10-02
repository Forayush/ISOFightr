"""Sprite-based pixel text: one glyph sprite per character, batched in a ``SpriteList``.

Plan note "02 - Technical Architecture" (performance): draw through sprite lists, and never
recreate text objects per frame. A :class:`PixelLabel` owns a fixed number of glyph sprites
and only swaps their textures when its text changes.
"""

import arcade
from arcade.types import RGBOrA255

from isofightr.ui.pixel_font import GLYPH_ADVANCE, GLYPH_HEIGHT, GLYPH_WIDTH, PRINTABLE, build_glyph


class GlyphAtlas:
    """Glyph textures for every printable ASCII character, built once."""

    def __init__(self) -> None:
        self._textures = {
            character: arcade.Texture(build_glyph(character)) for character in PRINTABLE
        }

    def get(self, character: str) -> arcade.Texture | None:
        """Return the glyph texture, or ``None`` for spaces and unsupported characters."""
        return self._textures.get(character)


class PixelLabel:
    """A line of text whose left edge and baseline box start at ``(x, y)`` (bottom-left)."""

    def __init__(
        self,
        glyphs: GlyphAtlas,
        sprites: "arcade.SpriteList[arcade.Sprite]",
        x: int,
        y: int,
        capacity: int,
        color: RGBOrA255 = arcade.color.WHITE,
    ) -> None:
        """Create ``capacity`` hidden glyph sprites in ``sprites``, positioned left to right."""
        self._glyphs = glyphs
        self._text = ""
        self._sprites: list[arcade.Sprite] = []
        placeholder = glyphs.get(PRINTABLE[0])
        for _ in range(capacity):
            sprite = arcade.Sprite(placeholder)
            sprite.color = color
            sprite.visible = False
            sprites.append(sprite)
            self._sprites.append(sprite)
        self.move_to(x, y)

    def move_to(self, x: int, y: int) -> None:
        """Move the label so its bottom-left corner is at ``(x, y)``."""
        for index, sprite in enumerate(self._sprites):
            sprite.position = (
                x + index * GLYPH_ADVANCE + GLYPH_WIDTH / 2,
                y + GLYPH_HEIGHT / 2,
            )

    @property
    def text(self) -> str:
        """The text currently shown (truncated to the label's capacity)."""
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        value = value[: len(self._sprites)]
        if value == self._text:
            return
        self._text = value
        for index, sprite in enumerate(self._sprites):
            texture = self._glyphs.get(value[index]) if index < len(value) else None
            sprite.visible = texture is not None
            if texture is not None:
                sprite.texture = texture
