"""Unit tests for vectors, rotation and sphere/capsule intersection (plan notes 03 and 05)."""

import math

import pytest

from isofightr.sim.math3d import (
    Box3,
    Capsule,
    Sphere,
    Vec2,
    Vec3,
    capsules_overlap,
    closest_point_on_segment,
    segment_distance_squared,
    sphere_overlaps_capsule,
    spheres_overlap,
)


def assert_vec2(actual: Vec2, expected: tuple[float, float]) -> None:
    assert (actual.x, actual.y) == pytest.approx(expected, abs=1e-12)


def test_vec2_arithmetic() -> None:
    a, b = Vec2(1.0, 2.0), Vec2(3.0, -4.0)
    assert a + b == Vec2(4.0, -2.0)
    assert a - b == Vec2(-2.0, 6.0)
    assert a * 2 == Vec2(2.0, 4.0)
    assert 2 * a == Vec2(2.0, 4.0)
    assert b / 2 == Vec2(1.5, -2.0)
    assert -a == Vec2(-1.0, -2.0)


def test_vec2_products_and_length() -> None:
    assert Vec2(1.0, 2.0).dot(Vec2(3.0, -4.0)) == -5.0
    assert Vec2(1.0, 0.0).cross(Vec2(0.0, 1.0)) == 1.0
    assert Vec2(0.0, 1.0).cross(Vec2(1.0, 0.0)) == -1.0
    assert Vec2(3.0, 4.0).length() == 5.0
    assert Vec2(3.0, 4.0).length_squared() == 25.0


def test_vec2_normalized_handles_zero() -> None:
    assert_vec2(Vec2(3.0, 4.0).normalized(), (0.6, 0.8))
    assert Vec2().normalized() == Vec2()


def test_vec2_rotation_is_counter_clockwise() -> None:
    assert_vec2(Vec2(1.0, 0.0).rotated(90), (0.0, 1.0))
    assert_vec2(Vec2(1.0, 0.0).rotated(180), (-1.0, 0.0))
    assert_vec2(Vec2(1.0, 0.0).rotated(-90), (0.0, -1.0))
    assert_vec2(Vec2(1.0, 0.0).rotated(45), (math.sqrt(0.5), math.sqrt(0.5)))
    assert Vec2(2.0, 0.0).rotated(33).length() == pytest.approx(2.0)


def test_perpendicular_left_matches_a_quarter_turn() -> None:
    forward = Vec2(0.6, 0.8)
    assert_vec2(forward.perpendicular_left(), (-0.8, 0.6))
    assert_vec2(forward.rotated(90), (-0.8, 0.6))
    assert forward.cross(forward.perpendicular_left()) > 0


def test_vec2_lifts_to_vec3_and_back() -> None:
    assert Vec2(1.0, 2.0).with_z(3.0) == Vec3(1.0, 2.0, 3.0)
    assert Vec3(1.0, 2.0, 3.0).xy == Vec2(1.0, 2.0)


def test_vec3_arithmetic_and_products() -> None:
    a, b = Vec3(1.0, 2.0, 3.0), Vec3(4.0, 5.0, 6.0)
    assert a + b == Vec3(5.0, 7.0, 9.0)
    assert b - a == Vec3(3.0, 3.0, 3.0)
    assert a * 2 == 2 * a == Vec3(2.0, 4.0, 6.0)
    assert b / 2 == Vec3(2.0, 2.5, 3.0)
    assert -a == Vec3(-1.0, -2.0, -3.0)
    assert a.dot(b) == 32.0
    assert Vec3(1.0, 0.0, 0.0).cross(Vec3(0.0, 1.0, 0.0)) == Vec3(0.0, 0.0, 1.0)
    assert Vec3(2.0, 3.0, 6.0).length() == 7.0
    assert Vec3(0.0, 0.0, 5.0).normalized() == Vec3(0.0, 0.0, 1.0)
    assert Vec3().normalized() == Vec3()


def test_vectors_are_immutable_and_hashable() -> None:
    vector = Vec3(1.0, 2.0, 3.0)
    with pytest.raises(AttributeError):
        vector.x = 5.0  # type: ignore[misc]
    assert {vector: "ok"}[Vec3(1.0, 2.0, 3.0)] == "ok"


def test_box_contains_includes_the_boundary() -> None:
    box = Box3(0.0, 2.0, 0.0, 3.0, -1.0, 4.0)
    assert box.contains(Vec3(1.0, 1.0, 0.0))
    assert box.contains(Vec3(2.0, 3.0, 4.0))
    assert not box.contains(Vec3(2.01, 1.0, 0.0))
    assert not box.contains(Vec3(1.0, 1.0, -1.01))
    assert len(set(box.corners())) == 8


def test_closest_point_on_segment_clamps_to_the_ends() -> None:
    start, end = Vec3(0.0, 0.0, 0.0), Vec3(0.0, 0.0, 2.0)
    assert closest_point_on_segment(Vec3(1.0, 0.0, 1.0), start, end) == Vec3(0.0, 0.0, 1.0)
    assert closest_point_on_segment(Vec3(1.0, 0.0, 5.0), start, end) == end
    assert closest_point_on_segment(Vec3(1.0, 0.0, -5.0), start, end) == start
    assert closest_point_on_segment(Vec3(1.0, 0.0, 5.0), start, start) == start


def test_spheres_overlap_including_touching() -> None:
    a = Sphere(Vec3(0.0, 0.0, 0.0), 1.0)
    assert spheres_overlap(a, Sphere(Vec3(1.5, 0.0, 0.0), 0.6))
    assert spheres_overlap(a, Sphere(Vec3(2.0, 0.0, 0.0), 1.0))
    assert not spheres_overlap(a, Sphere(Vec3(2.1, 0.0, 0.0), 1.0))
    assert not spheres_overlap(a, Sphere(Vec3(0.0, 0.0, 3.0), 1.5))


def test_sphere_against_a_vertical_hurtbox_capsule() -> None:
    hurtbox = Capsule(Vec3(0.0, 0.0, 0.2), Vec3(0.0, 0.0, 2.3), 0.35)
    assert sphere_overlaps_capsule(Sphere(Vec3(0.8, 0.0, 1.2), 0.5), hurtbox)
    assert not sphere_overlaps_capsule(Sphere(Vec3(0.9, 0.0, 1.2), 0.5), hurtbox)
    # Above the top end cap: distance is measured to the end point, not the infinite line.
    assert sphere_overlaps_capsule(Sphere(Vec3(0.0, 0.0, 3.0), 0.4), hurtbox)
    assert not sphere_overlaps_capsule(Sphere(Vec3(0.0, 0.0, 3.2), 0.4), hurtbox)
    # Same ground position but far below: 3D matters, the ground plane alone is not enough.
    assert not sphere_overlaps_capsule(Sphere(Vec3(0.0, 0.0, -2.0), 0.5), hurtbox)


def test_sphere_against_a_degenerate_capsule_is_sphere_vs_sphere() -> None:
    point_capsule = Capsule(Vec3(1.0, 1.0, 1.0), Vec3(1.0, 1.0, 1.0), 0.5)
    assert sphere_overlaps_capsule(Sphere(Vec3(2.0, 1.0, 1.0), 0.5), point_capsule)
    assert not sphere_overlaps_capsule(Sphere(Vec3(2.1, 1.0, 1.0), 0.5), point_capsule)


def test_segment_distance_for_crossing_parallel_and_skew_segments() -> None:
    origin = Vec3(0.0, 0.0, 0.0)
    # Crossing in the middle.
    assert segment_distance_squared(
        Vec3(-1.0, 0.0, 0.0), Vec3(1.0, 0.0, 0.0), Vec3(0.0, -1.0, 0.0), Vec3(0.0, 1.0, 0.0)
    ) == pytest.approx(0.0)
    # Parallel, offset by 2.
    assert segment_distance_squared(
        origin, Vec3(4.0, 0.0, 0.0), Vec3(1.0, 2.0, 0.0), Vec3(3.0, 2.0, 0.0)
    ) == pytest.approx(4.0)
    # Skew: perpendicular directions separated by 3 in z.
    assert segment_distance_squared(
        Vec3(-1.0, 0.0, 0.0), Vec3(1.0, 0.0, 0.0), Vec3(0.0, -1.0, 3.0), Vec3(0.0, 1.0, 3.0)
    ) == pytest.approx(9.0)
    # End to end: closest points are endpoints.
    assert segment_distance_squared(
        origin, Vec3(1.0, 0.0, 0.0), Vec3(3.0, 0.0, 0.0), Vec3(5.0, 0.0, 0.0)
    ) == pytest.approx(4.0)
    # Both degenerate, and one degenerate.
    far_point = Vec3(0.0, 3.0, 4.0)
    assert segment_distance_squared(origin, origin, far_point, far_point) == 25.0
    assert segment_distance_squared(
        Vec3(0.5, 2.0, 0.0), Vec3(0.5, 2.0, 0.0), origin, Vec3(1.0, 0.0, 0.0)
    ) == pytest.approx(4.0)


def test_segment_distance_is_symmetric() -> None:
    a = (Vec3(0.0, 0.0, 0.0), Vec3(2.0, 1.0, 0.5))
    b = (Vec3(1.0, 3.0, 2.0), Vec3(4.0, 2.0, -1.0))
    assert segment_distance_squared(*a, *b) == pytest.approx(segment_distance_squared(*b, *a))


def test_swept_hitbox_capsule_catches_a_target_it_would_tunnel_through() -> None:
    hurtbox = Capsule(Vec3(0.0, 0.0, 0.2), Vec3(0.0, 0.0, 2.3), 0.35)
    previous, current = Vec3(-2.0, 0.0, 1.0), Vec3(2.0, 0.0, 1.0)
    radius = 0.3
    assert not sphere_overlaps_capsule(Sphere(previous, radius), hurtbox)
    assert not sphere_overlaps_capsule(Sphere(current, radius), hurtbox)
    assert capsules_overlap(Capsule(previous, current, radius), hurtbox)


def test_capsules_that_miss() -> None:
    a = Capsule(Vec3(0.0, 0.0, 0.0), Vec3(0.0, 0.0, 2.0), 0.3)
    assert capsules_overlap(a, Capsule(Vec3(0.6, 0.0, 0.0), Vec3(0.6, 0.0, 2.0), 0.3))
    assert not capsules_overlap(a, Capsule(Vec3(0.7, 0.0, 0.0), Vec3(0.7, 0.0, 2.0), 0.3))
    assert not capsules_overlap(a, Capsule(Vec3(0.0, 0.0, 3.0), Vec3(1.0, 0.0, 3.0), 0.3))
