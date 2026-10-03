"""Tests for the ``python -m isofightr`` command-line flags (plan note 16, "CLI flags")."""

import re
import sys

import pytest

from isofightr.__main__ import EXIT_DATA_ERROR, build_parser, character_ids, main
from isofightr.config import DEFAULT_STAGE_ID, DEFAULT_WINDOW_SCALE
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.headless import run_headless

HASH = re.compile(r"state hash ([0-9a-f]{32})")


def test_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.scale is None and DEFAULT_WINDOW_SCALE == 2, "the saved setting decides"
    assert args.fullscreen is False
    assert args.frames is None
    assert args.debug is False
    assert args.stage is None and args.training is False
    assert DEFAULT_STAGE_ID == "sky_ruins"
    assert args.test_pattern is False
    assert (args.p1, args.p2, args.p3, args.p4) == ("rook", "rook", None, None)
    assert args.seed == 0
    assert args.headless is False


def test_window_and_smoke_run_flags() -> None:
    args = build_parser().parse_args(["--scale", "3", "--fullscreen", "--frames", "120", "--debug"])
    assert (args.scale, args.fullscreen, args.frames, args.debug) == (3, True, 120, True)


@pytest.mark.parametrize("argv", [["--scale", "0"], ["--frames", "0"], ["--scale", "big"]])
def test_invalid_values_are_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_stage_and_test_pattern_flags() -> None:
    args = build_parser().parse_args(["--stage", "training_grid"])
    assert args.stage == "training_grid"
    assert build_parser().parse_args(["--test-pattern"]).test_pattern is True


def test_unknown_stage_exits_with_a_clear_message_and_no_window(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--stage", "no_such_stage"]) == EXIT_DATA_ERROR
    error = capsys.readouterr().err
    assert "no such stage 'no_such_stage'" in error
    assert "sky_ruins" in error and "training_grid" in error


# --- players ------------------------------------------------------------------------------


def test_two_players_by_default_and_up_to_four() -> None:
    parser = build_parser()
    assert character_ids(parser.parse_args([]), parser) == ["rook", "rook"]
    four = parser.parse_args(["--p3", "rook", "--p4", "rook"])
    assert character_ids(four, parser) == ["rook"] * 4


def test_player_slots_must_be_filled_in_order(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        character_ids(parser.parse_args(["--p4", "rook"]), parser)
    assert "--p3 before --p4" in capsys.readouterr().err


def test_unknown_character_exits_with_a_clear_message(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--p2", "nobody", "--headless", "--frames", "10"]) == EXIT_DATA_ERROR
    assert (
        "no such character 'nobody' (available: bramble, mote, rook, zephyr)"
        in capsys.readouterr().err
    )


# --- headless -----------------------------------------------------------------------------


def test_headless_needs_a_frame_count(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--headless"])
    assert "--headless needs --frames N" in capsys.readouterr().err


def test_headless_run_reports_and_never_imports_arcade(capsys: pytest.CaptureFixture[str]) -> None:
    arcade_loaded_before = "arcade" in sys.modules
    assert main(["--headless", "--frames", "300", "--stage", "training_grid"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("300 ticks on training_grid with 2 fighters: ")
    assert "ms/tick" in output and HASH.search(output)
    assert ("arcade" in sys.modules) == arcade_loaded_before


def test_headless_is_reproducible_and_seed_dependent(capsys: pytest.CaptureFixture[str]) -> None:
    def state_hash(*extra: str) -> str:
        assert main(["--headless", "--frames", "400", *extra]) == 0
        found = HASH.search(capsys.readouterr().out)
        assert found is not None
        return found.group(1)

    assert state_hash() == state_hash()
    assert state_hash("--seed", "5") == state_hash("--seed", "5")
    assert state_hash("--seed", "5") != state_hash()
    assert state_hash("--p3", "rook") != state_hash()


def test_headless_report_numbers() -> None:
    report = run_headless(load_stage("sky_ruins"), [load_character("rook")] * 2, seed=3, ticks=500)
    assert (report.stage_id, report.fighters, report.ticks) == ("sky_ruins", 2, 500)
    assert report.seconds > 0 and report.ms_per_tick == report.seconds * 1000 / 500
    assert report.knockouts >= 0 and len(report.state_hash) == 32


def test_sim_tick_stays_well_inside_its_budget() -> None:
    """Plan note 02: a sim tick with 4 fighters must take at most 3 ms. It takes about 0.06 ms;
    the generous limit here only catches an accidental order-of-magnitude slowdown."""
    report = run_headless(load_stage("sky_ruins"), [load_character("rook")] * 4, seed=1, ticks=3000)
    assert report.ms_per_tick < 1.0


def test_cpu_flags_name_a_player_and_a_level(capsys: pytest.CaptureFixture[str]) -> None:
    args = build_parser().parse_args(["--cpu", "2:7", "--cpu", "1:9"])
    assert args.cpu == [(2, 7), (1, 9)]
    for bad in ("2", "2:10", "5:3", "x:1"):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--cpu", bad])
    with pytest.raises(SystemExit):
        main(["--cpu", "3:5", "--headless", "--frames", "5"])
    assert "only 2 players" in capsys.readouterr().err


def test_headless_cpus_are_reproducible(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["--headless", "--frames", "600", "--cpu", "1:9", "--cpu", "2:4", "--seed", "3"]
    assert main(argv) == 0
    first = HASH.search(capsys.readouterr().out)
    assert main(argv) == 0
    second = HASH.search(capsys.readouterr().out)
    assert first and second and first.group(1) == second.group(1)
