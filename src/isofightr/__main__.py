"""``python -m isofightr`` entrypoint and CLI flags.

Implements the "CLI flags" table in the plan note "16 - Testing Debug and Tooling". Built so
far: the window options (M0), ``--stage`` (M1), ``--p1`` to ``--p4``, ``--seed`` and
``--headless`` (M2), ``--training`` (M3), ``--battle`` (M6: without it, ``--stage``,
``--training`` or ``--cpu``, the game starts at the title screen), ``--record`` and
``--replay`` (M7), and ``--cpu`` (M10).
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from isofightr.config import (
    CPU_MAX_LEVEL,
    CPU_MIN_LEVEL,
    DEFAULT_CHARACTER_ID,
    DEFAULT_PLAYER_COUNT,
    DEFAULT_STAGE_ID,
    DEFAULT_WINDOW_SCALE,
    MAX_PLAYERS,
    MIN_WINDOW_SCALE,
    TRAINING_STAGE_ID,
)
from isofightr.data.character_loader import load_character
from isofightr.data.replay_io import load_replay, match_for, save_replay
from isofightr.data.stage_loader import load_stage
from isofightr.data.validation import DataError
from isofightr.headless import HEADLESS_RULES, replay_headless, run_headless
from isofightr.sim.replay import Recorder, ReplayError

EXIT_DATA_ERROR = 2
EXIT_REPLAY_MISMATCH = 3
EXIT_NO_AUDIO = 4
REPLAY_MISMATCH_TEXT = (
    "replay does NOT match the recorded state: the game's data or rules have changed since"
)


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


def _cpu_slot(text: str) -> tuple[int, int]:
    player, separator, level = text.partition(":")
    if not separator or not player.isdigit() or not level.isdigit():
        raise argparse.ArgumentTypeError(f"expected PLAYER:LEVEL such as 2:7, got {text!r}")
    if not 1 <= int(player) <= MAX_PLAYERS:
        raise argparse.ArgumentTypeError(f"player must be 1 to {MAX_PLAYERS}, got {player}")
    if not CPU_MIN_LEVEL <= int(level) <= CPU_MAX_LEVEL:
        raise argparse.ArgumentTypeError(
            f"CPU level must be {CPU_MIN_LEVEL} to {CPU_MAX_LEVEL}, got {level}"
        )
    return int(player), int(level)


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser for ``python -m isofightr``."""
    parser = argparse.ArgumentParser(
        prog="isofightr",
        description="ISOFightr: an isometric platform fighter.",
    )
    parser.add_argument(
        "--scale",
        type=_window_scale,
        default=None,
        metavar="N",
        help="integer window scale of the 640x360 native buffer (default: the saved setting, "
        f"at first {DEFAULT_WINDOW_SCALE})",
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
        "--cpu",
        type=_cpu_slot,
        action="append",
        default=[],
        metavar="P:L",
        help="player P is a CPU of level L (1 to 9), e.g. --cpu 2:7; repeat for more CPUs. "
        "Skips the menus; with --headless the other players get random input",
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
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        metavar="PATH",
        help="record every match of this session to a replay file (PATH, then PATH-2...)",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        metavar="PATH",
        help="play a replay file back; with --headless, only check that it still ends in "
        "the recorded state",
    )
    parser.add_argument("--mute", action="store_true", help="no sound effects or music")
    parser.add_argument(
        "--check-audio",
        action="store_true",
        help="play one sound and one song silently and exit (0 = audio works); used to "
        "test the packaged game",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    return parser


def skips_menus(args: argparse.Namespace) -> bool:
    """Return whether the command line asks to go straight into a match."""
    return bool(args.battle or args.training or args.stage is not None or args.cpu)


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


def cpu_levels(
    args: argparse.Namespace, players: int, parser: argparse.ArgumentParser
) -> list[int]:
    """Return the CPU level of each player (0 = a person) from ``--cpu``."""
    levels = [0] * players
    for player, level in args.cpu:
        if player > players:
            parser.error(f"--cpu {player}:{level}: there are only {players} players")
        levels[player - 1] = level
    return levels


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the game. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    if args.headless and args.frames is None and args.replay is None:
        parser.error("--headless needs --frames N")
    if args.replay is not None and (args.record is not None or args.training):
        parser.error("--replay cannot be combined with --record or --training")
    if args.check_audio:
        from isofightr.app import check_audio

        return 0 if check_audio() else EXIT_NO_AUDIO
    if args.replay is not None:
        return _replay(args)
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
    cpus = cpu_levels(args, len(characters), parser)
    if args.training and any(cpus[1:]):
        parser.error("--training makes the other players dummies: pick a CPU dummy in its menu")

    if args.headless:
        assert stage is not None
        recorder = None
        if args.record is not None:
            names = tuple(character.id for character in characters)
            recorder = Recorder(stage.id, names, args.seed, HEADLESS_RULES)
        report = run_headless(stage, characters, args.seed, args.frames, recorder, cpus)
        print(report.summary())
        if recorder is not None and recorder.final is not None:
            save_replay(args.record, recorder.final)
            print(f"recorded {recorder.final.ticks} ticks to {args.record}")
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
        record=args.record,
        cpus=cpus,
        sound=not args.mute,
    )
    return 0


def _replay(args: argparse.Namespace) -> int:
    """Play a replay file back, in a window or headless."""
    try:
        replay = load_replay(args.replay)
        match = match_for(replay)
    except (ReplayError, DataError) as error:
        print(f"isofightr: {error}", file=sys.stderr)
        return EXIT_DATA_ERROR
    if args.headless:
        report, matches = replay_headless(match, replay)
        print(report.summary())
        print("replay matches the recorded state" if matches else REPLAY_MISMATCH_TEXT)
        return 0 if matches else EXIT_REPLAY_MISMATCH

    from isofightr.app import run_replay

    scale = args.scale or DEFAULT_WINDOW_SCALE
    run_replay(replay, scale=scale, fullscreen=args.fullscreen, max_ticks=args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
