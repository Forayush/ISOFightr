"""Immutable character data: what a ``fighter.toml`` loads into.

Plan note "07 - Fighter State Machine and Move Data" ("Character data format"). A ``Fighter``
holds one :class:`CharacterDef` plus its own mutable runtime state. The TOML reading and
validation live in :mod:`isofightr.data.character_loader`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from isofightr.sim.move_def import MoveDef


@dataclass(frozen=True, slots=True)
class MovementStats:
    """Movement numbers, in world units and frames (plan note "04 - Movement and Physics")."""

    walk_speed: float
    """Ground speed at full stick tilt without dashing, in units per frame."""
    dash_speed: float
    """Speed of the initial dash burst."""
    dash_frames: int
    """Length of the initial dash before it becomes a run."""
    run_speed: float
    traction: float
    """Ground deceleration per frame when not driving."""
    jumpsquat: int
    """Grounded frames between pressing jump and leaving the ground."""
    full_hop_vz: float
    short_hop_vz: float
    double_jump_vz: float
    air_jumps: int
    air_accel: float
    """Horizontal acceleration per frame toward the stick while airborne."""
    air_speed: float
    """Cap on self-controlled horizontal air speed (a circle, not per axis)."""
    air_friction: float
    """Horizontal deceleration per frame while airborne with the stick neutral."""
    gravity: float
    max_fall: float
    fast_fall: float
    land_lag: int
    """Frames of landing lag after a normal (non-attacking) landing."""


@dataclass(frozen=True, slots=True)
class HurtboxDef:
    """The vertical capsule that can be hit, relative to the feet."""

    radius: float
    z0: float
    """Height of the capsule's lowest point above the feet."""
    z1: float
    """Height of the capsule's highest point above the feet."""


@dataclass(frozen=True, slots=True)
class BodyStats:
    """Body dimensions used for stage collision and for being hit."""

    radius: float
    """Environment collision radius on the ground plane."""
    height: float
    """Height from the feet to the top of the head."""
    hurtbox: HurtboxDef


@dataclass(frozen=True, slots=True)
class MoveSet:
    """Which move each input slot uses (plan note 07, ``[moveset]``). Values are move ids."""

    jab: tuple[str, ...]
    """The jab chain, in order."""
    ftilt: str
    utilt: str
    dtilt: str
    dash_attack: str
    fsmash: str
    usmash: str
    dsmash: str
    nair: str
    fair: str
    bair: str
    uair: str
    dair: str

    def all_ids(self) -> tuple[str, ...]:
        """Return every move id the moveset refers to."""
        singles = (
            self.ftilt,
            self.utilt,
            self.dtilt,
            self.dash_attack,
            self.fsmash,
            self.usmash,
            self.dsmash,
            self.nair,
            self.fair,
            self.bair,
            self.uair,
            self.dair,
        )
        return (*self.jab, *singles)


@dataclass(frozen=True, slots=True)
class CharacterDef:
    """Everything about a character that never changes during a match."""

    id: str
    display_name: str
    weight: float
    movement: MovementStats
    body: BodyStats
    moveset: MoveSet
    moves: Mapping[str, MoveDef]
    """Every move of the character, by id."""

    def __deepcopy__(self, memo: dict[int, object]) -> Self:
        """Character data is immutable, so a copied match (snapshots, rollback) shares it."""
        return self
