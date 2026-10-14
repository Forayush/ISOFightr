"""Tests for the launch profile (how a hit freezes and launches its target, decision D-066)."""

from itertools import pairwise

import pytest

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.fighter import GroundKind, StateId
from isofightr.sim.launch_profile import (
    PROFILE_FRAMES,
    TABLE_FRAMES,
    LaunchProfile,
    launch_profile,
    profile_lines,
)
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3

ROOK = load_character("rook")
GRID = load_stage("training_grid")


@pytest.fixture(scope="module")
def profiles() -> dict[int, LaunchProfile]:
    return {
        percent: launch_profile(GRID, ROOK, ROOK, "fsmash", percent) for percent in (0, 60, 150)
    }


def test_the_freeze_and_hitstun_are_the_formulas_of_the_hit(
    profiles: dict[int, LaunchProfile],
) -> None:
    for profile in profiles.values():
        assert profile.freeze == kb.hitlag_frames(profile.damage)
        assert profile.hitstun == kb.hitstun_frames(profile.knockback)
        assert profile.rows[0].hitstun == profile.hitstun


def test_the_record_starts_on_the_launch_tick_and_covers_the_profile_frames(
    profiles: dict[int, LaunchProfile],
) -> None:
    for profile in profiles.values():
        assert [row.frame for row in profile.rows] == list(range(PROFILE_FRAMES + 1))
        assert profile.rows[0].distance == 0.0
        # The first frame moves the target at its launch speed, less one frame of decay and
        # of gravity.
        first = profile.row(1).speed
        assert first == pytest.approx(kb.launch_speed(profile.knockback), abs=0.02)


def test_a_weak_hit_flinches_and_a_strong_one_tumbles(profiles: dict[int, LaunchProfile]) -> None:
    assert profiles[0].knockback < c.TUMBLE_KB and profiles[0].state is StateId.FLINCH
    assert profiles[60].knockback >= c.TUMBLE_KB and profiles[60].state is StateId.TUMBLE
    assert profiles[60].rise > profiles[0].rise


def test_a_ko_keeps_the_place_the_target_was_ko_d_from(profiles: dict[int, LaunchProfile]) -> None:
    rows = profiles[150].rows
    gone = [row for row in rows if row.state is StateId.KO]
    assert gone, "Rook's forward smash KOs Rook at 150%"
    assert {row.distance for row in gone} == {gone[0].distance}
    assert all(row.speed == 0.0 for row in gone[1:])
    # A KO is not the knockback running out.
    spent = profiles[150].knockback_spent_frame
    assert spent is None or spent < gone[0].frame


def test_the_metrics_are_shares_and_frames_inside_the_record(
    profiles: dict[int, LaunchProfile],
) -> None:
    for profile in profiles.values():
        assert 0.0 < profile.early_share <= 1.0
        spent = profile.knockback_spent_frame
        assert spent is None or 1 <= spent <= PROFILE_FRAMES
        assert profile.peak_speed >= profile.row(1).speed


def test_the_text_has_two_summary_lines_a_header_and_a_row_per_table_frame(
    profiles: dict[int, LaunchProfile],
) -> None:
    lines = profile_lines(profiles[60])
    assert len(lines) == 3 + len(TABLE_FRAMES)
    assert lines[0].startswith("--- target at 60%: hit ")
    assert lines[-1].split()[0] == str(TABLE_FRAMES[-1])


def test_a_move_that_misses_is_an_error() -> None:
    with pytest.raises(ValueError):
        launch_profile(GRID, ROOK, ROOK, "jab1", 0, gap=5.0)


# --- the snap (decision D-066) --------------------------------------------------------------

D029_SPEED_PER_KB = 0.03 * c.PHYS_SCALE
D029_DECAY = 0.051 * c.PHYS_SCALE
"""The launch before the snap: what every KO percent was calibrated against (D-029)."""
KNOCKBACKS = range(20, 401, 20)


def glide(speed: float, loss: float) -> tuple[float, int]:
    """Return how far a speed losing ``loss`` per frame carries, and in how many frames."""
    travel, frames = 0.0, 0
    while speed > loss:
        speed -= loss
        travel += speed
        frames += 1
    return travel, frames


def flight(knockback: float, grounded: bool = False) -> tuple[list[float], float]:
    """Run the real knockback decay on a fighter launched sideways; return the speed on each
    frame and the distance covered."""
    match = Match.create(GRID, [ROOK, ROOK], rules=MatchRules(stocks=None))
    fighter = match.fighters[0]
    fighter.ground = GroundKind.CELL if grounded else GroundKind.NONE
    fighter.kb_vel = Vec3(kb.launch_speed(knockback), 0.0, 0.0)
    speeds, travel = [], 0.0
    while fighter.kb_vel.length() > 0.0:
        physics.decay_knockback(fighter)
        speeds.append(fighter.kb_vel.length())
        travel += fighter.kb_vel.length()
    return speeds, travel


def test_a_launch_slows_every_frame_and_stops() -> None:
    for knockback in KNOCKBACKS:
        speeds, _ = flight(knockback)
        assert all(later < earlier for earlier, later in pairwise(speeds[:-1]))
        assert speeds[-1] == 0.0


def test_the_snap_keeps_the_distance_of_every_launch_within_three_percent() -> None:
    """What every KO percent depends on: twice as fast, four times the decay, same reach.
    Each frame decays before it moves, so a launch falls short of the continuous distance by
    half its first step: within one old first step of the old distance (frame rounding)."""
    for knockback in KNOCKBACKS:
        before, frames_before = glide(knockback * D029_SPEED_PER_KB, D029_DECAY)
        _, travel = flight(knockback)
        step = knockback * D029_SPEED_PER_KB
        assert travel == pytest.approx(before, rel=0.03, abs=step), knockback
        assert len(flight(knockback)[0]) < frames_before * 0.6, "in about half the time"


def test_a_slide_on_the_ground_keeps_its_length() -> None:
    """Ground traction on knockback is scaled with the snap, so a flinch slides as far, give
    or take the frame rounding of the test above."""
    traction = ROOK.movement.traction
    for knockback in range(40, 121, 20):
        before, _ = glide(knockback * D029_SPEED_PER_KB, D029_DECAY + traction)
        _, travel = flight(knockback, grounded=True)
        assert travel == pytest.approx(before, abs=knockback * D029_SPEED_PER_KB), knockback


def test_the_knockback_is_spent_before_hitstun_ends() -> None:
    for knockback in range(int(c.TUMBLE_KB), 401, 10):
        speeds, _ = flight(knockback)
        peak = kb.launch_speed(knockback)
        spent = next(frame for frame, speed in enumerate(speeds, 1) if speed < 0.1 * peak)
        assert spent < kb.hitstun_frames(knockback), knockback


def test_rooks_forward_smash_meets_the_feel_targets(profiles: dict[int, LaunchProfile]) -> None:
    """D-066's targets as revised after the evaluation, at knockback 156 and 282."""
    at_60, at_150 = profiles[60], profiles[150]
    assert round(at_60.knockback) == 156 and round(at_150.knockback) == 282
    assert at_60.body_heights_per_second(at_60.peak_speed) >= 7.0
    assert at_150.body_heights_per_second(at_150.peak_speed) >= 13.0
    assert at_60.early_share >= 0.70 and at_150.early_share >= 0.55
    spent = at_60.knockback_spent_frame
    assert spent is not None and spent < at_60.hitstun
    # A 40 degree launch arcs: it rises at least 0.45 body, and peaks within 20 frames.
    assert at_60.rise >= 0.45 * at_60.body_height
    highest = max(at_60.rows, key=lambda row: row.height)
    assert highest.frame <= 20
