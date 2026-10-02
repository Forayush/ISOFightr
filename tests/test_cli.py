"""Tests for the ``python -m isofightr`` command-line flags (plan note 16, "CLI flags")."""

import pytest

from isofightr.__main__ import build_parser
from isofightr.config import DEFAULT_WINDOW_SCALE


def test_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.scale == DEFAULT_WINDOW_SCALE
    assert args.fullscreen is False
    assert args.frames is None
    assert args.debug is False


def test_window_and_smoke_run_flags() -> None:
    args = build_parser().parse_args(["--scale", "3", "--fullscreen", "--frames", "120", "--debug"])
    assert (args.scale, args.fullscreen, args.frames, args.debug) == (3, True, 120, True)


@pytest.mark.parametrize("argv", [["--scale", "0"], ["--frames", "0"], ["--scale", "big"]])
def test_invalid_values_are_rejected(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)
