"""3D hitboxes and hurtboxes, local-to-world transform, interpolated hitboxes.

Plan note "05 - Combat Core" ("Collision volumes"). All collision is spheres and capsules in
world space; nothing here knows about pixels.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from dataclasses import dataclass

from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import Capsule, Vec2, Vec3, capsules_overlap
from isofightr.sim.move_def import HitboxDef


@dataclass(frozen=True, slots=True)
class ActiveHitbox:
    """A hitbox that is out this tick, in world space."""

    definition: HitboxDef
    centre: Vec3
    previous: Vec3
    """Where the centre was last tick if the hitbox was already out, else ``centre``."""

    @property
    def volume(self) -> Capsule:
        """The capsule swept from last tick's centre to this tick's (so hits cannot tunnel)."""
        return Capsule(self.previous, self.centre, self.definition.radius)


def local_to_world(pos: Vec3, facing: Vec2, offset: Vec3) -> Vec3:
    """Place a fighter-local offset (forward, left, up) in the world.

    ``world = pos + forward * f + left * s + up * z`` with ``s = (-fy, fx)``.
    """
    left = facing.perpendicular_left()
    return Vec3(
        pos.x + offset.x * facing.x + offset.y * left.x,
        pos.y + offset.x * facing.y + offset.y * left.y,
        pos.z + offset.z,
    )


def hurtbox(fighter: Fighter) -> Capsule:
    """Return a fighter's hurtbox: a vertical capsule above its feet."""
    shape = fighter.character.body.hurtbox
    pos = fighter.pos
    return Capsule(
        Vec3(pos.x, pos.y, pos.z + shape.z0 + shape.radius),
        Vec3(pos.x, pos.y, pos.z + shape.z1 - shape.radius),
        shape.radius,
    )


def active_hitboxes(fighter: Fighter) -> list[ActiveHitbox]:
    """Return the hitboxes a fighter has out this tick, lowest id first."""
    move = fighter.move
    if move is None:
        return []
    facing = fighter.facing.world
    boxes = []
    for definition in move.active_hitboxes(fighter.state_frame):
        centre = local_to_world(fighter.pos, facing, definition.offset)
        previous = fighter.hitbox_centres.get(definition.id, centre)
        boxes.append(ActiveHitbox(definition, centre, previous))
    return boxes


def remember_hitboxes(fighter: Fighter, boxes: list[ActiveHitbox]) -> None:
    """Store this tick's hitbox centres so next tick can sweep from them."""
    fighter.hitbox_centres = {box.definition.id: box.centre for box in boxes}


def hits(box: ActiveHitbox, target: Fighter) -> bool:
    """Return whether a hitbox overlaps a fighter's hurtbox."""
    return capsules_overlap(box.volume, hurtbox(target))


def hitboxes_touch(first: ActiveHitbox, second: ActiveHitbox) -> bool:
    """Return whether two hitboxes overlap each other (for clanks)."""
    return capsules_overlap(first.volume, second.volume)


def charge_multiplier(fighter: Fighter) -> float:
    """Return the damage multiplier from charging the current smash attack."""
    move = fighter.move
    if move is None or move.charge is None:
        return 1.0
    charged = fighter.charge_frames / move.charge.max_frames
    return 1.0 + (move.charge.damage_mult - 1.0) * charged


def hit_damage(attacker: Fighter, definition: HitboxDef) -> float:
    """Return the damage a hitbox deals right now: base, times charge, times staling.

    The reply of a counter deals at least what the countered hit would have dealt, scaled.
    """
    base = max(definition.damage, attacker.counter_damage)
    return base * charge_multiplier(attacker) * attacker.move_stale
