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

# --- Shield (plan note 06) -----------------------------------------------------------------
SHIELD_MAX_HP: Final[float] = 50.0
SHIELD_DECAY: Final[float] = 0.15
"""Shield HP lost per frame while the shield is up."""
SHIELD_REGEN: Final[float] = 0.08
"""Shield HP regained per frame while it is down."""
SHIELD_MIN_FRAMES: Final[int] = 3
"""A shield stays up at least this long, however briefly the button was pressed."""
SHIELD_DROP_FRAMES: Final[int] = 11
SHIELD_MIN_SIZE: Final[float] = 0.4
"""Fraction of its full radius the shield sphere keeps at 0 HP; it grows linearly with HP."""
SHIELD_CENTRE_HEIGHT: Final[float] = 1.25
"""Height of the shield sphere's centre above the feet, in units."""
SHIELD_DAMAGE_MULT: Final[float] = 1.19
SHIELDSTUN_PER_DAMAGE: Final[float] = 0.8 * 0.725
SHIELDSTUN_BASE: Final[float] = 2.0
SHIELD_PUSH_PER_DAMAGE: Final[float] = 0.004
"""Speed the defender slides back per point of blocked damage, in units per frame."""
SHIELD_PUSH_MAX: Final[float] = 0.09
SHIELD_ATTACKER_PUSH: Final[float] = 0.4
"""Fraction of the defender's pushback a grounded attacker gets, the other way."""
SHIELD_BREAK_POP: Final[float] = 0.34
"""Upward speed of a fighter whose shield just broke."""
SHIELD_BREAK_HP: Final[float] = 0.3 * SHIELD_MAX_HP
"""Shield HP right after a break."""
DIZZY_BASE_FRAMES: Final[int] = 400
DIZZY_MIN_FRAMES: Final[int] = 90
"""Dizzy lasts ``max(DIZZY_MIN_FRAMES, DIZZY_BASE_FRAMES - damage)`` frames."""
PARRY_WINDOW: Final[int] = 5
"""With the parry rule on: a hit in the first frames of dropping shield is parried."""
PARRY_EXTRA_HITLAG: Final[int] = 14
"""Extra frames the attacker is frozen after being parried."""

# --- Dodges --------------------------------------------------------------------------------
SPOT_DODGE_FRAMES: Final[int] = 26
SPOT_DODGE_INTANGIBLE: Final[tuple[int, int]] = (3, 17)
ROLL_FRAMES: Final[int] = 31
ROLL_INTANGIBLE: Final[tuple[int, int]] = (4, 15)
ROLL_MOVE_FRAMES: Final[tuple[int, int]] = (4, 23)
"""Frames of a roll during which the fighter travels."""
ROLL_DISTANCE: Final[float] = 1.6
AIR_DODGE_FRAMES: Final[int] = 49
AIR_DODGE_INTANGIBLE: Final[tuple[int, int]] = (3, 29)
AIR_DODGE_DIRECTIONAL_INTANGIBLE: Final[tuple[int, int]] = (3, 19)
AIR_DODGE_SPEED: Final[float] = 0.17
"""Starting speed of a directional air dodge; it falls linearly to zero over the burst."""
AIR_DODGE_BURST_FRAMES: Final[int] = 18
AIR_DODGE_LAND_LAG: Final[int] = 10
AIR_DODGE_DIRECTIONAL_LAND_LAG: Final[int] = 19
DODGE_STALE_STEP: Final[int] = 2
"""Extra end lag per recent dodge."""
DODGE_STALE_MAX: Final[int] = 12
DODGE_STALE_RESET_FRAMES: Final[int] = 120
"""Dodge staling wears off after this long without dodging (or on landing a hit)."""

# --- Grabs and throws ----------------------------------------------------------------------
GRAB_HOLD_DISTANCE: Final[float] = 0.6
"""How far in front of the grabber the victim is held, in units."""
GRAB_HOLD_BASE_FRAMES: Final[int] = 90
GRAB_HOLD_PER_DAMAGE: Final[float] = 1.7
GRAB_MASH_FRAMES: Final[int] = 4
"""Frames each new input by the victim takes off the hold."""
GRAB_RELEASE_FRAMES: Final[int] = 30
"""Lag for both fighters after a grab release or a grab clash."""
GRAB_RELEASE_SPEED: Final[float] = 0.06
"""Speed the two are pushed apart at on release."""
PUMMEL_HITLAG: Final[int] = 4
THROW_BACK_DEGREES: Final[float] = 112.5
"""A stick direction further than this from the facing picks the back throw."""

# --- Ledges --------------------------------------------------------------------------------
LEDGE_REACH: Final[float] = 0.5
"""Horizontal distance from a ledge line within which a falling fighter grabs it."""
LEDGE_Z_BELOW: Final[tuple[float, float]] = (0.3, 2.0)
"""The feet must be between these distances below the ledge's top to grab it."""
LEDGE_HANG_OUT: Final[float] = 0.35
"""A hanging fighter's feet point is this far outside the ledge line."""
LEDGE_HANG_BELOW: Final[float] = 1.8
"""...and this far below its top."""
LEDGE_AWAY_SPEED: Final[float] = 0.02
"""A fighter moving away from the stage faster than this does not grab."""
LEDGE_OCCUPIED_DISTANCE: Final[float] = 0.8
"""Two fighters closer than this along one ledge line share a spot (the newcomer trumps)."""
LEDGE_REGRAB_COOLDOWN: Final[int] = 30
LEDGE_ACTION_DELAY: Final[int] = 8
"""Frames a fighter must hang before it can pick a ledge option."""
LEDGE_MAX_HANG: Final[int] = 300
LEDGE_INTANGIBLE_BASE: Final[float] = 64.0
LEDGE_INTANGIBLE_MIN: Final[int] = 16
LEDGE_INTANGIBLE_PER_AIR_FRAME: Final[float] = 0.1
LEDGE_INTANGIBLE_PER_DAMAGE: Final[float] = 0.1
LEDGE_TRUMP_FRAMES: Final[int] = 20
LEDGE_TRUMP_SPEED: Final[float] = 0.05
LEDGE_GETUP_FRAMES: Final[int] = 30
LEDGE_GETUP_INTANGIBLE: Final[int] = 28
LEDGE_GETUP_INSET: Final[float] = 0.6
"""A getup ends this far inside the ledge line, standing on top."""
LEDGE_ATTACK_CLIMB_FRAMES: Final[int] = 18
LEDGE_ROLL_FRAMES: Final[int] = 45
LEDGE_ROLL_INTANGIBLE: Final[int] = 30
LEDGE_ROLL_DISTANCE: Final[float] = 2.0
LEDGE_JUMP_INTANGIBLE: Final[int] = 10
LEDGE_JUMP_IN_SPEED: Final[float] = 0.05
LEDGE_JUMP_VZ_MULT: Final[float] = 1.15
"""A ledge jump rises at the full hop speed times this."""

# --- Tech, knockdown, wall bounce, helpless ------------------------------------------------
TECH_WINDOW: Final[int] = 11
"""A shield press this many frames or fewer before touching ground or wall techs."""
TECH_LOCKOUT: Final[int] = 40
"""After a shield press in tumble, another one cannot count for this long."""
TECH_FRAMES: Final[int] = 26
TECH_INTANGIBLE: Final[int] = 20
TECH_ROLL_FRAMES: Final[int] = 40
TECH_ROLL_DISTANCE: Final[float] = 1.8
WALL_TECH_FRAMES: Final[int] = 20
WALL_TECH_INTANGIBLE: Final[int] = 14
WALL_BOUNCE_MIN_SPEED: Final[float] = 0.05
"""A tumbling fighter hitting a wall slower than this just stops."""
WALL_BOUNCE_KEEP: Final[float] = 0.8
"""Fraction of the knockback speed kept after bouncing off a wall."""
WALL_BOUNCE_DAMAGE: Final[float] = 1.0
GETUP_INTANGIBLE: Final[int] = 14
GETUP_ROLL_FRAMES: Final[int] = 35
GETUP_ROLL_INTANGIBLE: Final[int] = 20
GETUP_ROLL_DISTANCE: Final[float] = 1.6
HELPLESS_DRIFT_MULT: Final[float] = 0.6
HELPLESS_LAND_LAG: Final[int] = 20

# --- Specials, projectiles, counters -------------------------------------------------------------
PROJECTILE_SHIELDSTUN_MULT: Final[float] = 0.33
"""Shieldstun from a blocked projectile, relative to a blocked attack."""
COUNTER_MIN_FRAMES_TO_REPLY: Final[int] = 1
