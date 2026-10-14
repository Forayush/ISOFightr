"""Tests for the launch profile (how a hit freezes and launches its target, decision D-066)."""

import pytest

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.fighter import StateId
from isofightr.sim.launch_profile import (
    PROFILE_FRAMES,
    TABLE_FRAMES,
    LaunchProfile,
    launch_profile,
    profile_lines,
)

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
