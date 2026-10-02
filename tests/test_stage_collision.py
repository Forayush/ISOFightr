"""Scenario tests for stage collision: soft platforms, walls, steps and the island underside.

Plan note "04 - Movement and Physics" ("Stage collision (heightmap model)" and the
"Ground hugging and edge cases checklist"). Synthetic stages come from ``make_stage``; digits
in the grid are cell heights.
"""

import pytest

from helpers import hold, make_match, make_stage, neutral, place, run, run_until
from isofightr.sim.constants import PLATFORM_DROP_FRAMES, STEP_HEIGHT
from isofightr.sim.fighter import GroundKind, StateId
from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.math3d import Vec3

JUMP = InputFrame(held=Button.JUMP)
RADIUS = 0.30
HEIGHT = 2.5

# A 7x7 floor with a 3x3 soft platform 2.5 units up, like one of Sky Ruins' low platforms.
PLATFORM_STAGE = make_stage(["0000000"] * 7, platforms=[(2, 2, 5, 5, 2.5)])


# --- soft platforms -----------------------------------------------------------------------


def test_falling_onto_a_soft_platform_lands_on_it() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 3.5, 3.5, z=4.0)
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 2.5
    assert (rook.ground, rook.platform) == (GroundKind.PLATFORM, 0)


def test_jumping_up_through_a_soft_platform_from_below() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 3.5, 3.5, z=0.0)
    run(match, [JUMP] * 4)
    heights = []
    while rook.vel.z > 0:
        run(match, neutral(1))
        heights.append(rook.pos.z)
    assert max(heights) == pytest.approx(3.6), "the platform did not stop the rise"
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 2.5, "and on the way down the fighter lands on it"


def test_a_full_hop_reaches_the_low_platforms_and_not_the_high_one() -> None:
    match = make_match("sky_ruins")
    rook = match.fighters[0]
    place(match, rook, 3.5, 7.5, z=0.0)  # under the low screen-left platform (z 2.5)
    run(match, [JUMP] * 4)
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 2.5
    place(match, rook, 6.5, 4.5, z=0.0)  # under the high platform (z 4.5)
    run(match, [JUMP] * 4)
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 0.0
    # A full hop plus the air jump does reach it.
    run(match, neutral(5))
    run(match, [JUMP] * 4)
    while rook.vel.z > 0:
        run(match, neutral(1))
    run(match, [JUMP])
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 4.5


def test_walking_sideways_under_a_platform_does_not_snap_onto_it() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 1.0, 3.5)
    run(match, hold(Dir8.SE, Button.WALK, frames=60))
    assert rook.pos.x > 4.0
    assert rook.pos.z == 0.0 and rook.ground is GroundKind.CELL


def test_walking_off_a_platform_edge_falls_to_the_ground() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 4.5, 3.5)
    assert rook.pos.z == 2.5 and rook.ground is GroundKind.PLATFORM
    run(match, hold(Dir8.SE, Button.WALK, frames=15))
    assert rook.state is StateId.FALL
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 0.0 and rook.ground is GroundKind.CELL


def test_holding_down_on_a_platform_drops_through_after_three_frames() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 3.5, 3.5)
    states = []
    for _ in range(PLATFORM_DROP_FRAMES + 1):
        run(match, hold(vertical=-1, frames=1))
        states.append(rook.state)
    assert states == [StateId.PLATFORM_DROP] * PLATFORM_DROP_FRAMES + [StateId.FALL]
    assert rook.pos.z < 2.5
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 0.0
    assert not rook.fast_falling, "the drop tap is not also a fast fall"


def test_down_does_nothing_on_solid_ground() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 6.5, 6.5)
    run(match, hold(vertical=-1, frames=10))
    assert rook.state is StateId.IDLE and rook.pos.z == 0.0


def test_tapping_down_while_walking_on_a_platform_drops_through() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 2.5, 3.5)
    run(match, hold(Dir8.SE, Button.WALK, frames=5))
    run(match, hold(Dir8.SE, Button.WALK, frames=1, vertical=-1))
    assert rook.state is StateId.PLATFORM_DROP


def test_after_dropping_through_the_same_platform_can_be_landed_on_again() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 3.5, 3.5)
    run(match, hold(vertical=-1, frames=PLATFORM_DROP_FRAMES + 1))
    run_until(match, rook, StateId.LAND)
    run(match, neutral(5))
    run(match, [JUMP] * 4)
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 2.5


def test_fast_horizontal_movement_does_not_tunnel_through_a_platform() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 2.2, 3.5, z=2.6)
    rook.kb_vel = Vec3(0.9, 0.0, -0.3)
    run(match, neutral(1))
    assert rook.pos.z == 2.5 and rook.ground is GroundKind.PLATFORM


# --- walls and steps ----------------------------------------------------------------------


def test_a_raised_block_is_a_wall() -> None:
    match = make_match(make_stage(["00200"]))
    rook = match.fighters[0]
    place(match, rook, 0.5, 0.5)
    run(match, hold(Dir8.SE, frames=40))
    assert rook.pos.x == pytest.approx(2.0 - RADIUS, abs=1e-5), "stopped a body radius short"
    assert rook.pos.z == 0.0 and rook.grounded
    assert rook.vel.x == 0.0


def test_sliding_along_a_wall() -> None:
    match = make_match(make_stage(["00200", "00200", "00200", "00000"]))
    rook = match.fighters[0]
    place(match, rook, 1.0, 0.5)
    run(match, hold(Dir8.S, Button.WALK, frames=30))  # south = +x and +y together
    assert rook.pos.x == pytest.approx(2.0 - RADIUS, abs=1e-5)
    assert rook.pos.y > 1.5, "kept moving along the wall"


def test_a_wall_cannot_be_tunnelled_through_at_high_speed() -> None:
    match = make_match(make_stage(["00200"]))
    rook = match.fighters[0]
    place(match, rook, 0.5, 0.5)
    rook.kb_vel = Vec3(3.0, 0.0, 0.0)
    run(match, neutral(1))
    assert rook.pos.x == pytest.approx(2.0 - RADIUS, abs=1e-5)
    assert rook.kb_vel.x == 0.0


def test_walls_block_from_every_side() -> None:
    stage = make_stage(["000", "020", "000"])
    for start, direction, axis, limit in [
        ((0.5, 1.5), Dir8.SE, "x", 1.0 - RADIUS),
        ((2.5, 1.5), Dir8.NW, "x", 2.0 + RADIUS),
        ((1.5, 0.5), Dir8.SW, "y", 1.0 - RADIUS),
        ((1.5, 2.5), Dir8.NE, "y", 2.0 + RADIUS),
    ]:
        match = make_match(stage)
        rook = match.fighters[0]
        place(match, rook, *start)
        run(match, hold(direction, frames=30))
        assert getattr(rook.pos, axis) == pytest.approx(limit, abs=1e-5)


def test_jumping_onto_a_block() -> None:
    match = make_match(make_stage(["00200"]))
    rook = match.fighters[0]
    place(match, rook, 1.5, 0.5)
    run(match, [JUMP] * 4)
    run(match, hold(Dir8.SE, frames=8))  # a short drift carries the fighter over the block
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 2.0 and 2.0 <= rook.pos.x < 3.0


def test_small_steps_are_walked_up_and_down() -> None:
    assert STEP_HEIGHT == 0.25
    legend_stage = _stepped_stage(step=0.25)
    match = make_match(legend_stage)
    rook = match.fighters[0]
    place(match, rook, 0.5, 0.5)
    run(match, hold(Dir8.SE, Button.WALK, frames=20))
    assert rook.pos.x > 1.0 and rook.pos.z == 0.25 and rook.grounded
    run(match, hold(Dir8.NW, Button.WALK, frames=30))
    assert rook.pos.x < 1.0 and rook.pos.z == 0.0 and rook.grounded
    assert rook.state is StateId.WALK


def test_a_taller_step_blocks_going_up_and_falls_going_down() -> None:
    match = make_match(_stepped_stage(step=0.5))
    rook = match.fighters[0]
    place(match, rook, 0.5, 0.5)
    run(match, hold(Dir8.SE, Button.WALK, frames=20))
    assert rook.pos.x == pytest.approx(1.0 - RADIUS, abs=1e-5) and rook.pos.z == 0.0
    place(match, rook, 1.5, 0.5, facing=Dir8.NW)
    assert rook.pos.z == 0.5
    run(match, hold(Dir8.NW, Button.WALK, frames=12))
    assert rook.state is StateId.FALL


def _stepped_stage(step: float):  # type: ignore[no-untyped-def]
    from isofightr.sim.math3d import Vec2
    from isofightr.sim.stage import Cell, build_stage

    return build_stage(
        id="steps",
        display_name="Steps",
        tileset="grid",
        grid_rows=["0S"],
        legend={"S": Cell(top=step)},
        soft_platforms=[],
        spawns=[Vec2(0.5, 0.5)] * 4,
        respawn=Vec2(0.5, 0.5),
        blast_side=7.0,
        blast_top=14.0,
        blast_bottom=-8.0,
        camera_margin=4.0,
    )


# --- the island's side and underside ------------------------------------------------------


def test_the_island_side_is_a_wall_to_a_fighter_below_the_surface() -> None:
    match = make_match(make_stage(["000", "000", "000"]))
    rook = match.fighters[0]
    place(match, rook, -1.0, 1.5, z=-0.5)
    rook.ledge_cooldown = 10  # or it would catch the ledge instead
    rook.kb_vel = Vec3(1.5, 0.0, 0.0)
    run(match, neutral(1))
    assert rook.pos.x == pytest.approx(-RADIUS, abs=1e-5)


def test_feet_just_below_an_edge_come_out_on_top_of_it() -> None:
    """Within one step height of the top, a fighter is lifted onto the edge, not blocked."""
    match = make_match(make_stage(["000", "000", "000"]))
    rook = match.fighters[0]
    place(match, rook, -0.2, 1.5, z=-0.1)
    rook.kb_vel = Vec3(0.3, 0.0, 0.0)
    run(match, neutral(1))
    assert rook.pos.x > 0.0 and rook.pos.z == 0.0 and rook.grounded


def test_a_fighter_can_pass_under_the_island() -> None:
    stage = make_stage(["000", "000", "000"])
    match = make_match(stage)
    rook = match.fighters[0]
    assert stage.underside == -1.0
    place(match, rook, -1.0, 1.5, z=stage.underside - HEIGHT - 1.0)
    rook.vel = Vec3(0.07, 0.0, 0.3)
    rook.kb_vel = Vec3(0.3, 0.0, 0.0)
    run(match, neutral(4))
    assert rook.pos.x > 0.0, "moved in under the island"
    assert rook.pos.z + HEIGHT <= stage.underside + 1e-9, "head stays below the underside"


def test_rising_under_the_island_bonks_the_head_on_its_underside() -> None:
    stage = make_stage(["000", "000", "000"])
    match = make_match(stage)
    rook = match.fighters[0]
    place(match, rook, 1.5, 1.5, z=stage.underside - HEIGHT - 0.1)
    rook.vel = Vec3(0.0, 0.0, 0.3)
    run(match, neutral(1))
    assert rook.pos.z == pytest.approx(stage.underside - HEIGHT)
    assert rook.vel.z == 0.0
    run(match, neutral(10))
    assert rook.pos.z < stage.underside - HEIGHT, "then falls away again"
