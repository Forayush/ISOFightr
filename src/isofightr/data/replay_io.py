"""Reading and writing replay files, and building the match a replay starts from.

Plan note "16 - Testing Debug and Tooling" (``--record path.json``, ``--replay path.json``).
The replay format itself is in :mod:`isofightr.sim.replay`.
"""

import json
from pathlib import Path

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.match import Match
from isofightr.sim.replay import Replay, ReplayError, from_data, to_data


def save_replay(path: Path, replay: Replay) -> None:
    """Write a replay as JSON (LF line endings on every platform)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(to_data(replay), separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def load_replay(path: Path) -> Replay:
    """Read a replay file.

    Raises:
        ReplayError: if the file is missing, is not JSON, or is not a valid replay.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ReplayError(f"{path}: cannot read replay: {error}") from error
    except json.JSONDecodeError as error:
        raise ReplayError(f"{path}: not valid JSON: {error}") from error
    try:
        return from_data(data)
    except ReplayError as error:
        raise ReplayError(f"{path}: {error}") from error


def match_for(replay: Replay) -> Match:
    """Create the match a replay starts from, loading its stage and characters."""
    stage = load_stage(replay.stage)
    characters = [load_character(name) for name in replay.characters]
    return Match.create(stage, characters, replay.seed, replay.rules)


def numbered(path: Path, number: int) -> Path:
    """Return the file for the ``number``-th recording of a session: the path itself, then
    ``name-2.json``, ``name-3.json``..."""
    return path if number <= 1 else path.with_name(f"{path.stem}-{number}{path.suffix}")
