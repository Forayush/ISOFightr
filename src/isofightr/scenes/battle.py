"""The battle scene. M0 stub: fixed-timestep loop driving the pixel test pattern.

Implements "Game loop: fixed 60 Hz simulation" in the plan note "02 - Technical
Architecture". From M2 on, :meth:`BattleView.tick` polls input, steps the ``Match`` and feeds
its events to the presentation layer; until then it only counts ticks so the loop, the
offscreen buffer and the integer upscale can be seen working.
"""

import arcade

from isofightr.config import NATIVE_H, NATIVE_W, TICK_RATE, WINDOW_TITLE
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.pixel_scale import ScaledViewport, integer_scale_viewport
from isofightr.render.test_pattern import build_marker, build_test_pattern, marker_center_native
from isofightr.timestep import FixedTimestep


class BattleView(arcade.View):
    """Runs the fixed 60 Hz loop and draws into the native-resolution buffer."""

    def __init__(self, pixel_buffer: PixelBuffer, max_ticks: int | None = None) -> None:
        """Create the view.

        Args:
            pixel_buffer: the window's shared native-resolution render target.
            max_ticks: close the window after this many ticks (``--frames``); ``None`` runs on.
        """
        super().__init__()
        self.pixel_buffer = pixel_buffer
        self.timestep = FixedTimestep()
        self.tick_count = 0
        self.max_ticks = max_ticks

        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        pattern = arcade.Sprite(
            arcade.Texture(build_test_pattern()), center_x=NATIVE_W / 2, center_y=NATIVE_H / 2
        )
        self.marker = arcade.Sprite(arcade.Texture(build_marker()))
        self.sprites.append(pattern)
        self.sprites.append(self.marker)

    def on_update(self, delta_time: float) -> None:
        """Convert the variable frame time into whole simulation ticks and run them."""
        for _ in range(self.timestep.advance(delta_time)):
            if self.max_ticks is not None and self.tick_count >= self.max_ticks:
                self.window.close()
                return
            self.tick()

    def tick(self) -> None:
        """Advance exactly one fixed simulation step."""
        self.tick_count += 1
        if self.tick_count % TICK_RATE == 0:
            scale = self._window_viewport().scale
            self.window.set_caption(f"{WINDOW_TITLE}  |  tick {self.tick_count}  |  {scale}x")

    def on_draw(self) -> None:
        """Draw the scene at native resolution, then upscale it to the window."""
        self.clear()
        self.marker.position = marker_center_native(self.tick_count)
        with self.pixel_buffer.drawing():
            self.sprites.draw(pixelated=True)
        self.pixel_buffer.blit(self.window.ctx.screen, self._window_viewport())

    def _window_viewport(self) -> ScaledViewport:
        """Where the upscaled buffer sits in the window, measured in real framebuffer pixels."""
        return integer_scale_viewport(*self.window.get_framebuffer_size())
