"""Tests for the ``python -m isofightr`` command-line flags (plan note 16, "CLI flags")."""

import pytest

from isofightr.__main__ import EXIT_DATA_ERROR, build_parser, main
from isofightr.config import DEFAULT_STAGE_ID, DEFAULT_WINDOW_SCALE


def test_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.scale == DEFAULT_WINDOW_SCALE
    assert args.fullscreen is False
    assert args.frames is None
    assert args.debug is False
    assert args.stage == DEFAULT_STAGE_ID == "sky_ruins"
    assert args.test_pattern is False


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
