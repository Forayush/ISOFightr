"""Vec2/Vec3, rotation, boxes, and sphere/capsule intersection tests.

Plan notes "03 - Isometric World and Rendering" (world space: ``x``/``y`` ground plane, ``z``
up, 1 unit = 1 tile edge) and "05 - Combat Core" (all collision is 3D spheres and capsules).
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

EPSILON: Final[float] = 1e-9
"""Lengths below this count as zero (degenerate segments, normalizing a null vector)."""


@dataclass(frozen=True, slots=True)
class Vec2:
    """A point or direction on the ground plane."""

    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar: float) -> Vec2:
        return Vec2(self.x / scalar, self.y / scalar)

    def __neg__(self) -> Vec2:
        return Vec2(-self.x, -self.y)

    def dot(self, other: Vec2) -> float:
        """Return the dot product."""
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        """Return the 2D cross product (z of the 3D cross): positive if ``other`` is to the left."""
        return self.x * other.y - self.y * other.x

    def length_squared(self) -> float:
        """Return the squared length (no square root)."""
        return self.x * self.x + self.y * self.y

    def length(self) -> float:
        """Return the Euclidean length."""
        return math.hypot(self.x, self.y)

    def normalized(self) -> Vec2:
        """Return the unit vector, or the zero vector if this one has no length."""
        length = self.length()
        if length < EPSILON:
            return Vec2()
        return Vec2(self.x / length, self.y / length)

    def rotated(self, degrees: float) -> Vec2:
        """Return this vector rotated counter-clockwise in world space by ``degrees``."""
        radians = math.radians(degrees)
        cos, sin = math.cos(radians), math.sin(radians)
        return Vec2(self.x * cos - self.y * sin, self.x * sin + self.y * cos)

    def perpendicular_left(self) -> Vec2:
        """Return the left-hand perpendicular ``(-y, x)``, i.e. this vector rotated +90 degrees."""
        return Vec2(-self.y, self.x)

    def with_z(self, z: float) -> Vec3:
        """Lift this ground-plane vector to 3D at height ``z``."""
        return Vec3(self.x, self.y, z)


@dataclass(frozen=True, slots=True)
class Vec3:
    """A point or direction in world space (``z`` is up)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar: float) -> Vec3:
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def __neg__(self) -> Vec3:
        return Vec3(-self.x, -self.y, -self.z)

    @property
    def xy(self) -> Vec2:
        """The ground-plane part of this vector."""
        return Vec2(self.x, self.y)

    def dot(self, other: Vec3) -> float:
        """Return the dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        """Return the cross product (right-handed)."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length_squared(self) -> float:
        """Return the squared length (no square root)."""
        return self.x * self.x + self.y * self.y + self.z * self.z

    def length(self) -> float:
        """Return the Euclidean length."""
        return math.sqrt(self.length_squared())

    def normalized(self) -> Vec3:
        """Return the unit vector, or the zero vector if this one has no length."""
        length = self.length()
        if length < EPSILON:
            return Vec3()
        return Vec3(self.x / length, self.y / length, self.z / length)


ZERO2: Final[Vec2] = Vec2()
"""The zero ground vector. Vectors are immutable, so sharing one instance is safe."""

ZERO3: Final[Vec3] = Vec3()
"""The zero world vector."""


@dataclass(frozen=True, slots=True)
class Box3:
    """An axis-aligned box in world space (blast zones, camera bounds, stage extents)."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    def contains(self, point: Vec3) -> bool:
        """Return whether ``point`` is inside the box or on its boundary."""
        return (
            self.x_min <= point.x <= self.x_max
            and self.y_min <= point.y <= self.y_max
            and self.z_min <= point.z <= self.z_max
        )

    def corners(self) -> tuple[Vec3, ...]:
        """Return the eight corners, bottom face first."""
        return tuple(
            Vec3(x, y, z)
            for z in (self.z_min, self.z_max)
            for y in (self.y_min, self.y_max)
            for x in (self.x_min, self.x_max)
        )


@dataclass(frozen=True, slots=True)
class Sphere:
    """A sphere: hitboxes, grab boxes and shields."""

    center: Vec3
    radius: float


@dataclass(frozen=True, slots=True)
class Capsule:
    """All points within ``radius`` of the segment ``start``-``end``: hurtboxes, swept hitboxes."""

    start: Vec3
    end: Vec3
    radius: float


def closest_point_on_segment(point: Vec3, start: Vec3, end: Vec3) -> Vec3:
    """Return the point of segment ``start``-``end`` nearest to ``point``."""
    segment = end - start
    length_squared = segment.length_squared()
    if length_squared < EPSILON:
        return start
    t = (point - start).dot(segment) / length_squared
    return start + segment * min(1.0, max(0.0, t))


def segment_distance_squared(a_start: Vec3, a_end: Vec3, b_start: Vec3, b_end: Vec3) -> float:
    """Return the squared distance between the closest points of two segments.

    Handles degenerate (zero-length) and parallel segments. Standard clamped closest-point
    computation (Ericson, "Real-Time Collision Detection", 5.1.9).
    """
    d1 = a_end - a_start
    d2 = b_end - b_start
    r = a_start - b_start
    a = d1.length_squared()
    e = d2.length_squared()
    f = d2.dot(r)

    if a < EPSILON and e < EPSILON:
        return r.length_squared()
    if a < EPSILON:
        s = 0.0
        t = min(1.0, max(0.0, f / e))
    else:
        c = d1.dot(r)
        if e < EPSILON:
            t = 0.0
            s = min(1.0, max(0.0, -c / a))
        else:
            b = d1.dot(d2)
            denominator = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / denominator)) if denominator > EPSILON else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = min(1.0, max(0.0, (b - c) / a))

    closest_a = a_start + d1 * s
    closest_b = b_start + d2 * t
    return (closest_a - closest_b).length_squared()


def spheres_overlap(a: Sphere, b: Sphere) -> bool:
    """Return whether two spheres intersect (touching counts)."""
    reach = a.radius + b.radius
    return (a.center - b.center).length_squared() <= reach * reach


def sphere_overlaps_capsule(sphere: Sphere, capsule: Capsule) -> bool:
    """Return whether a sphere intersects a capsule (touching counts)."""
    closest = closest_point_on_segment(sphere.center, capsule.start, capsule.end)
    reach = sphere.radius + capsule.radius
    return (sphere.center - closest).length_squared() <= reach * reach


def capsules_overlap(a: Capsule, b: Capsule) -> bool:
    """Return whether two capsules intersect (touching counts)."""
    reach = a.radius + b.radius
    return segment_distance_squared(a.start, a.end, b.start, b.end) <= reach * reach
