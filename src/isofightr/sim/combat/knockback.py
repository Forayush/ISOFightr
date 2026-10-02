"""Knockback formula, hitstun, hitlag, launch direction and DI.

Plan note "05 - Combat Core". Everything here is a pure function of numbers, so each formula
has unit tests against hand-computed values.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

import math

from isofightr.sim.combat import constants as c
from isofightr.sim.math3d import EPSILON, Vec2, Vec3
from isofightr.sim.move_def import Effect


def knockback(
    percent_after: float,
    damage: float,
    weight: float,
    bkb: float,
    kbg: float,
    fkb: float = 0.0,
    ratio: float = 1.0,
) -> float:
    """Return knockback in Smash units (the Brawl/4/Ultimate formula).

    ``percent_after`` is the target's damage after this hit was added, and ``damage`` the
    damage dealt after staling. A fixed-knockback hit (``fkb > 0``) ignores both.
    """
    if fkb > 0.0:
        percent_after, damage = c.FIXED_KB_PERCENT, fkb
    scaled = percent_after / 10.0 + percent_after * damage / 20.0
    scaled *= c.KB_WEIGHT_NUMERATOR / (weight + c.KB_WEIGHT_OFFSET) * c.KB_SCALE
    return ((scaled + c.KB_CONSTANT) * kbg / 100.0 + bkb) * ratio


def hitstun_frames(kb: float) -> int:
    """Return how many frames a target is stunned by a hit of this knockback."""
    return math.floor(kb * c.HITSTUN_PER_KB)


def is_tumble(kb: float) -> bool:
    """Return whether this knockback sends the target into tumble."""
    return kb >= c.TUMBLE_KB


def hitlag_frames(
    damage: float,
    multiplier: float = 1.0,
    effect: Effect = Effect.NORMAL,
    full_charge: bool = False,
) -> int:
    """Return the freeze frames a hit gives both fighters."""
    if effect is Effect.ELECTRIC:
        multiplier *= c.ELECTRIC_HITLAG_MULT
    if full_charge:
        multiplier *= c.FULL_CHARGE_HITLAG_MULT
    frames = math.floor((damage * c.HITLAG_PER_DAMAGE + c.HITLAG_BASE) * multiplier)
    return min(frames, c.HITLAG_MAX)


def launch_speed(kb: float) -> float:
    """Return the launch speed in units per frame for a knockback value."""
    return kb * c.LAUNCH_SPEED_PER_KB


def resolve_elevation(angle: float, kb: float, target_grounded: bool) -> float:
    """Return the launch elevation in degrees for a hitbox angle.

    - The Sakurai angle (361) is horizontal for weak hits on a grounded target, rises
      linearly to 40 degrees as knockback grows, and is 40 degrees for an airborne target.
    - A meteor (negative angle) cannot push a grounded target into the floor: it pops the
      target up at the mirrored angle instead.
    """
    if angle == c.SAKURAI_ANGLE:
        if not target_grounded or kb >= c.SAKURAI_KB_HIGH:
            return c.SAKURAI_MAX_DEGREES
        if kb < c.SAKURAI_KB_LOW:
            return 0.0
        span = c.SAKURAI_KB_HIGH - c.SAKURAI_KB_LOW
        return c.SAKURAI_MAX_DEGREES * (kb - c.SAKURAI_KB_LOW) / span
    if angle < 0.0 and target_grounded:
        return -angle
    return angle


def meteor_tumbles(angle: float, kb: float, target_grounded: bool) -> bool:
    """Return whether a meteor on a grounded target bounces it into tumble."""
    return angle < 0.0 and angle != c.SAKURAI_ANGLE and target_grounded and kb >= c.METEOR_BOUNCE_KB


def apply_di(heading: Vec2, elevation: float, stick: Vec2, vertical: int) -> tuple[Vec2, float]:
    """Return the launch heading and elevation after directional influence.

    The held stick rotates the horizontal heading by up to ``DI_MAX_DEGREES``, in proportion
    to how perpendicular it is to the launch (holding along the launch does nothing). The
    up and down modifiers shift the elevation by ``DI_MAX_DEGREES`` (the iso addition).
    """
    magnitude = stick.length()
    if magnitude > EPSILON:
        turn = c.DI_MAX_DEGREES * heading.cross(stick / magnitude) * min(magnitude, 1.0)
        heading = heading.rotated(turn)
    if vertical != 0:
        shifted = elevation + c.DI_MAX_DEGREES * vertical
        elevation = max(-90.0, min(90.0, shifted))
    return heading, elevation


def launch_vector(heading: Vec2, elevation: float) -> Vec3:
    """Return the unit launch direction for a horizontal heading and an elevation."""
    radians = math.radians(elevation)
    flat = math.cos(radians)
    return Vec3(heading.x * flat, heading.y * flat, math.sin(radians))
