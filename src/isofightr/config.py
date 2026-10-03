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

# --- Input devices (plan note "08 - Controls and Input", "Analog processing") --------------
STICK_DEADZONE: Final[float] = 0.20
"""Radial deadzone: stick magnitudes at or below this read as zero."""

STICK_SATURATION: Final[float] = 0.95
"""Stick magnitudes at or above this read as fully pushed."""

MODIFIER_THRESHOLD: Final[float] = 0.5
"""How far the right stick must be pushed up or down to act as the up or down modifier."""

TRIGGER_THRESHOLD: Final[float] = 0.5
"""How far an analog trigger must be pulled to count as held."""

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

# --- Stage geometry shared by physics, the depth sorter and the tile art -------------------
ISLAND_THICKNESS: Final[float] = 1.0
"""How far the island extends below its lowest cell top, in units. Solid for physics too:
fighters can pass under the island below this depth."""

DECK_THICKNESS: Final[float] = 0.25
"""Visual thickness of a soft platform deck, in units (4 px)."""

# --- Camera ---------------------------------------------------------------------------------
CAMERA_LERP: Final[float] = 0.1
"""Fraction of the remaining distance the camera pans toward its target each tick."""
CAMERA_ZOOM_STEP: Final[int] = 2
"""Stepped zoom (an M8 experiment, decision D-048): the world is drawn at 1x or exactly 2x."""
CAMERA_ZOOM_MARGIN: Final[int] = 56
"""Room kept around the fighters, in native pixels, when deciding whether 2x still fits."""
CAMERA_ZOOM_IN_TICKS: Final[int] = 45
"""How long everyone must fit the zoomed view before the camera zooms in."""

# --- Fighter presentation -------------------------------------------------------------------
OCCLUDED_FIGHTER_ALPHA: Final[int] = 96
"""Opacity (0-255) of the "x-ray" copy of each fighter drawn over the world, so a fighter
behind a platform or the island stays visible. 0 turns it off (decision D-025)."""

INVINCIBLE_BLINK_FRAMES: Final[int] = 4
"""An invincible fighter's sprite is hidden for this many frames, then shown for as many."""

# --- Match defaults -------------------------------------------------------------------------
DEFAULT_STAGE_ID: Final[str] = "sky_ruins"
"""Stage loaded when ``--stage`` is not given."""

TRAINING_STAGE_ID: Final[str] = "training_grid"
"""Stage loaded for ``--training`` when ``--stage`` is not given."""

DEFAULT_CHARACTER_ID: Final[str] = "rook"
"""Character used for a player slot when ``--p1``/``--p2`` are not given."""

DEFAULT_PLAYER_COUNT: Final[int] = 2
"""Players in a match started from the command line without ``--p3``/``--p4``."""

MAX_PLAYERS: Final[int] = 4

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
