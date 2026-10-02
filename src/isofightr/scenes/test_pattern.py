"""Diagnostic view: the M0 pixel test pattern (``--test-pattern``).

Kept after M0 because it is the quickest way to check a display for scaling or DPI faults:
any blur in the 1 px blocks means the upscale is not a whole number.
"""

import arcade

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.test_pattern import build_marker, build_test_pattern, marker_center_native
from isofightr.scenes.ticked_view import TickedView


class TestPatternView(TickedView):
    """Draws the static test pattern plus a marker that moves 1 px per tick."""

    __test__ = False  # the name starts with "Test", but this is not a pytest class

    def __init__(self, pixel_buffer: PixelBuffer, max_ticks: int | None = None) -> None:
        """Build the pattern and marker sprites."""
        super().__init__(pixel_buffer, max_ticks)
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        pattern = arcade.Sprite(
            arcade.Texture(build_test_pattern()), center_x=NATIVE_W / 2, center_y=NATIVE_H / 2
        )
        self.marker = arcade.Sprite(arcade.Texture(build_marker()))
        self.sprites.append(pattern)
        self.sprites.append(self.marker)

    def on_draw(self) -> None:
        """Draw the pattern at native resolution, then upscale it to the window."""
        self.clear()
        self.marker.position = marker_center_native(self.tick_count)
        with self.pixel_buffer.drawing():
            self.sprites.draw(pixelated=True)
        self.blit_to_window()
