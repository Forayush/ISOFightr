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


class DirectionMode(Enum):
    """How a hitbox picks its horizontal launch direction."""

    FACING = "facing"
    """Relative to the attacker's facing (the default)."""
    RADIAL = "radial"
    """From the hitbox centre toward the target."""
    AUTOLINK = "autolink"
    """Toward a point in front of the attacker, to keep multi-hits connecting."""


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

    @property
    def first_active_frame(self) -> int | None:
        """The move's startup: the first frame any hitbox is out."""
        return min((window.frames.first for window in self.windows), default=None)
