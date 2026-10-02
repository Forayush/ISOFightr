"""Scenario tests for blast-zone KOs, respawn and pushboxes (plan note 04)."""

import pytest

from helpers import hold, make_match, neutral, place, run, run_until
from isofightr.sim.constants import (
    PUSH_SPEED,
    RESPAWN_DELAY_FRAMES,
    RESPAWN_INVINCIBLE_FRAMES,
    REVIVAL_HEIGHT,
    REVIVAL_MAX_FRAMES,
    REVIVAL_SPACING,
)
from isofightr.sim.events import KoEvent, RespawnEvent
from isofightr.sim.fighter import GroundKind, StateId
from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.math3d import Vec3

JUMP = InputFrame(held=Button.JUMP)


def ko_events(match) -> list[KoEvent]:  # type: ignore[no-untyped-def]
    return [event for event in match.events if isinstance(event, KoEvent)]


# --- blast zones --------------------------------------------------------------------------


def test_falling_below_the_stage_is_a_ko() -> None:
    match = make_match()
    rook = match.fighters[0]
    place(match, rook, 13.0, 6.0, z=0.0)  # past the +x edge of Training Grid
    ticks = run_until(match, rook, StateId.KO)
    [event] = ko_events(match)
    assert event.player == 0
    assert event.normal == Vec3(0.0, 0.0, -1.0)
    assert event.position.z == match.stage.blast_zone.z_min == -8.0
    assert event.stocks_left == 2
    assert rook.stocks == 2
    assert not rook.in_play
    assert ticks > 40, "falling 8 units takes a while"


def test_ko_below_happens_on_the_first_frame_past_the_zone() -> None:
    match = make_match()
    rook = match.fighters[0]
    place(match, rook, 13.0, 6.0, z=-7.995)
    rook.vel = Vec3(0.0, 0.0, -0.18)
    run(match, neutral(1))
    assert rook.state is StateId.KO


@pytest.mark.parametrize(
    ("position", "normal"),
    [
        (Vec3(19.5, 6.0, 0.0), Vec3(1.0, 0.0, 0.0)),
        (Vec3(-7.5, 6.0, 0.0), Vec3(-1.0, 0.0, 0.0)),
        (Vec3(6.0, 19.5, 0.0), Vec3(0.0, 1.0, 0.0)),
        (Vec3(6.0, -7.5, 0.0), Vec3(0.0, -1.0, 0.0)),
        (Vec3(6.0, 6.0, 14.5), Vec3(0.0, 0.0, 1.0)),
    ],
)
def test_every_face_of_the_blast_zone_kos(position: Vec3, normal: Vec3) -> None:
    match = make_match()
    rook = match.fighters[0]
    place(match, rook, position.x, position.y, z=position.z)
    run(match, neutral(1))
    [event] = ko_events(match)
    assert event.normal == normal
    assert match.stage.blast_zone.contains(event.position)


def test_inside_the_blast_zone_is_safe() -> None:
    match = make_match()
    rook = match.fighters[0]
    place(match, rook, 18.5, 6.0, z=5.0)
    run(match, neutral(1))
    assert rook.in_play and ko_events(match) == []


def test_the_other_fighter_is_untouched_by_a_ko() -> None:
    match = make_match()
    first, second = match.fighters
    place(match, first, 13.0, 6.0, z=-7.995)
    run(match, neutral(5))
    assert first.state is StateId.KO
    assert second.state is StateId.IDLE and second.stocks == 3


# --- respawn ------------------------------------------------------------------------------


def knocked_out_match():  # type: ignore[no-untyped-def]
    match = make_match()
    rook = match.fighters[0]
    rook.damage = 87.0
    place(match, rook, 13.0, 6.0, z=-7.995, damage=87.0)
    run(match, neutral(1))
    assert rook.state is StateId.KO
    return match, rook


def test_respawn_on_the_revival_platform_after_sixty_frames() -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES - 1))
    assert rook.state is StateId.KO
    run(match, neutral(1))
    assert rook.state is StateId.REVIVAL
    assert rook.ground is GroundKind.REVIVAL
    assert rook.damage == 0.0
    assert rook.invincible
    assert match.events == [RespawnEvent(0, rook.pos)]
    centre = match.stage.respawn_point()
    assert rook.pos.z == centre.z + REVIVAL_HEIGHT
    # Two fighters: P1's platform sits half a spacing to the screen-left of the centre.
    offset = Dir8.E.world * (-0.5 * REVIVAL_SPACING)
    assert (rook.pos.x, rook.pos.y) == pytest.approx((centre.x + offset.x, centre.y + offset.y))


def test_the_revival_platform_holds_the_fighter_until_it_acts() -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES + 100))
    assert rook.state is StateId.REVIVAL
    height = rook.pos.z
    run(match, neutral(50))
    assert rook.pos.z == height


def test_the_revival_platform_drops_the_fighter_after_three_hundred_frames() -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES))
    run(match, neutral(REVIVAL_MAX_FRAMES - 1))
    assert rook.state is StateId.REVIVAL
    run(match, neutral(1))
    assert rook.state is StateId.FALL
    assert rook.invincible_frames == RESPAWN_INVINCIBLE_FRAMES


@pytest.mark.parametrize(
    "frame",
    [
        InputFrame(move=Dir8.E.world),
        InputFrame(vertical=-1),
        InputFrame(held=Button.ATTACK),
        InputFrame(held=Button.SHIELD),
    ],
)
def test_any_input_leaves_the_revival_platform(frame: InputFrame) -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES + 10))
    run(match, [frame])
    assert rook.state is StateId.FALL
    assert not rook.fast_falling


def test_jumping_off_the_revival_platform() -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES + 10))
    start = rook.pos.z
    run(match, [JUMP] * 4)
    assert rook.state is StateId.JUMP
    assert rook.pos.z > start
    assert rook.air_jumps_left == 1


def test_invincibility_lasts_one_hundred_and_twenty_frames_after_leaving() -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES + 10))
    run(match, hold(Dir8.E, frames=1))
    assert rook.invincible_frames == RESPAWN_INVINCIBLE_FRAMES
    run(match, neutral(RESPAWN_INVINCIBLE_FRAMES - 1))
    assert rook.invincible
    run(match, neutral(1))
    assert not rook.invincible


def test_the_dropped_fighter_lands_back_on_the_stage() -> None:
    match, rook = knocked_out_match()
    run(match, neutral(RESPAWN_DELAY_FRAMES + 10))
    run(match, hold(vertical=-1, frames=1))
    run_until(match, rook, StateId.LAND)
    assert rook.pos.z == 0.0 and rook.ground is GroundKind.CELL


def test_out_of_stocks_stays_out() -> None:
    match = make_match(stocks=1)
    rook = match.fighters[0]
    place(match, rook, 13.0, 6.0, z=-7.995)
    run(match, neutral(1))
    assert rook.stocks == 0 and rook.eliminated
    run(match, neutral(RESPAWN_DELAY_FRAMES + 200))
    assert rook.state is StateId.KO


def test_infinite_stocks_never_run_out() -> None:
    match = make_match(stocks=None)
    rook = match.fighters[0]
    for _ in range(3):
        place(match, rook, 13.0, 6.0, z=-7.995)
        run(match, neutral(1))
        [event] = ko_events(match)
        assert event.stocks_left is None
        run(match, neutral(RESPAWN_DELAY_FRAMES))
        assert rook.state is StateId.REVIVAL
    assert rook.stocks is None and not rook.eliminated


# --- pushboxes ----------------------------------------------------------------------------


def test_overlapping_grounded_fighters_push_each_other_apart() -> None:
    match = make_match()
    first, second = match.fighters
    place(match, first, 6.0, 6.0)
    place(match, second, 6.2, 6.0)
    run(match, neutral(1))
    assert first.pos.x == pytest.approx(6.0 - PUSH_SPEED)
    assert second.pos.x == pytest.approx(6.2 + PUSH_SPEED)
    run(match, neutral(60))
    gap = second.pos.x - first.pos.x
    assert gap == pytest.approx(0.6, abs=2 * PUSH_SPEED), "they stop once the bodies clear"
    assert first.pos.y == second.pos.y == 6.0


def test_fighters_exactly_on_top_of_each_other_separate_deterministically() -> None:
    match = make_match()
    first, second = match.fighters
    place(match, first, 6.0, 6.0)
    place(match, second, 6.0, 6.0)
    run(match, neutral(1))
    assert first.pos.x < 6.0 < second.pos.x


def test_fighters_can_run_through_each_other() -> None:
    match = make_match()
    first, second = match.fighters
    place(match, first, 4.0, 6.0)
    place(match, second, 6.0, 6.0)
    run(match, hold(Dir8.SE, frames=40))
    assert first.pos.x > second.pos.x


def test_airborne_or_distant_fighters_are_not_pushed() -> None:
    match = make_match()
    first, second = match.fighters
    place(match, first, 6.0, 6.0)
    place(match, second, 6.2, 6.0, z=3.0)
    run(match, neutral(1))
    assert first.pos.x == 6.0
    place(match, second, 7.0, 6.0)
    run(match, neutral(1))
    assert (first.pos.x, second.pos.x) == (6.0, 7.0)


def test_a_fighter_can_be_pushed_off_an_edge() -> None:
    match = make_match()
    first, second = match.fighters
    place(match, first, 11.9, 6.0)
    place(match, second, 12.13, 6.0, z=0.0)
    run(match, neutral(3))
    run(match, neutral(30))
    assert second.state in (StateId.FALL, StateId.KO) or not second.grounded
