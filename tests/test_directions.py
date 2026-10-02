"""Unit tests for 8-way facing and stick-to-world conversion (plan notes 03 and 08)."""

import math

import pytest

from isofightr.config import FACING_HYSTERESIS_DEGREES
from isofightr.render.iso import project
from isofightr.sim.input_frame import Dir8, facing_from_move, stick_to_world, world_to_stick
from isofightr.sim.math3d import Vec2

D = 1 / math.sqrt(2)


def stick(degrees: float, magnitude: float = 1.0) -> Vec2:
    """A world move vector for a stick pushed at ``degrees`` counter-clockwise from screen-right."""
    radians = math.radians(degrees)
    return stick_to_world(magnitude * math.cos(radians), magnitude * math.sin(radians))


@pytest.mark.parametrize(
    ("direction", "world"),
    [
        (Dir8.E, (D, -D)),
        (Dir8.W, (-D, D)),
        (Dir8.N, (-D, -D)),
        (Dir8.S, (D, D)),
        (Dir8.SE, (1.0, 0.0)),
        (Dir8.SW, (0.0, 1.0)),
        (Dir8.NE, (0.0, -1.0)),
        (Dir8.NW, (-1.0, 0.0)),
    ],
)
def test_world_vectors_match_the_plan_table(direction: Dir8, world: tuple[float, float]) -> None:
    assert (direction.world.x, direction.world.y) == pytest.approx(world)
    assert direction.world.length() == pytest.approx(1.0)


@pytest.mark.parametrize("direction", list(Dir8))
def test_facing_points_the_named_way_on_screen(direction: Dir8) -> None:
    def sign(value: float) -> int:
        return 0 if abs(value) < 1e-9 else (1 if value > 0 else -1)

    sx, sy = project(direction.world.x, direction.world.y)
    radians = math.radians(direction.stick_degrees)
    # Iso foreshortening halves the vertical component; the sign pattern is what matters.
    assert sign(sx) == sign(math.cos(radians))
    assert sign(sy) == sign(math.sin(radians))


def test_stick_right_moves_screen_right() -> None:
    world = stick_to_world(1.0, 0.0)
    assert (world.x, world.y) == pytest.approx((D, -D))
    sx, sy = project(world.x, world.y)
    assert sx > 0 and sy == pytest.approx(0.0)


def test_stick_up_moves_screen_up() -> None:
    world = stick_to_world(0.0, 1.0)
    sx, sy = project(world.x, world.y)
    assert sx == pytest.approx(0.0) and sy > 0


def test_stick_conversion_preserves_magnitude_and_round_trips() -> None:
    world = stick_to_world(0.3, -0.4)
    assert world.length() == pytest.approx(0.5)
    assert world_to_stick(world) == pytest.approx((0.3, -0.4))


@pytest.mark.parametrize("direction", list(Dir8))
def test_exact_directions_snap_to_themselves(direction: Dir8) -> None:
    assert facing_from_move(direction.world) is direction
    assert facing_from_move(direction.world * 0.2) is direction


def test_nearest_direction_without_a_current_facing() -> None:
    assert facing_from_move(stick(20)) is Dir8.E
    assert facing_from_move(stick(25)) is Dir8.NE
    assert facing_from_move(stick(-170)) is Dir8.W
    assert facing_from_move(stick(-100)) is Dir8.S


def test_zero_move_keeps_the_current_facing() -> None:
    assert facing_from_move(Vec2(), Dir8.NW) is Dir8.NW
    assert facing_from_move(Vec2()) is None


def test_hysteresis_holds_the_facing_just_past_the_boundary() -> None:
    boundary = 22.5
    inside = boundary + FACING_HYSTERESIS_DEGREES - 0.5
    outside = boundary + FACING_HYSTERESIS_DEGREES + 0.5
    assert facing_from_move(stick(inside), Dir8.E) is Dir8.E
    assert facing_from_move(stick(outside), Dir8.E) is Dir8.NE
    assert facing_from_move(stick(-inside), Dir8.E) is Dir8.E
    assert facing_from_move(stick(-outside), Dir8.E) is Dir8.SE


def test_hysteresis_works_across_the_wrap_at_west() -> None:
    assert facing_from_move(stick(-160), Dir8.W) is Dir8.W
    assert facing_from_move(stick(160), Dir8.W) is Dir8.W
    assert facing_from_move(stick(150), Dir8.W) is Dir8.NW


def test_boundary_jitter_does_not_flip_the_facing() -> None:
    facing = Dir8.E
    changes = 0
    for step in range(40):
        jitter = 22.5 + (1.5 if step % 2 else -1.5)
        new_facing = facing_from_move(stick(jitter), facing)
        changes += new_facing is not facing
        assert new_facing is not None
        facing = new_facing
    assert changes == 0
