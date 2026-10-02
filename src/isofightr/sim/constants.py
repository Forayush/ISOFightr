"""Sim-wide tunables for input, movement, physics and match flow.

Plan notes "04 - Movement and Physics", "07 - Fighter State Machine and Move Data" and
"08 - Controls and Input". Per-character numbers live in ``fighter.toml``; the values here apply
to everyone. Combat tunables go in :mod:`isofightr.sim.combat.constants`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from typing import Final

# --- Input ---------------------------------------------------------------------------------
BUFFER_FRAMES: Final[int] = 6
"""A press stays usable for this many frames, counting the frame it happened on."""

STICK_NEUTRAL: Final[float] = 0.2
"""Stick magnitudes at or below this count as neutral inside the sim."""

FLICK_LOW: Final[float] = 0.25
"""A flick starts from a stick magnitude below this..."""

FLICK_HIGH: Final[float] = 0.8
"""...and reaches a magnitude above this..."""

FLICK_FRAMES: Final[int] = 3
"""...within this many frames (plan note 08, "Walk vs. dash")."""

# --- Ground movement -----------------------------------------------------------------------
TURN_FRAMES: Final[int] = 3
"""Length of a standing turnaround of more than 90 degrees."""

TURN_THRESHOLD_DEGREES: Final[float] = 90.0
"""Stick directions further than this from the facing need a turnaround; closer is instant."""

RUN_TURN_FRAMES: Final[int] = 12
"""Length of the skidding turnaround when reversing out of a run."""

RUN_TURN_TRACTION_MULT: Final[float] = 2.0
"""Traction multiplier while skidding through a run turnaround."""

PLATFORM_DROP_FRAMES: Final[int] = 3
"""Frames spent crouching before dropping through a soft platform."""

# --- Stage collision -----------------------------------------------------------------------
STEP_HEIGHT: Final[float] = 0.25
"""Height difference a grounded fighter walks up or down without jumping or falling."""

EDGE_TOLERANCE: Final[float] = 0.5
"""Fraction of the body radius the feet point may hang past an edge and still be supported."""

WALL_SKIN: Final[float] = 1e-6
"""Gap left between a fighter and a wall it is pressed against, so it never ends up inside."""

PLATFORM_DROP_CLEARANCE: Final[float] = 0.1
"""How far below a soft platform the feet must be before it can be landed on again."""

# --- Fighters pushing each other -----------------------------------------------------------
PUSH_SPEED: Final[float] = 0.01
"""How far each of two overlapping grounded fighters is nudged apart per frame, in units."""

PUSH_HEIGHT_TOLERANCE: Final[float] = 0.5
"""Fighters only push each other when their feet are within this height of each other."""

# --- KO and respawn ------------------------------------------------------------------------
RESPAWN_DELAY_FRAMES: Final[int] = 60
"""Frames between a KO and the fighter reappearing on the revival platform."""

REVIVAL_HEIGHT: Final[float] = 5.0
"""Height of the revival platform above the stage's respawn point."""

REVIVAL_MAX_FRAMES: Final[int] = 300
"""Longest a fighter may wait on the revival platform before it drops them."""

REVIVAL_SPACING: Final[float] = 1.5
"""Sideways spacing of revival platforms when several fighters respawn at once, in units."""

RESPAWN_INVINCIBLE_FRAMES: Final[int] = 120
"""Invincibility after leaving the revival platform."""

DEFAULT_STOCKS: Final[int] = 3
"""Stocks per fighter in a stock match."""

# --- Match flow ------------------------------------------------------------------------------
COUNTDOWN_FRAMES: Final[int] = 180
"""Length of the "3, 2, 1" countdown before a match starts (one second per number)."""

DEFAULT_TIME_MINUTES: Final[int] = 3
FRAMES_PER_MINUTE: Final[int] = 3600

SUDDEN_DEATH_DAMAGE: Final[float] = 300.0
"""Damage every fighter starts a sudden death on."""

KO_CREDIT_FRAMES: Final[int] = 480
"""A KO is credited to the last fighter that hit the victim within this many frames;
otherwise it is a self-destruct."""
