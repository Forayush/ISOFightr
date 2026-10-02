"""Compile-time constants shared by the sim and the presentation layers.

Implements the "Configuration" section of the plan note "02 - Technical Architecture" and
the projection constants of "03 - Isometric World and Rendering". This module must stay free
of ``arcade`` and ``pyglet`` imports because ``isofightr.sim`` reads it.

User settings (``settings.toml``: window scale, fullscreen, volumes, bindings) arrive in M7.
"""

from typing import Final

# --- Simulation clock ---------------------------------------------------------------------
TICK_RATE: Final[int] = 60
"""Simulation ticks per second. All gameplay timing is counted in these frames."""

TICK_SECONDS: Final[float] = 1.0 / TICK_RATE
"""Wall-clock length of one simulation tick. Only the presentation loop may use it."""

MAX_FRAME_SECONDS: Final[float] = 0.25
"""Largest wall-clock step fed to the accumulator in one update (spiral-of-death clamp)."""

# --- Isometric projection (2:1 dimetric) --------------------------------------------------
TILE_W: Final[int] = 32
"""Width in native pixels of one tile's top diamond."""

TILE_H: Final[int] = 16
"""Height in native pixels of one tile's top diamond."""

Z_PX: Final[int] = 16
"""Native pixels per world unit of height."""

# --- Native resolution and window ---------------------------------------------------------
NATIVE_W: Final[int] = 640
"""Width of the offscreen pixel-art buffer."""

NATIVE_H: Final[int] = 360
"""Height of the offscreen pixel-art buffer."""

DEFAULT_WINDOW_SCALE: Final[int] = 2
"""Default integer upscale of the native buffer (2x = 1280x720)."""

MIN_WINDOW_SCALE: Final[int] = 1
"""Smallest integer upscale; also used when the window is smaller than the native buffer."""

WINDOW_TITLE: Final[str] = "ISOFightr"
