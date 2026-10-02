"""The 640x360 offscreen framebuffer everything is drawn into, then upscaled to the window.

Implements "Native resolution and pixel-perfect scaling" in the plan note "03 - Isometric
World and Rendering": world and HUD render at native resolution, and the result is drawn to
the window scaled by a whole number with nearest-neighbor filtering, letterboxed.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import arcade
from arcade.gl import Framebuffer
from arcade.gl.geometry import quad_2d_fs
from arcade.types import LBWH, LRBT, RGBOrA255

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render.pixel_scale import ScaledViewport

_BLIT_VERTEX_SHADER = """
#version 330
in vec2 in_vert;
in vec2 in_uv;
out vec2 v_uv;

void main() {
    gl_Position = vec4(in_vert, 0.0, 1.0);
    v_uv = in_uv;
}
"""

# Alpha is forced to 1 so translucent sprites drawn into the buffer cannot let the window's
# letterbox color bleed through during the upscale.
_BLIT_FRAGMENT_SHADER = """
#version 330
uniform sampler2D native_buffer;
in vec2 v_uv;
out vec4 f_color;

void main() {
    f_color = vec4(texture(native_buffer, v_uv).rgb, 1.0);
}
"""

_NATIVE_BUFFER_TEXTURE_UNIT = 0


class PixelBuffer:
    """Native-resolution render target plus the nearest-neighbor blit that upscales it.

    Usage, once per drawn frame::

        with pixel_buffer.drawing():
            sprites.draw(pixelated=True)
        pixel_buffer.blit(window.ctx.screen, integer_scale_viewport(window.width, window.height))
    """

    def __init__(self, window: arcade.Window) -> None:
        ctx = window.ctx
        self._ctx = ctx
        self.texture = ctx.texture(
            (NATIVE_W, NATIVE_H),
            components=4,
            filter=(ctx.NEAREST, ctx.NEAREST),
            wrap_x=ctx.CLAMP_TO_EDGE,
            wrap_y=ctx.CLAMP_TO_EDGE,
        )
        self.framebuffer: Framebuffer = ctx.framebuffer(color_attachments=[self.texture])
        # Native coordinates: origin at the buffer's bottom-left corner, one unit per pixel.
        self.camera = arcade.Camera2D(
            viewport=LBWH(0, 0, NATIVE_W, NATIVE_H),
            position=(NATIVE_W / 2, NATIVE_H / 2),
            projection=LRBT(-NATIVE_W / 2, NATIVE_W / 2, -NATIVE_H / 2, NATIVE_H / 2),
            render_target=self.framebuffer,
            window=window,
        )
        self._quad = quad_2d_fs()
        self._program = ctx.program(
            vertex_shader=_BLIT_VERTEX_SHADER,
            fragment_shader=_BLIT_FRAGMENT_SHADER,
        )
        self._program["native_buffer"] = _NATIVE_BUFFER_TEXTURE_UNIT

    @contextmanager
    def drawing(self, clear_color: RGBOrA255 = arcade.color.BLACK) -> Iterator[None]:
        """Clear the native buffer and route all drawing inside the ``with`` block into it.

        The previously active framebuffer and camera are restored afterwards.
        """
        with self.camera.activate():
            self.framebuffer.clear(color=clear_color)
            yield

    def blit(self, target: Framebuffer, viewport: ScaledViewport) -> None:
        """Draw the native buffer into ``target`` at ``viewport`` with nearest-neighbor sampling.

        ``viewport`` comes from :func:`isofightr.render.pixel_scale.integer_scale_viewport`, in
        real pixels of the target. For the screen that relies on the window running with a
        pixel ratio of 1 (see the DPI note in :mod:`isofightr.app`).
        """
        target.use()
        previous_viewport = self._ctx.viewport
        self._ctx.viewport = viewport.lbwh
        try:
            self.texture.use(_NATIVE_BUFFER_TEXTURE_UNIT)
            self._quad.render(self._program)
        finally:
            self._ctx.viewport = previous_viewport
