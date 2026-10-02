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

# --- Input ---------------------------------------------------------------------------------
FACING_HYSTERESIS_DEGREES: Final[float] = 5.0
"""Extra angle the stick must travel past a 45-degree boundary before 8-way facing changes."""

# --- Stage defaults (used when a stage.toml omits the value) -------------------------------
LEDGE_MIN_DROP: Final[float] = 2.0
"""A solid neighbour lower by more than this many units still leaves a grabbable ledge."""

DEFAULT_BLAST_SIDE: Final[float] = 7.0
"""Horizontal blast-zone margin beyond the stage's solid bounding box, in units."""

DEFAULT_BLAST_TOP: Final[float] = 14.0
"""Height of the top blast zone, in units above the main floor."""

DEFAULT_BLAST_BOTTOM: Final[float] = -8.0
"""Height of the bottom blast zone, in units (negative = below the main floor)."""

DEFAULT_CAMERA_MARGIN: Final[float] = 4.0
"""How far beyond the stage's solid bounding box the camera may look, in units."""

MIN_PLATFORM_CLEARANCE: Final[float] = 1.0
"""A soft platform must sit at least this far above every solid cell beneath it, in units."""

SURFACE_EPSILON: Final[float] = 1e-4
"""Height tolerance when deciding whether something is on, above or below a surface."""

PLAYER_SPAWN_COUNT: Final[int] = 4
"""Every stage defines spawn points ``p1`` to ``p4``."""

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
