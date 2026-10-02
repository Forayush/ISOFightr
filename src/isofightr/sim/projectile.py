"""Projectile entity: spawning, flight, ground contact, reflection.

Plan note "05 - Combat Core" ("Projectiles"). A projectile is a moving hitbox owned by a
fighter. What it hits is decided in :mod:`isofightr.sim.combat.projectile_hits`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from isofightr.sim.combat.hitbox import local_to_world
from isofightr.sim.math3d import Capsule, Vec2, Vec3
from isofightr.sim.move_def import GroundBehavior, HitboxDef, ProjectileDef
from isofightr.sim.stage import Stage

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter

REFLECT_DAMAGE_MULT: Final[float] = 1.5
"""A reflected projectile deals this many times its damage."""
REFLECT_SPEED_MULT: Final[float] = 1.0
BOUNCE_KEEP: Final[float] = 0.7
"""Fraction of its vertical speed a bouncing projectile keeps."""


def _nobody() -> list[int]:
    return []


@dataclass(slots=True)
class Projectile:
    """One projectile in flight."""

    id: int
    owner: int
    """Player index of the fighter it belongs to (it cannot hit its owner)."""
    move_id: str
    """The move that fired it, for the owner's stale queue."""
    definition: ProjectileDef
    pos: Vec3
    previous: Vec3
    """Where it was last tick, so fast projectiles cannot tunnel."""
    vel: Vec3
    damage: float
    """Damage it deals, fixed when it was fired (charge and staling included)."""
    lifetime: int
    age: int = 0
    pierce_left: int = 0
    hit: list[int] = field(default_factory=_nobody)
    """Player indices it has already hit or been blocked by."""
    alive: bool = True

    @property
    def hitbox(self) -> HitboxDef:
        """The projectile's hitbox definition."""
        return self.definition.hitbox

    @property
    def volume(self) -> Capsule:
        """The capsule swept from last tick's position to this tick's."""
        return Capsule(self.previous, self.pos, self.hitbox.radius)

    @property
    def heading(self) -> Vec2:
        """Horizontal direction of travel, a unit vector (zero if it moves straight up)."""
        return self.vel.xy.normalized()


def spawn(
    projectile_id: int, owner: Fighter, definition: ProjectileDef, damage: float
) -> Projectile:
    """Create the projectile a fighter's current move fires, in front of the fighter."""
    facing = owner.facing.world
    pos = local_to_world(owner.pos, facing, definition.hitbox.offset)
    forward = facing * definition.speed
    return Projectile(
        id=projectile_id,
        owner=owner.player_index,
        move_id=owner.move_id,
        definition=definition,
        pos=pos,
        previous=pos,
        vel=Vec3(forward.x, forward.y, definition.rise),
        damage=damage,
        lifetime=definition.lifetime,
        pierce_left=definition.pierce,
    )


def step(stage: Stage, projectile: Projectile) -> None:
    """Move a projectile for one tick: gravity, flight, the ground, the blast zone, old age."""
    projectile.age += 1
    if projectile.age > projectile.lifetime:
        projectile.alive = False
        return
    gravity = projectile.definition.gravity
    if gravity:
        projectile.vel = projectile.vel - Vec3(0.0, 0.0, gravity)
    projectile.previous = projectile.pos
    projectile.pos = projectile.pos + projectile.vel
    if not stage.blast_zone.contains(projectile.pos):
        projectile.alive = False
        return
    _touch_ground(stage, projectile)


def _touch_ground(stage: Stage, projectile: Projectile) -> None:
    pos = projectile.pos
    top = stage.surface_top(pos.x, pos.y)
    floor = pos.z - projectile.hitbox.radius
    if top is None or floor >= top or pos.z < stage.underside:
        return
    behavior = projectile.definition.ground
    came_from_above = projectile.previous.z - projectile.hitbox.radius >= top
    if behavior is GroundBehavior.DESTROY or not came_from_above:
        projectile.alive = False  # also when it runs into the side of the stage
        return
    projectile.pos = Vec3(pos.x, pos.y, top + projectile.hitbox.radius)
    if behavior is GroundBehavior.BOUNCE:
        projectile.vel = Vec3(projectile.vel.x, projectile.vel.y, -projectile.vel.z * BOUNCE_KEEP)
    else:
        projectile.vel = Vec3(projectile.vel.x, projectile.vel.y, 0.0)


def reflect(projectile: Projectile, new_owner: int) -> None:
    """Send a projectile back: reversed on the ground plane, stronger, and now ``new_owner``'s."""
    projectile.vel = Vec3(
        -projectile.vel.x * REFLECT_SPEED_MULT,
        -projectile.vel.y * REFLECT_SPEED_MULT,
        projectile.vel.z,
    )
    projectile.damage *= REFLECT_DAMAGE_MULT
    projectile.owner = new_owner
    projectile.hit = []
    projectile.age = 0
