"""``python -m isofightr`` entrypoint and CLI flags.

Implements the "CLI flags" table in the plan note "16 - Testing Debug and Tooling". Built so
far: the window options (M0), ``--stage`` (M1), ``--p1`` to ``--p4``, ``--seed`` and
``--headless`` (M2), ``--training`` (M3) and ``--battle`` (M6: without it, ``--stage`` or
``--training``, the game starts at the title screen). ``--cpu``, ``--replay`` and ``--record`` are
added by the milestones that build what they control.
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from isofightr.config import (
    DEFAULT_CHARACTER_ID,
    DEFAULT_PLAYER_COUNT,
    DEFAULT_STAGE_ID,
    DEFAULT_WINDOW_SCALE,
    MAX_PLAYERS,
    MIN_WINDOW_SCALE,
    TRAINING_STAGE_ID,
)
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.data.validation import DataError
from isofightr.headless import run_headless

EXIT_DATA_ERROR = 2


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or greater, got {value}")
    return value


def _window_scale(text: str) -> int:
    value = int(text)
    if value < MIN_WINDOW_SCALE:
        raise argparse.ArgumentTypeError(f"must be {MIN_WINDOW_SCALE} or greater, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser for ``python -m isofightr``."""
    parser = argparse.ArgumentParser(
        prog="isofightr",
        description="ISOFightr: an isometric platform fighter.",
    )
    parser.add_argument(
        "--scale",
        type=_window_scale,
        default=DEFAULT_WINDOW_SCALE,
        metavar="N",
        help="integer window scale of the 640x360 native buffer (default: %(default)s)",
    )
    parser.add_argument("--fullscreen", action="store_true", help="start in fullscreen")
    parser.add_argument(
        "--stage",
        default=None,
        metavar="ID",
        help=f"stage to load from assets/stages (default: {DEFAULT_STAGE_ID}, or "
        f"{TRAINING_STAGE_ID} with --training)",
    )
    parser.add_argument(
        "--battle",
        action="store_true",
        help="skip the menus and start a match at once with --p1 to --p4 and --stage "
        "(endless stocks). --stage and --training do the same",
    )
    parser.add_argument(
        "--training",
        action="store_true",
        help="training mode: player 2 is a dummy; see the on-screen help for the tools",
    )
    for slot in range(1, MAX_PLAYERS + 1):
        default = DEFAULT_CHARACTER_ID if slot <= DEFAULT_PLAYER_COUNT else None
        parser.add_argument(
            f"--p{slot}",
            default=default,
            metavar="ID",
            help=f"character for player {slot}"
            + (" (default: %(default)s)" if default else " (default: not playing)"),
        )
    parser.add_argument(
        "--seed", type=int, default=0, metavar="N", help="match seed (default: %(default)s)"
    )
    parser.add_argument(
        "--test-pattern",
        action="store_true",
        help="show the pixel test pattern instead of a stage (checks display scaling)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run the simulation without a window on seeded random input; needs --frames",
    )
    parser.add_argument(
        "--frames",
        type=_positive_int,
        default=None,
        metavar="N",
        help="stop automatically after N simulation ticks",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    return parser


def skips_menus(args: argparse.Namespace) -> bool:
    """Return whether the command line asks to go straight into a match."""
    return bool(args.battle or args.training or args.stage is not None)


def stage_id(args: argparse.Namespace) -> str:
    """Return the stage to load: ``--stage``, or the default for the chosen mode."""
    if args.stage is not None:
        return str(args.stage)
    return TRAINING_STAGE_ID if args.training else DEFAULT_STAGE_ID


def character_ids(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    """Return the chosen character ids in player order. Slots must be filled without gaps."""
    slots = [getattr(args, f"p{slot}") for slot in range(1, MAX_PLAYERS + 1)]
    chosen = [character for character in slots if character is not None]
    if slots[: len(chosen)] != chosen:
        parser.error("player slots must be filled in order: use --p3 before --p4")
    return chosen


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the game. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    if args.headless and args.frames is None:
        parser.error("--headless needs --frames N")
    if args.headless and args.test_pattern:
        parser.error("--headless and --test-pattern cannot be combined")
    if args.training and (args.headless or args.test_pattern):
        parser.error("--training needs the normal game window")

    # Data is loaded first, so a bad --stage or --p1 is reported without opening a window.
    try:
        stage = None if args.test_pattern else load_stage(stage_id(args))
        characters = [load_character(name) for name in character_ids(args, parser)]
    except DataError as error:
        print(f"isofightr: {error}", file=sys.stderr)
        return EXIT_DATA_ERROR

    if args.headless:
        assert stage is not None
        print(run_headless(stage, characters, args.seed, args.frames).summary())
        return 0

    # Imported here so parsing, --help and --headless work without an OpenGL context.
    from isofightr.app import run

    run(
        stage,
        characters,
        seed=args.seed,
        scale=args.scale,
        fullscreen=args.fullscreen,
        max_ticks=args.frames,
        training=args.training,
        menus=not (skips_menus(args) or args.test_pattern),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
