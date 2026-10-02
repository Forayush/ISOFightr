"""Dataclass events emitted by the sim each tick for presentation and audio to consume.

Plan note "02 - Technical Architecture": presentation reads the sim state and the per-tick
event list, and never mutates the sim. ``Match.events`` holds the events of the latest tick.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from dataclasses import dataclass
from enum import Enum

from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect


class JumpKind(Enum):
    """Which kind of jump left the ground or the air."""

    SHORT_HOP = "short_hop"
    FULL_HOP = "full_hop"
    AIR = "air"


@dataclass(frozen=True, slots=True)
class JumpEvent:
    """A fighter jumped (dust puff, jump sound)."""

    player: int
    kind: JumpKind
    position: Vec3


@dataclass(frozen=True, slots=True)
class LandEvent:
    """A fighter landed on the ground or a platform (dust puff, landing sound)."""

    player: int
    position: Vec3
    fall_speed: float
    """Downward speed just before landing, in units per frame (0 or positive)."""


@dataclass(frozen=True, slots=True)
class KoEvent:
    """A fighter crossed a blast zone and lost a stock (KO blast VFX, crowd sound)."""

    player: int
    position: Vec3
    """Where the fighter crossed the blast-zone box."""
    normal: Vec3
    """Outward unit normal of the face that was crossed."""
    stocks_left: int | None
    """Stocks remaining after the KO, or ``None`` when stocks are infinite."""


@dataclass(frozen=True, slots=True)
class RespawnEvent:
    """A fighter reappeared on the revival platform."""

    player: int
    position: Vec3


@dataclass(frozen=True, slots=True)
class HitEvent:
    """An attack connected (hit spark, hit sound, screen shake, HUD shake)."""

    attacker: int
    target: int
    move_id: str
    damage: float
    """Damage dealt after charge and staling (0 against an invincible target)."""
    knockback: float
    position: Vec3
    """World position of the hitbox that connected."""
    effect: Effect
    hitlag: int


@dataclass(frozen=True, slots=True)
class ClankEvent:
    """A fighter's attack was stopped by clashing with another attack (clank spark)."""

    player: int
    position: Vec3


type Event = JumpEvent | LandEvent | KoEvent | RespawnEvent | HitEvent | ClankEvent
