"""Tunable combat numbers (knockback, hitstun, hitlag, staling, DI...).

Plan note "05 - Combat Core". Combat tunables live here or in data files, never inline.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from typing import Final

# --- Damage --------------------------------------------------------------------------------
MAX_DAMAGE: Final[float] = 999.9
FRESH_BONUS: Final[float] = 1.05
"""Damage multiplier for a move that is not in the attacker's stale queue at all."""

# --- Knockback formula ---------------------------------------------------------------------
KB_WEIGHT_NUMERATOR: Final[float] = 200.0
KB_WEIGHT_OFFSET: Final[float] = 100.0
KB_SCALE: Final[float] = 1.4
KB_CONSTANT: Final[float] = 18.0
FIXED_KB_PERCENT: Final[float] = 10.0
"""Fixed-knockback hits use this as the target's percent, whatever it really is."""

HITSTUN_PER_KB: Final[float] = 0.4
TUMBLE_KB: Final[float] = 80.0
"""Knockback at or above this sends the target into tumble."""

PHYS_SCALE: Final[float] = 0.033
"""Converts Smash-unit knockback to world units. Calibrated so Rook's uncharged forward smash
KOs Rook at about 130% from the centre of Sky Ruins (see ``tools/kill_calc.py``)."""

LAUNCH_SPEED_PER_KB: Final[float] = 0.03 * PHYS_SCALE
"""Launch speed in units per frame, per point of knockback."""

KB_DECAY: Final[float] = 0.051 * PHYS_SCALE
"""Knockback speed lost per frame, along its own direction."""

LAUNCH_SELF_VELOCITY_KEEP: Final[float] = 0.5
"""Fraction of horizontal self velocity a fighter keeps when launched."""

HITSTUN_DRIFT_MULT: Final[float] = 0.5
"""Air drift acceleration multiplier while in hitstun."""

HITSTUN_GRAVITY_MULT: Final[float] = 0.4
"""Gravity and fall-speed multiplier while in hitstun. Blast zones here are much closer than
in Smash, so launches are slower (``PHYS_SCALE``); without this, gravity would flatten every
launch and nothing could KO off the top (decision D-029)."""

# --- Launch angle --------------------------------------------------------------------------
SAKURAI_ANGLE: Final[float] = 361.0
SAKURAI_MAX_DEGREES: Final[float] = 40.0
SAKURAI_KB_LOW: Final[float] = 60.0
"""Grounded targets below this knockback are sent horizontally by a Sakurai-angle hit."""
SAKURAI_KB_HIGH: Final[float] = 88.0
"""At and above this knockback a grounded target gets the full Sakurai angle."""
METEOR_BOUNCE_KB: Final[float] = 60.0
"""A downward hit on a grounded target pops it up; at this knockback or more it tumbles."""

# --- Hitlag, SDI, DI -----------------------------------------------------------------------
HITLAG_PER_DAMAGE: Final[float] = 0.65
HITLAG_BASE: Final[float] = 6.0
HITLAG_MAX: Final[int] = 30
ELECTRIC_HITLAG_MULT: Final[float] = 1.5
FULL_CHARGE_HITLAG_MULT: Final[float] = 1.2
SDI_DISTANCE: Final[float] = 0.06
"""How far one new stick input during hitlag nudges the target, in units."""
DI_MAX_DEGREES: Final[float] = 15.0

# --- Staling -------------------------------------------------------------------------------
STALE_QUEUE_LENGTH: Final[int] = 9
STALE_PENALTIES: Final[tuple[float, ...]] = (0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01)
"""Damage lost per queue slot holding the move, newest slot first."""

# --- Clanks --------------------------------------------------------------------------------
CLANK_DAMAGE_WINDOW: Final[float] = 9.0
"""Two clashing attacks both rebound when their damage differs by less than this."""
REBOUND_FRAMES: Final[int] = 20

# --- Move selection ------------------------------------------------------------------------
BACK_DOT: Final[float] = -0.38
"""Stick directions with a dot product against the facing below this count as "back"."""

# --- Knockdown -----------------------------------------------------------------------------
KNOCKDOWN_LOCK_FRAMES: Final[int] = 20
"""Frames a knocked-down fighter must lie still before any input gets it up."""
KNOCKDOWN_MAX_FRAMES: Final[int] = 60
"""A knocked-down fighter gets up by itself after this many frames."""
GETUP_FRAMES: Final[int] = 20
