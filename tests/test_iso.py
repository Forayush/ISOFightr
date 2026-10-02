"""Unit tests for the isometric projection and its inverse (plan note 03, "Projection")."""

import pytest

from isofightr.render.iso import depth_key, project, project_point, unproject
from isofightr.sim.math3d import Vec3


def test_origin_projects_to_origin() -> None:
    assert project(0.0, 0.0, 0.0) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("world", "screen"),
    [
        ((1.0, 0.0, 0.0), (16.0, -8.0)),  # +x is screen south-east
        ((0.0, 1.0, 0.0), (-16.0, -8.0)),  # +y is screen south-west
        ((-1.0, 0.0, 0.0), (-16.0, 8.0)),  # -x is screen north-west
        ((0.0, -1.0, 0.0), (16.0, 8.0)),  # -y is screen north-east
        ((0.0, 0.0, 1.0), (0.0, 16.0)),  # +z is straight up
        ((1.0, 1.0, 0.0), (0.0, -16.0)),  # toward the camera is straight down
        ((1.0, -1.0, 0.0), (32.0, 0.0)),  # screen east
        ((3.0, 5.0, 2.5), (-32.0, -24.0)),
    ],
)
def test_projection_matches_the_plan_formula(
    world: tuple[float, float, float], screen: tuple[float, float]
) -> None:
    assert project(*world) == screen
    assert project_point(Vec3(*world)) == screen


def test_tile_top_is_a_32_by_16_diamond() -> None:
    back, right, front, left = (project(*c) for c in [(0, 0), (1, 0), (1, 1), (0, 1)])
    assert right[0] - left[0] == 32
    assert back[1] - front[1] == 16
    assert back[0] == front[0] == 0


@pytest.mark.parametrize("z", [0.0, 2.5, -3.0])
@pytest.mark.parametrize("point", [(0.0, 0.0), (3.25, 7.5), (-4.5, 12.125), (10.0, -2.0)])
def test_round_trip_world_to_screen_to_world(point: tuple[float, float], z: float) -> None:
    sx, sy = project(point[0], point[1], z)
    assert unproject(sx, sy, z) == pytest.approx(point)


@pytest.mark.parametrize("z", [0.0, 1.5])
@pytest.mark.parametrize("screen", [(0.0, 0.0), (37.0, -91.0), (-120.5, 44.25)])
def test_round_trip_screen_to_world_to_screen(screen: tuple[float, float], z: float) -> None:
    x, y = unproject(screen[0], screen[1], z)
    assert project(x, y, z) == pytest.approx(screen)


def test_unproject_defaults_to_the_ground_plane() -> None:
    assert unproject(16.0, -8.0) == pytest.approx((1.0, 0.0))


def test_depth_key_grows_toward_the_camera() -> None:
    assert depth_key(1.0, 1.0) > depth_key(0.0, 0.0)
    assert depth_key(2.0, 3.0) == depth_key(3.0, 2.0) == 5.0
    # Larger key means lower on screen at the same height.
    assert project(2.0, 2.0)[1] < project(1.0, 1.0)[1]
