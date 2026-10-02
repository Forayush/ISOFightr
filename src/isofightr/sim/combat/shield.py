"""Shield geometry and numbers: the bubble, shield damage and shieldstun.

Plan note "06 - Shield Dodge Grab and Ledge" ("Shield"). The shield is a sphere that shrinks
as it loses HP; a hitbox that reaches the hurtbox without touching the sphere pokes through.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

import math

from isofightr.sim.combat import constants as c
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.math3d import Capsule, Vec3

SHIELDING_STATES = frozenset({StateId.SHIELD, StateId.SHIELD_STUN})


def is_shielding(fighter: Fighter) -> bool:
    """Return whether the fighter's shield is up."""
    return fighter.state in SHIELDING_STATES


def shield_radius(fighter: Fighter) -> float:
    """Return the shield sphere's radius at the fighter's current shield HP."""
    health = max(0.0, min(1.0, fighter.shield_hp / c.SHIELD_MAX_HP))
    size = c.SHIELD_MIN_SIZE + (1.0 - c.SHIELD_MIN_SIZE) * health
    return fighter.character.body.shield_radius_max * size


def shield_centre(fighter: Fighter) -> Vec3:
    """Return the centre of the shield sphere."""
    return fighter.pos + Vec3(0.0, 0.0, c.SHIELD_CENTRE_HEIGHT)


def shield_volume(fighter: Fighter) -> Capsule:
    """Return the shield sphere as a zero-length capsule, for overlap tests."""
    centre = shield_centre(fighter)
    return Capsule(centre, centre, shield_radius(fighter))


def shield_damage(damage: float, extra: float = 0.0) -> float:
    """Return the shield HP a blocked hit removes."""
    return damage * c.SHIELD_DAMAGE_MULT + extra


def shieldstun_frames(damage: float) -> int:
    """Return how long a blocked hit keeps the defender in shieldstun."""
    return math.floor(damage * c.SHIELDSTUN_PER_DAMAGE + c.SHIELDSTUN_BASE)


def shield_push_speed(damage: float) -> float:
    """Return how fast a blocked hit slides the defender back, in units per frame."""
    return min(damage * c.SHIELD_PUSH_PER_DAMAGE, c.SHIELD_PUSH_MAX)


def dizzy_frames(damage: float) -> int:
    """Return how long a fighter stays dizzy after a shield break."""
    return max(c.DIZZY_MIN_FRAMES, math.floor(c.DIZZY_BASE_FRAMES - damage))
