"""Immutable move data: what a move TOML loads into.

Plan notes "07 - Fighter State Machine and Move Data" ("Move data format") and
"05 - Combat Core" ("Hitbox fields"). Frames are 1-indexed and ranges are inclusive.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from dataclasses import dataclass
from enum import Enum

from isofightr.sim.math3d import Vec3


class MoveKind(Enum):
    """What sort of move this is, which decides how it starts and ends."""

    JAB = "jab"
    TILT = "tilt"
    DASH_ATTACK = "dash_attack"
    SMASH = "smash"
    AERIAL = "aerial"
    RECOVERY = "recovery"
    """A getup attack: from a knockdown or from a ledge."""
    SPECIAL = "special"
    TAUNT = "taunt"


class DirectionMode(Enum):
    """How a hitbox picks its horizontal launch direction."""

    FACING = "facing"
    """Relative to the attacker's facing (the default)."""
    RADIAL = "radial"
    """From the hitbox centre toward the target."""
    AUTOLINK = "autolink"
    """Toward the hitbox centre, and carried along with the attacker's own velocity, to keep
    multi-hits connecting."""


class Effect(Enum):
    """Hit flavour. Mostly presentation; electric adds hitlag."""

    NORMAL = "normal"
    SLASH = "slash"
    FIRE = "fire"
    ELECTRIC = "electric"
    ICE = "ice"
    DARKNESS = "darkness"


@dataclass(frozen=True, slots=True)
class FrameRange:
    """An inclusive range of 1-indexed move frames."""

    first: int
    last: int

    def __contains__(self, frame: object) -> bool:
        return isinstance(frame, int) and self.first <= frame <= self.last


@dataclass(frozen=True, slots=True)
class HitboxDef:
    """One hitbox sphere of a move."""

    id: int
    """Priority within the move: the lowest id that connects is the one that hits."""
    group: int
    """A target can be hit once per group per activation (unless ``rehit``)."""
    offset: Vec3
    """Centre in fighter-local space: ``x`` forward, ``y`` to the fighter's left, ``z`` up."""
    radius: float
    damage: float
    angle: float
    """Launch elevation in degrees; 361 is the Sakurai angle; negative is a meteor."""
    yaw: float
    """Horizontal launch direction relative to the facing: 0 forward, 180 behind."""
    direction_mode: DirectionMode
    bkb: float
    kbg: float
    fkb: float
    """Fixed knockback: when above 0, damage and percent do not affect knockback."""
    hitlag_mult: float
    sdi_mult: float
    effect: Effect
    hits_ground: bool
    hits_air: bool
    rehit: int
    """Frames before the same group may hit the same target again (0 = never)."""
    clank: bool
    shield_damage: float = 0.0
    """Extra damage this hitbox does to a shield, on top of its normal damage."""


@dataclass(frozen=True, slots=True)
class HitWindow:
    """Hitboxes that are active over a range of frames."""

    frames: FrameRange
    hitboxes: tuple[HitboxDef, ...]


@dataclass(frozen=True, slots=True)
class MotionWindow:
    """Scripted self velocity over a range of frames, in fighter-local space."""

    frames: FrameRange
    velocity: Vec3
    """Units per frame: ``x`` forward, ``y`` to the fighter's left, ``z`` up."""


@dataclass(frozen=True, slots=True)
class ChargeDef:
    """A smash attack's charge: hold the strong button on ``frame`` to power it up."""

    frame: int
    max_frames: int
    damage_mult: float
    """Damage multiplier at full charge; it grows linearly from 1."""


@dataclass(frozen=True, slots=True)
class CancelDef:
    """A window in which pressing attack again moves on to another move (jab chains)."""

    frames: FrameRange
    into: str


class GroundBehavior(Enum):
    """What a projectile does when it touches solid ground."""

    DESTROY = "destroy"
    BOUNCE = "bounce"
    SLIDE = "slide"


@dataclass(frozen=True, slots=True)
class ProjectileDef:
    """A projectile a move fires (plan note 05, "Projectiles")."""

    frame: int
    """Move frame on which it is spawned."""
    hitbox: HitboxDef
    """What it hits with. ``offset`` is where it appears, relative to the fighter."""
    speed: float
    """Launch speed along the fighter's facing, in units per frame."""
    rise: float
    """Initial upward speed, in units per frame."""
    gravity: float
    lifetime: int
    """Frames before it fades out."""
    pierce: int
    """How many fighters or shields it passes through before it is destroyed."""
    reflectable: bool
    absorbable: bool
    ground: GroundBehavior
    burst: HitboxDef | None = None
    """If set, landing turns the projectile into this hitbox on the ground (a shockwave)."""
    burst_frames: int = 0
    """How long the burst stays out."""
    returns: int = 0
    """From this age on, the projectile flies back to its owner (a boomerang); 0 = never."""
    curve: float = 0.0
    """Degrees its heading turns each frame on its way out (positive: to its left)."""
    max_per_owner: int = 0
    """At most this many of the move's projectiles per owner; firing another removes the
    oldest (0 = no limit)."""


@dataclass(frozen=True, slots=True)
class CounterDef:
    """A counter window: a hit taken during it is cancelled and answered with ``into``."""

    frames: FrameRange
    into: str
    """The move performed in reply."""
    damage_mult: float
    """The reply deals at least the incoming damage times this."""


@dataclass(frozen=True, slots=True)
class ArmorDef:
    """Frames on which hits deal damage but do not launch (super armor), or only launch
    above a knockback threshold (heavy armor)."""

    frames: FrameRange
    threshold: float
    """Knockback at or above this breaks through; ``inf`` is super armor."""


@dataclass(frozen=True, slots=True)
class MoveDef:
    """Everything about one move."""

    id: str
    kind: MoveKind
    total: int
    """Number of frames the move lasts if nothing interrupts it."""
    faf: int
    """First actionable frame: from here the fighter may act out of the move."""
    anim: str
    windows: tuple[HitWindow, ...]
    motion: tuple[MotionWindow, ...]
    charge: ChargeDef | None
    cancel: CancelDef | None
    landing_lag: int
    """Aerials only: landing lag when the move is interrupted by landing."""
    autocancel: tuple[FrameRange, ...]
    intangible: FrameRange | None = None
    """Frames during which the fighter cannot be hit or grabbed (getup attacks)."""
    projectiles: tuple[ProjectileDef, ...] = ()
    counter: CounterDef | None = None
    armor: tuple[ArmorDef, ...] = ()
    reflect: FrameRange | None = None
    """Frames during which the move sends reflectable projectiles back."""
    script: str | None = None
    """Name of the Python script attached to the move (``"rook.side_special"``)."""
    helpless: bool = False
    """Whether ending the move in the air leaves the fighter in the helpless fall."""
    ledge_grab_from: int = 0
    """First frame on which the move can catch a ledge (0 = never)."""
    once_per_airtime: bool = False
    """Whether the move can be used only once in the air until landing or a ledge."""
    """Aerials only: frames on which landing uses the normal landing lag instead."""

    def active_hitboxes(self, frame: int) -> tuple[HitboxDef, ...]:
        """Return the hitboxes that are out on a move frame."""
        for window in self.windows:
            if frame in window.frames:
                return window.hitboxes
        return ()

    def scripted_velocity(self, frame: int) -> Vec3 | None:
        """Return the scripted local velocity on a move frame, if any."""
        for window in self.motion:
            if frame in window.frames:
                return window.velocity
        return None

    def armor_threshold(self, frame: int) -> float | None:
        """Return the knockback needed to break the armor on a move frame, or ``None``."""
        for window in self.armor:
            if frame in window.frames:
                return window.threshold
        return None

    @property
    def first_active_frame(self) -> int | None:
        """The move's startup: the first frame any hitbox is out."""
        return min((window.frames.first for window in self.windows), default=None)
