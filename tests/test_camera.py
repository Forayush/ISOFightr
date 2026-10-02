"""Unit tests for the follow camera maths (plan note 03, "Camera")."""

import pytest

from isofightr.config import CAMERA_LERP, NATIVE_H, NATIVE_W
from isofightr.data.stage_loader import load_stage
from isofightr.render.camera import (
    FollowCamera,
    bounds_on_screen,
    clamp_centre,
    follow_target,
    snap,
)
from isofightr.render.depth import ScreenRect
from isofightr.render.iso import project
from isofightr.sim.math3d import Box3, Vec3

WIDE = ScreenRect(-1000.0, -1000.0, 1000.0, 1000.0)


def test_snap_rounds_halves_up_in_both_directions() -> None:
    assert [snap(v) for v in (0.4, 0.5, 1.5, 2.5, -0.5, -1.5, -0.6)] == [0, 1, 2, 3, 0, -1, -1]


def test_target_is_the_centre_of_the_bounding_box_not_the_average() -> None:
    positions = [Vec3(0.0, 0.0, 0.0), Vec3(4.0, 0.0, 0.0), Vec3(4.0, 0.0, 0.0)]
    assert follow_target(positions) == (32.0, -16.0)


def test_single_position_is_its_projection() -> None:
    assert follow_target([Vec3(3.0, 5.0, 2.5)]) == project(3.0, 5.0, 2.5)


def test_bounds_on_screen_encloses_every_corner() -> None:
    rect = bounds_on_screen(Box3(0.0, 2.0, 0.0, 4.0, -1.0, 3.0))
    # Leftmost is (0, 4), rightmost (2, 0); lowest is (2, 4, -1), highest (0, 0, 3).
    assert rect == ScreenRect(left=-64.0, bottom=-64.0, right=32.0, top=48.0)


def test_clamp_keeps_the_view_inside_wide_limits() -> None:
    limits = ScreenRect(0.0, 0.0, 1000.0, 600.0)
    assert clamp_centre((500.0, 300.0), limits) == (500.0, 300.0)
    assert clamp_centre((0.0, 0.0), limits) == (NATIVE_W / 2, NATIVE_H / 2)
    assert clamp_centre((5000.0, 5000.0), limits) == (1000 - NATIVE_W / 2, 600 - NATIVE_H / 2)


def test_clamp_locks_to_the_centre_when_limits_are_narrower_than_the_view() -> None:
    limits = ScreenRect(-100.0, -50.0, 300.0, 1000.0)
    assert clamp_centre((9999.0, 400.0), limits) == (100.0, 400.0)


def test_snap_to_jumps_and_update_lerps() -> None:
    camera = FollowCamera(limits=WIDE)
    camera.snap_to([Vec3(0.0, 0.0, 0.0)])
    assert (camera.x, camera.y) == (0.0, 0.0)
    target = [Vec3(10.0, 0.0, 0.0)]  # projects to (160, -80)
    camera.update(target)
    assert (camera.x, camera.y) == pytest.approx((160 * CAMERA_LERP, -80 * CAMERA_LERP))
    for _ in range(200):
        camera.update(target)
    assert (camera.x, camera.y) == pytest.approx((160.0, -80.0), abs=1e-6)
    assert camera.pixel_centre == (160, -80)


def test_pan_never_overshoots() -> None:
    camera = FollowCamera(limits=WIDE)
    previous = 0.0
    for _ in range(100):
        camera.update([Vec3(10.0, 0.0, 0.0)])
        assert previous <= camera.x <= 160.0
        previous = camera.x


def test_unclamped_camera_follows_past_the_limits() -> None:
    limits = ScreenRect(-10.0, -10.0, 10.0, 10.0)
    far = [Vec3(30.0, 0.0, 0.0)]
    camera = FollowCamera(limits=limits)
    camera.snap_to(far)
    assert (camera.x, camera.y) == (0.0, 0.0)
    camera.clamped = False
    camera.snap_to(far)
    assert (camera.x, camera.y) == project(30.0, 0.0)


@pytest.mark.parametrize("stage_id", ["training_grid", "sky_ruins"])
def test_main_islands_fit_on_screen_with_the_camera_at_rest(stage_id: str) -> None:
    """Design rule 2 in the plan note 11: the island plus platforms fits the native view."""
    stage = load_stage(stage_id)
    camera = FollowCamera(limits=bounds_on_screen(stage.camera_bounds))
    camera.snap_to([stage.spawn_point(index) for index in range(len(stage.spawns))])
    centre_x, centre_y = camera.pixel_centre
    highest = max([stage.bounds.z_max, *(platform.z for platform in stage.soft_platforms)])
    visible = bounds_on_screen(
        Box3(
            stage.bounds.x_min,
            stage.bounds.x_max,
            stage.bounds.y_min,
            stage.bounds.y_max,
            stage.bounds.z_min,
            highest,
        )
    )
    assert visible.left >= centre_x - NATIVE_W / 2
    assert visible.right <= centre_x + NATIVE_W / 2
    assert visible.bottom >= centre_y - NATIVE_H / 2
    assert visible.top <= centre_y + NATIVE_H / 2
