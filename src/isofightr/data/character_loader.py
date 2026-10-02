"""Loads ``assets/characters/<id>/fighter.toml`` into an immutable ``CharacterDef``.

Implements "Character data format" and "Validation at load" in the plan note "07 - Fighter
State Machine and Move Data", with strict validation (decision D-009): unknown keys are
errors, and every error names the file and the key.
"""

import tomllib
from collections.abc import Mapping
from pathlib import Path

from isofightr.data.paths import CHARACTER_FILE_NAME, CHARACTERS_DIR
from isofightr.data.validation import DataError, TableReader
from isofightr.sim.character_def import BodyStats, CharacterDef, MovementStats

_SPEED_KEYS = (
    "walk_speed",
    "dash_speed",
    "run_speed",
    "traction",
    "full_hop_vz",
    "short_hop_vz",
    "double_jump_vz",
    "air_accel",
    "air_speed",
    "air_friction",
    "gravity",
    "max_fall",
    "fast_fall",
)
_FRAME_KEYS = ("dash_frames", "jumpsquat", "air_jumps", "land_lag")


def list_character_ids(characters_dir: Path = CHARACTERS_DIR) -> list[str]:
    """Return the ids of every character that has a ``fighter.toml``, sorted."""
    return sorted(path.parent.name for path in characters_dir.glob(f"*/{CHARACTER_FILE_NAME}"))


def load_character(character_id: str, characters_dir: Path = CHARACTERS_DIR) -> CharacterDef:
    """Load a character by id from ``<characters_dir>/<id>/fighter.toml``.

    Raises:
        DataError: if the file is missing, is not valid TOML, or fails validation.
    """
    path = characters_dir / character_id / CHARACTER_FILE_NAME
    if not path.is_file():
        known = ", ".join(list_character_ids(characters_dir)) or "none"
        raise DataError(f"{path}: no such character {character_id!r} (available: {known})")
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise DataError(f"{path}: invalid TOML: {error}") from error
    return parse_character(data, source=str(path), expected_id=character_id)


def parse_character(
    data: Mapping[str, object], *, source: str, expected_id: str | None = None
) -> CharacterDef:
    """Validate a parsed ``fighter.toml`` table and build the :class:`CharacterDef`."""
    root = TableReader(
        data,
        source=source,
        where="",
        allowed=("id", "display_name", "weight", "movement", "body"),
    )
    character_id = root.string("id")
    if expected_id is not None and character_id != expected_id:
        raise root.error(f"is {character_id!r} but the directory is named {expected_id!r}", "id")
    weight = root.number("weight")
    if weight <= 0:
        raise root.error("must be greater than 0", "weight")

    return CharacterDef(
        id=character_id,
        display_name=root.string("display_name"),
        weight=weight,
        movement=_movement(root.subtable("movement", (*_SPEED_KEYS, *_FRAME_KEYS))),
        body=_body(root.subtable("body", ("radius", "height"))),
    )


def _movement(reader: TableReader) -> MovementStats:
    speeds = {key: reader.number(key) for key in _SPEED_KEYS}
    frames = {key: reader.integer(key) for key in _FRAME_KEYS}
    for key, value in speeds.items():
        if value <= 0:
            raise reader.error("must be greater than 0", key)
    for key in ("dash_frames", "jumpsquat"):
        if frames[key] < 1:
            raise reader.error("must be 1 or greater", key)
    for key in ("air_jumps", "land_lag"):
        if frames[key] < 0:
            raise reader.error("must be 0 or greater", key)
    if speeds["short_hop_vz"] >= speeds["full_hop_vz"]:
        raise reader.error("must be less than full_hop_vz", "short_hop_vz")
    if speeds["fast_fall"] < speeds["max_fall"]:
        raise reader.error("must be at least max_fall", "fast_fall")
    return MovementStats(
        walk_speed=speeds["walk_speed"],
        dash_speed=speeds["dash_speed"],
        dash_frames=frames["dash_frames"],
        run_speed=speeds["run_speed"],
        traction=speeds["traction"],
        jumpsquat=frames["jumpsquat"],
        full_hop_vz=speeds["full_hop_vz"],
        short_hop_vz=speeds["short_hop_vz"],
        double_jump_vz=speeds["double_jump_vz"],
        air_jumps=frames["air_jumps"],
        air_accel=speeds["air_accel"],
        air_speed=speeds["air_speed"],
        air_friction=speeds["air_friction"],
        gravity=speeds["gravity"],
        max_fall=speeds["max_fall"],
        fast_fall=speeds["fast_fall"],
        land_lag=frames["land_lag"],
    )


def _body(reader: TableReader) -> BodyStats:
    radius, height = reader.number("radius"), reader.number("height")
    if radius <= 0:
        raise reader.error("must be greater than 0", "radius")
    if height <= 0:
        raise reader.error("must be greater than 0", "height")
    return BodyStats(radius=radius, height=height)
