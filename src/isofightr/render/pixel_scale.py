"""Integer-scale and letterbox maths for drawing the native buffer into a window.

Implements "Native resolution and pixel-perfect scaling" in the plan note "03 - Isometric
World and Rendering". Pure Python (no ``arcade``) so it can be unit tested without a window.
"""

from dataclasses import dataclass

from isofightr.config import MIN_WINDOW_SCALE, NATIVE_H, NATIVE_W


@dataclass(frozen=True, slots=True)
class ScaledViewport:
    """Where the upscaled native buffer sits inside a window, in window pixels.

    ``left`` and ``bottom`` are measured from the window's bottom-left corner. They go negative
    when the window is smaller than the native buffer, which crops the image evenly.
    """

    scale: int
    left: int
    bottom: int
    width: int
    height: int

    @property
    def lbwh(self) -> tuple[int, int, int, int]:
        """The viewport as ``(left, bottom, width, height)``, the order OpenGL expects."""
        return (self.left, self.bottom, self.width, self.height)


def integer_scale_viewport(
    window_width: int,
    window_height: int,
    native_width: int = NATIVE_W,
    native_height: int = NATIVE_H,
) -> ScaledViewport:
    """Return the largest whole-number upscale that fits the window, centered (letterboxed).

    Whole-number scaling with nearest-neighbor sampling is what keeps pixel art crisp: every
    native pixel becomes an exact ``scale x scale`` block.
    """
    scale = max(MIN_WINDOW_SCALE, min(window_width // native_width, window_height // native_height))
    width = native_width * scale
    height = native_height * scale
    return ScaledViewport(
        scale=scale,
        left=(window_width - width) // 2,
        bottom=(window_height - height) // 2,
        width=width,
        height=height,
    )
