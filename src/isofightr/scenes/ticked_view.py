"""Base view that turns variable frame time into fixed 60 Hz ticks.

Implements "Game loop: fixed 60 Hz simulation" in the plan note "02 - Technical
Architecture". Subclasses put everything that advances the game in :meth:`TickedView.tick`.
"""

import arcade

from isofightr.audio.sound_director import SoundDirector
from isofightr.config import TICK_RATE, WINDOW_TITLE
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.pixel_scale import ScaledViewport, integer_scale_viewport
from isofightr.timestep import FixedTimestep


class TickedView(arcade.View):
    """A view driven by the fixed-timestep accumulator, drawing into the native buffer."""

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
        self._silent = SoundDirector()

    def on_update(self, delta_time: float) -> None:
        """Convert the variable frame time into whole ticks and run them."""
        for _ in range(self.timestep.advance(delta_time)):
            if self.max_ticks is not None and self.tick_count >= self.max_ticks:
                self.window.close()
                return
            self.tick_count += 1
            self.tick()
            self.audio.tick()
            if self.tick_count % TICK_RATE == 0:
                self.window.set_caption(self.caption())

    def tick(self) -> None:
        """Advance exactly one fixed step. Override in subclasses."""

    @property
    def audio(self) -> SoundDirector:
        """The window's sound director (a silent one if the window has none)."""
        director = getattr(self.window, "audio", None)
        if director is None:
            director = self._silent
        return director  # type: ignore[no-any-return]

    def caption(self) -> str:
        """Return the window title, refreshed once per second of ticks."""
        scale = self.window_viewport().scale
        return f"{WINDOW_TITLE}  |  tick {self.tick_count}  |  {scale}x"

    def window_viewport(self) -> ScaledViewport:
        """Where the upscaled buffer sits in the window, measured in real framebuffer pixels."""
        return integer_scale_viewport(*self.window.get_framebuffer_size())

    def blit_to_window(self) -> None:
        """Upscale the native buffer onto the window."""
        self.pixel_buffer.blit(self.window.ctx.screen, self.window_viewport())
