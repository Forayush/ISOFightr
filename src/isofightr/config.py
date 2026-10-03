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

# --- CPU AI (plan note "15 - CPU AI") ------------------------------------------------------
# Per-level parameters are given at the plan's anchor levels 1, 3, 5, 7 and 9; the even
# levels sit halfway between their neighbours (``isofightr.ai.levels``).
CPU_MIN_LEVEL: Final[int] = 1
CPU_MAX_LEVEL: Final[int] = 9
CPU_DEFAULT_LEVEL: Final[int] = 5
CPU_LEVEL_ANCHORS: Final[tuple[int, ...]] = (1, 3, 5, 7, 9)
CPU_REACTION_FRAMES: Final[tuple[float, ...]] = (40, 28, 18, 12, 7)
"""How old the CPU's view of its opponents is, in frames."""
CPU_DECISION_FRAMES: Final[tuple[float, ...]] = (30, 20, 12, 8, 4)
"""How often a CPU in neutral picks a new plan, in frames."""
CPU_DEFEND_CHANCE: Final[tuple[float, ...]] = (0.05, 0.20, 0.40, 0.60, 0.80)
"""Chance to shield or dodge an attack it sees coming."""
CPU_DI_QUALITY: Final[tuple[float, ...]] = (0.0, 0.2, 0.5, 0.8, 1.0)
"""Chance to DI a launch toward survival (otherwise it holds nothing)."""
CPU_TECH_CHANCE: Final[tuple[float, ...]] = (0.0, 0.15, 0.40, 0.70, 0.90)
CPU_AIM_JITTER_DEGREES: Final[tuple[float, ...]] = (40.0, 22.0, 10.0, 4.0, 0.0)
"""Random error added to every direction the CPU aims."""
CPU_AGGRESSION: Final[tuple[float, ...]] = (0.25, 0.45, 0.65, 0.85, 0.95)
"""Chance to attack when one of its moves reaches the target."""
CPU_PREDICTION: Final[tuple[float, ...]] = (0.0, 0.3, 0.6, 0.85, 1.0)
"""Share of its reaction delay the CPU makes up for by extrapolating the target's motion."""
CPU_EDGEGUARD_CHANCE: Final[tuple[float, ...]] = (0.0, 0.0, 0.4, 0.8, 1.0)
"""Chance to go and guard the ledge while the target recovers."""
CPU_RECOVERY_MIXUP: Final[tuple[float, ...]] = (0.0, 0.0, 0.4, 0.6, 0.8)
"""Chance to vary recovery timing (jump late, up special early) instead of the plain route."""
CPU_LEDGE_WAIT_MAX: Final[tuple[float, ...]] = (10, 20, 35, 45, 50)
"""Longest the CPU waits on a ledge before picking an option, in frames."""
CPU_MASH_EVERY: Final[tuple[float, ...]] = (8, 6, 4, 3, 2)
"""Frames between presses while mashing out of a grab."""
CPU_PUNISH_MARGIN: Final[tuple[float, ...]] = (0, 1, 2, 3, 4)
"""Frames of an opponent's end lag the CPU leaves spare when it picks a punish."""

CPU_HIT_SLACK: Final[float] = -0.1
"""Units added to hitbox reach when the CPU judges whether a move will connect: negative, so
it only counts on hits with some overlap to spare (a borderline swing would whiff forever)."""
CPU_THREAT_SLACK: Final[float] = 0.15
"""Units added to an opponent's hitbox reach when the CPU judges whether it is in danger."""
CPU_THREAT_FRAMES: Final[int] = 8
"""How far ahead the CPU looks for hitboxes and projectiles that will reach it."""
CPU_CLOSE_RANGE: Final[float] = 1.4
"""Distance a brawler tries to keep from its target."""
CPU_ZONER_RANGE: Final[float] = 4.5
"""Distance a character with a long-range projectile tries to keep."""
CPU_ZONER_REACH: Final[float] = 8.0
"""A projectile that hits this far away makes its character a zoner."""
CPU_ZONER_HEIGHT: Final[float] = 1.0
"""A zoner only keeps its distance from a target at about its own height."""
CPU_WALK_RANGE: Final[float] = 2.5
"""Closer than this the CPU walks instead of dashing."""
CPU_WALK_TILT: Final[float] = 0.55
CPU_TURN_TILT: Final[float] = 0.3
"""A light push behind the CPU: enough to turn around without walking off."""
CPU_EDGE_LOOKAHEAD: Final[float] = 0.9
"""How far ahead of its feet a grounded CPU checks for ground before moving on."""
CPU_STEP_HEIGHT: Final[float] = 0.4
"""A height difference the CPU treats as level ground (anything more needs a jump)."""
CPU_REGION_SNAP: Final[float] = 0.75
"""A fighter belongs to a region if one of its cell centres is this close (per axis)."""
CPU_JUMP_REACH_SHARE: Final[float] = 0.6
"""Share of its full-hop-plus-air-jump distance a CPU counts on when planning a jump."""
CPU_JUMP_RISE_SHARE: Final[float] = 0.7
"""Share of its full-hop-plus-air-jump height a CPU counts on when planning a jump."""
CPU_ROUTE_HEIGHT_COST: Final[float] = 0.5
"""Route cost of a unit of height, against a unit of distance."""
CPU_TAKEOFF_RADIUS: Final[float] = 0.4
"""How close to a route's takeoff point the CPU gets before it jumps."""
CPU_SAFE_INSET: Final[float] = 0.8
"""How far inside a ledge the CPU stands when its target is off the stage."""
CPU_LEDGE_APPROACH_OUT: Final[float] = 0.3
"""While below a ledge, the CPU aims this far outside it so it does not slide under."""
CPU_LEDGE_APPROACH_IN: Final[float] = 0.8
"""Once level with a ledge, the CPU aims this far inside it to land on the stage."""
CPU_DESTINATION_BIAS: Final[float] = 0.6
"""Weight of "toward where I am going" against "nearest" when picking a ledge to recover to."""
CPU_UPSPECIAL_SAFETY: Final[float] = 0.7
"""Share of its up special's measured rise the CPU counts on when deciding to use it."""
CPU_SHIELD_HOLD_EXTRA: Final[int] = 4
"""Frames the CPU keeps its shield up after the threat it saw has passed."""
CPU_GETUP_MIN_LOCK: Final[int] = 2
CPU_KILL_HEADROOM: Final[float] = 1.0
"""A launch that would carry the target this many units short of the blast zone still counts
as a KO (it keeps flying a little after its knockback runs out)."""
CPU_SOFTLOCK_FRAMES: Final[int] = 20 * 60
"""The soak test's soft-lock limit: no fighter may stay in one state longer than this."""

# --- Audio (plan note "14 - Audio") ----------------------------------------------------------
AUDIO_HIT_TIERS: Final[tuple[float, float, float]] = (40.0, 80.0, 120.0)
"""Knockback at which a hit sounds medium, heavy and KO-level."""
AUDIO_HEAVY_LANDING_SPEED: Final[float] = 0.2
"""A landing at this fall speed or more (units per frame) uses the heavy landing sound."""
AUDIO_PITCH_VARIATION: Final[float] = 0.05
"""Repeated sounds are played up to this much faster or slower, so they do not machine-gun."""
AUDIO_MAX_PAN: Final[float] = 0.5
"""Stereo pan of a sound at the edge of the screen."""
AUDIO_MAX_INSTANCES: Final[int] = 3
"""How many copies of one sound may start within ``AUDIO_INSTANCE_TICKS``."""
AUDIO_INSTANCE_TICKS: Final[int] = 6
AUDIO_DUCK_VOLUME: Final[float] = 0.5
"""Music volume factor while ducked (about -6 dB), on KOs and at "GAME!"."""
AUDIO_DUCK_TICKS: Final[int] = 70
AUDIO_MENU_SONG: Final[str] = "menu"
AUDIO_VICTORY_SONG: Final[str] = "victory"
