"""Scenario tests for ground and air movement (plan note 04, with Rook's stats).

Every test scripts ``InputFrame``s against a real ``Match`` on Training Grid (flat 12x12).
Frame counts are exact: frames are 1-indexed and the tick an input arrives is frame 1.
"""

import pytest

from helpers import hold, make_match, neutral, place, run, run_until
from isofightr.sim.events import JumpEvent, JumpKind, LandEvent
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.match import Match
from isofightr.sim.math3d import Vec3

WALK_SPEED, DASH_SPEED, RUN_SPEED = 0.060, 0.105, 0.100
DASH_FRAMES, JUMPSQUAT, LAND_LAG = 12, 3, 3
FULL_HOP_VZ, SHORT_HOP_VZ, DOUBLE_JUMP_VZ = 0.300, 0.180, 0.280
GRAVITY, MAX_FALL, FAST_FALL = 0.012, 0.180, 0.260
AIR_SPEED, TRACTION = 0.070, 0.006

JUMP = InputFrame(held=Button.JUMP)


@pytest.fixture
def match() -> Match:
    """Two Rooks on Training Grid; P1 is moved to the middle, facing south-east."""
    created = make_match()
    place(created, created.fighters[0], 6.0, 6.0)
    return created


@pytest.fixture
def rook(match: Match) -> Fighter:
    return match.fighters[0]


def speed(fighter: Fighter) -> float:
    return fighter.vel.xy.length()


def apex(match: Match, fighter: Fighter) -> float:
    """Tick with neutral input until the fighter stops rising; return the peak height."""
    highest = fighter.pos.z
    while fighter.vel.z > 0 or fighter.grounded:
        match.tick(neutral(len(match.fighters)))
        highest = max(highest, fighter.pos.z)
    return highest


# --- standing and walking -----------------------------------------------------------------


def test_fighters_start_idle_on_their_spawns_facing_the_centre() -> None:
    match = make_match()
    first, second = match.fighters
    assert (first.state, first.ground) == (StateId.IDLE, GroundKind.CELL)
    assert first.pos == match.stage.spawn_point(0)
    assert (first.facing, second.facing) == (Dir8.SE, Dir8.NW)
    assert (first.stocks, first.damage, first.air_jumps_left) == (3, 0.0, 1)


def test_no_input_changes_nothing(match: Match, rook: Fighter) -> None:
    before = rook.pos
    run(match, neutral(120))
    assert (rook.pos, rook.state, rook.vel) == (before, StateId.IDLE, Vec3())


def test_walk_modifier_walks_at_walk_speed(match: Match, rook: Fighter) -> None:
    start = rook.pos
    run(match, hold(Dir8.SE, Button.WALK, frames=30))
    assert rook.state is StateId.WALK
    assert speed(rook) == pytest.approx(WALK_SPEED)
    assert rook.pos.x - start.x == pytest.approx(30 * WALK_SPEED)
    assert rook.pos.y == start.y


def test_partial_tilt_walks_slower(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=5, magnitude=0.1))
    run(match, hold(Dir8.SE, frames=20, magnitude=0.5))
    assert rook.state is StateId.WALK
    assert speed(rook) == pytest.approx(WALK_SPEED * 0.5)


def test_walking_stops_at_once_when_the_stick_is_released(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, Button.WALK, frames=10))
    run(match, neutral(1))
    assert rook.state is StateId.IDLE
    # Traction eats walk speed over the next frames; Rook slides for 0.06 / 0.006 = 10.
    run(match, neutral(9))
    assert speed(rook) == pytest.approx(0.0, abs=1e-12)


def test_walk_faces_and_moves_in_each_of_the_eight_directions(match: Match, rook: Fighter) -> None:
    for direction in Dir8:
        place(match, rook, 6.0, 6.0, facing=direction)
        start = rook.pos
        run(match, hold(direction, Button.WALK, frames=10))
        moved = (rook.pos - start).xy
        assert rook.facing is direction
        assert moved.normalized().dot(direction.world) == pytest.approx(1.0)


def test_walking_up_to_ninety_degrees_off_turns_instantly(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SW, Button.WALK, frames=2))  # 90 degrees from south-east
    assert rook.state is StateId.WALK
    assert rook.facing is Dir8.SW


def test_tilting_behind_takes_a_three_frame_turnaround(match: Match, rook: Fighter) -> None:
    states = []
    for _ in range(5):
        run(match, hold(Dir8.NW, Button.WALK, frames=1))
        states.append(rook.state)
    assert states == [StateId.TURN] * 3 + [StateId.WALK] * 2
    assert rook.facing is Dir8.NW


# --- dash and run -------------------------------------------------------------------------


def test_a_direction_press_dashes_for_twelve_frames_then_runs(match: Match, rook: Fighter) -> None:
    start = rook.pos
    states = []
    for _ in range(DASH_FRAMES + 3):
        run(match, hold(Dir8.SE, frames=1))
        states.append(rook.state)
    assert states == [StateId.DASH] * DASH_FRAMES + [StateId.RUN] * 3
    travelled = rook.pos.x - start.x
    assert travelled == pytest.approx(DASH_FRAMES * DASH_SPEED + 3 * RUN_SPEED)


def test_dash_moves_on_the_very_first_frame(match: Match, rook: Fighter) -> None:
    start = rook.pos
    run(match, hold(Dir8.SE, frames=1))
    assert rook.pos.x - start.x == pytest.approx(DASH_SPEED)


def test_run_speed(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=40))
    before = rook.pos
    run(match, hold(Dir8.SE, frames=10))
    assert rook.state is StateId.RUN
    assert speed(rook) == pytest.approx(RUN_SPEED)
    assert (rook.pos - before).length() == pytest.approx(10 * RUN_SPEED)


def test_run_speed_is_the_same_in_every_direction(match: Match, rook: Fighter) -> None:
    for direction in (Dir8.E, Dir8.N, Dir8.SW):
        place(match, rook, 6.0, 6.0, facing=direction)
        run(match, hold(direction, frames=20))
        assert speed(rook) == pytest.approx(RUN_SPEED)
        run(match, neutral(40))


def test_releasing_a_dash_before_it_ends_does_not_run(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=4))
    run(match, neutral(DASH_FRAMES - 4))
    assert rook.state is StateId.DASH, "the dash burst always completes"
    run(match, neutral(1))
    assert rook.state is StateId.IDLE


def test_releasing_the_stick_while_running_skids_to_a_stop(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=30))
    run(match, neutral(1))
    assert rook.state is StateId.SKID
    assert speed(rook) == pytest.approx(RUN_SPEED - TRACTION)
    ticks = run_until(match, rook, StateId.IDLE)
    # 0.100 / 0.006 = 16.67: stopped on the 17th frame of sliding, idle the frame after.
    assert ticks == 17
    assert speed(rook) == 0.0


def test_reversing_a_run_skids_through_a_run_turnaround(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=30))
    turning_at = rook.pos.x
    run(match, hold(Dir8.NW, frames=1))
    assert rook.state is StateId.RUN_TURN
    assert rook.facing is Dir8.NW
    assert rook.vel.x > 0, "momentum still carries forward"
    run(match, hold(Dir8.NW, frames=11))
    assert rook.state is StateId.RUN_TURN
    assert rook.pos.x > turning_at
    run(match, hold(Dir8.NW, frames=1))
    assert rook.state is StateId.RUN
    assert rook.vel.x == pytest.approx(-RUN_SPEED)


def test_running_steers_without_slowing(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=20))
    run(match, hold(Dir8.S, frames=5))
    assert rook.state is StateId.RUN
    assert rook.facing is Dir8.S
    assert speed(rook) == pytest.approx(RUN_SPEED)
    assert rook.vel.xy.normalized().dot(Dir8.S.world) == pytest.approx(1.0)


def test_dash_dance_reverses_instantly(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=5))
    run(match, hold(Dir8.NW, frames=1))
    assert rook.state is StateId.DASH
    assert rook.state_frame == 1
    assert rook.facing is Dir8.NW
    assert rook.vel.x == pytest.approx(-DASH_SPEED)


def test_dashing_backward_from_standing_is_immediate(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.NW, frames=1))
    assert rook.state is StateId.DASH
    assert rook.facing is Dir8.NW


def test_the_walk_modifier_suppresses_dashing(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, Button.WALK, frames=20))
    assert rook.state is StateId.WALK


# --- jumping ------------------------------------------------------------------------------


def test_jumpsquat_lasts_three_frames_then_the_fighter_is_airborne(
    match: Match, rook: Fighter
) -> None:
    grounded = []
    for _ in range(JUMPSQUAT + 1):
        run(match, [JUMP])
        grounded.append((rook.state, rook.grounded))
    assert grounded == [(StateId.JUMP_SQUAT, True)] * JUMPSQUAT + [(StateId.JUMP, False)]
    assert rook.vel.z == pytest.approx(FULL_HOP_VZ - GRAVITY)


def test_full_hop_apex(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    peak = apex(match, rook)
    # Gravity is applied before each move: 24 rising frames, sum of 0.288, 0.276 ... 0.012.
    assert peak == pytest.approx(3.6)
    assert peak == pytest.approx(3.75, abs=0.2), "the plan's continuous estimate"


def test_short_hop_when_jump_is_released_during_jumpsquat(match: Match, rook: Fighter) -> None:
    run(match, [JUMP])
    run(match, neutral(JUMPSQUAT))
    assert rook.state is StateId.JUMP
    assert rook.vel.z == pytest.approx(SHORT_HOP_VZ - GRAVITY)
    assert isinstance(match.events[0], JumpEvent) and match.events[0].kind is JumpKind.SHORT_HOP
    assert apex(match, rook) == pytest.approx(1.26)


def test_full_hop_event(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    assert match.events == [JumpEvent(0, JumpKind.FULL_HOP, Vec3(6.0, 6.0, 0.0))]


def test_jump_becomes_fall_at_the_apex(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    while rook.vel.z > 0:
        assert rook.state is StateId.JUMP
        run(match, neutral(1))
    run(match, neutral(1))
    assert rook.state is StateId.FALL


def test_double_jump_once(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    run(match, neutral(10))
    run(match, [JUMP])
    assert rook.state is StateId.DOUBLE_JUMP
    assert rook.vel.z == pytest.approx(DOUBLE_JUMP_VZ - GRAVITY)
    assert rook.air_jumps_left == 0
    assert match.events == [JumpEvent(0, JumpKind.AIR, rook.pos - Vec3(0, 0, rook.vel.z))]
    run(match, neutral(3))
    rising = rook.vel.z
    run(match, [JUMP])
    assert rook.vel.z == pytest.approx(rising - GRAVITY), "no third jump"


def test_double_jump_redirects_drift_instantly(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, Button.JUMP, frames=JUMPSQUAT + 10))
    assert rook.vel.x > 0
    run(match, neutral(1))
    run(match, hold(Dir8.NW, Button.JUMP, frames=1))
    assert rook.vel.x == pytest.approx(-AIR_SPEED)


def test_running_jump_carries_momentum_clamped_to_air_speed(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, frames=20))
    run(match, hold(Dir8.SE, Button.JUMP, frames=JUMPSQUAT + 1))
    assert rook.state is StateId.JUMP
    assert speed(rook) == pytest.approx(AIR_SPEED)
    assert RUN_SPEED > AIR_SPEED


def test_standing_jump_goes_straight_up(match: Match, rook: Fighter) -> None:
    start = rook.pos
    run(match, [JUMP] * 20)
    assert (rook.pos.x, rook.pos.y) == (start.x, start.y)


def test_air_drift_accelerates_to_a_circular_cap(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    run(match, hold(Dir8.S, frames=1))  # a world diagonal: both x and y change
    assert speed(rook) == pytest.approx(0.006)
    run(match, hold(Dir8.S, frames=20))
    assert speed(rook) == pytest.approx(AIR_SPEED)
    assert rook.vel.x == pytest.approx(AIR_SPEED / 2**0.5), "capped as a circle, not per axis"


def test_air_friction_slows_drift_when_the_stick_is_neutral(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    run(match, hold(Dir8.SE, frames=15))
    drifting = speed(rook)
    run(match, neutral(5))
    assert speed(rook) == pytest.approx(drifting - 5 * 0.002)


def test_facing_does_not_change_in_the_air(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    run(match, hold(Dir8.NW, frames=10))
    assert rook.facing is Dir8.SE


def test_fall_speed_is_capped(match: Match, rook: Fighter) -> None:
    place(match, rook, 6.0, 6.0, z=10.0)
    run(match, neutral(30))
    assert rook.vel.z == pytest.approx(-MAX_FALL)


def test_fast_fall_speed(match: Match, rook: Fighter) -> None:
    place(match, rook, 6.0, 6.0, z=10.0)
    run(match, neutral(3))
    run(match, hold(vertical=-1, frames=1))
    assert rook.fast_falling
    assert rook.vel.z == pytest.approx(-FAST_FALL)
    run(match, neutral(5))
    assert rook.vel.z == pytest.approx(-FAST_FALL), "it stays fast without holding down"


def test_fast_fall_needs_the_apex(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    run(match, hold(vertical=-1, frames=1))
    assert not rook.fast_falling, "still rising"
    run(match, hold(vertical=-1, frames=40))
    assert not rook.fast_falling, "holding down from before the apex is not a fresh tap"
    assert rook.vel.z < 0
    run(match, neutral(1))
    run(match, hold(vertical=-1, frames=1))
    assert rook.fast_falling


def test_fast_fall_tapped_just_before_the_apex_is_buffered(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    while rook.vel.z > 3 * GRAVITY:
        run(match, neutral(1))
    run(match, hold(vertical=-1, frames=1))
    assert not rook.fast_falling
    run(match, neutral(4))
    assert rook.fast_falling


# --- landing ------------------------------------------------------------------------------


def test_landing_lag_is_three_frames(match: Match, rook: Fighter) -> None:
    place(match, rook, 6.0, 6.0, z=1.0)
    ticks = run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 0.0 and rook.grounded
    landing = match.events[0]
    assert isinstance(landing, LandEvent) and landing.fall_speed > 0
    states = []
    for _ in range(LAND_LAG + 1):
        run(match, neutral(1))
        states.append(rook.state)
    assert states == [StateId.LAND] * (LAND_LAG - 1) + [StateId.IDLE] * 2
    assert ticks > 0


def test_jump_buffered_during_landing_lag_comes_out_on_the_first_free_frame(
    match: Match, rook: Fighter
) -> None:
    place(match, rook, 6.0, 6.0, z=1.0)
    run_until(match, rook, StateId.LAND)
    run(match, [JUMP])
    assert rook.state is StateId.LAND
    run(match, neutral(LAND_LAG - 1))
    assert rook.state is StateId.JUMP_SQUAT


def test_landing_restores_the_air_jump_and_clears_fast_fall(match: Match, rook: Fighter) -> None:
    run(match, [JUMP] * (JUMPSQUAT + 1))
    run(match, neutral(5))
    run(match, [JUMP])
    run(match, neutral(30))
    run(match, hold(vertical=-1, frames=1))
    assert rook.air_jumps_left == 0 and rook.fast_falling
    run_until(match, rook, StateId.LAND)
    assert rook.air_jumps_left == 1 and not rook.fast_falling


def test_a_very_fast_fall_does_not_tunnel_through_the_floor(match: Match, rook: Fighter) -> None:
    place(match, rook, 6.0, 6.0, z=0.3)
    rook.kb_vel = Vec3(0.0, 0.0, -5.0)  # far faster than any fall: a spike's knockback
    run(match, neutral(1))
    assert rook.pos.z == 0.0 and rook.grounded


def test_landing_on_a_cell_boundary_is_deterministic(match: Match, rook: Fighter) -> None:
    place(match, rook, 6.0, 6.0, z=0.5)
    run_until(match, rook, StateId.LAND)
    assert rook.pos == Vec3(6.0, 6.0, 0.0)


# --- edges --------------------------------------------------------------------------------


def test_walking_off_an_edge_falls(match: Match, rook: Fighter) -> None:
    place(match, rook, 11.5, 6.0)
    run(match, hold(Dir8.SE, Button.WALK, frames=7))
    assert rook.state is StateId.WALK, "still on the last cell"
    run(match, hold(Dir8.SE, Button.WALK, frames=10))
    assert rook.state is StateId.FALL
    assert not rook.grounded
    assert rook.pos.x > 12.0 and rook.pos.z < 0.0


def test_the_feet_may_hang_slightly_past_an_edge(match: Match, rook: Fighter) -> None:
    """Edge tolerance: half the body radius (0.15) past the edge still counts as standing."""
    place(match, rook, 12.1, 6.0, z=0.0)
    run(match, neutral(5))
    assert rook.grounded and rook.pos.z == 0.0
    place(match, rook, 12.2, 6.0, z=0.0)
    run(match, neutral(2))
    assert not rook.grounded


def test_running_off_an_edge_keeps_the_air_jump(match: Match, rook: Fighter) -> None:
    place(match, rook, 10.5, 6.0)
    run(match, hold(Dir8.SE, frames=30))
    assert rook.state is StateId.FALL
    assert rook.air_jumps_left == 1
    run(match, [JUMP])
    assert rook.state is StateId.DOUBLE_JUMP


def test_fighters_do_not_stop_at_edges(match: Match, rook: Fighter) -> None:
    place(match, rook, 11.0, 6.0)
    run(match, hold(Dir8.SE, frames=12))
    assert rook.pos.x > 12.15 and not rook.grounded
