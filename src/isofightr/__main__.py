"""``python -m isofightr`` entrypoint and CLI flags.

Implements the "CLI flags" table in the plan note "16 - Testing Debug and Tooling". M0 covers
the window options; match setup flags (``--p1``, ``--stage``, ``--training``, ``--headless``,
``--replay``...) are added by the milestones that build what they control.
"""

import argparse
import logging
from collections.abc import Sequence

from isofightr.config import DEFAULT_WINDOW_SCALE, MIN_WINDOW_SCALE


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
        "--frames",
        type=_positive_int,
        default=None,
        metavar="N",
        help="close automatically after N simulation ticks",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the command line and run the game. Returns the process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    # Imported here so parsing (and --help) works without creating an OpenGL context.
    from isofightr.app import run

    run(scale=args.scale, fullscreen=args.fullscreen, max_ticks=args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
