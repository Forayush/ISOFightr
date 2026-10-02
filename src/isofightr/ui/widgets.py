"""The drawing half of the UI widget kit: panels, labels and text blocks at native resolution.

Plan note "13 - Game Modes UI and Flow" ("UI implementation notes"): a tiny widget set
rendered at native resolution with the bitmap font, batched in one ``SpriteList`` per layer.
The menu model and input are in :mod:`isofightr.ui.menu`.
"""

from collections.abc import Sequence

import arcade
from arcade.types import RGBOrA255

from isofightr.config import NATIVE_W
from isofightr.render import placeholder_art as art
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
        self.labels = [
            layer.label(left, top - (row + 1) * height, capacity, scale=scale)
            for row in range(rows)
        ]

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

    def draw(self) -> None:
        """Draw the layer. Call inside ``pixel_buffer.drawing()`` without a world camera."""
        self.panels.draw(pixelated=True)
        self.text.draw(pixelated=True)
