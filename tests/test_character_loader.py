"""Tests for the strict ``fighter.toml`` loader and data validation of shipped characters.

Plan note "07 - Fighter State Machine and Move Data" ("Character data format", "Validation at
load").
"""

import tomllib
from pathlib import Path

import pytest

from isofightr.data.character_loader import list_character_ids, load_character, parse_character
from isofightr.data.paths import CHARACTER_FILE_NAME
from isofightr.data.validation import DataError
from isofightr.sim.character_def import CharacterDef

ROOK = """
id = "rook"
display_name = "Rook"
weight = 98
[movement]
walk_speed = 0.060
dash_speed = 0.105
dash_frames = 12
run_speed = 0.100
traction = 0.006
jumpsquat = 3
full_hop_vz = 0.300
short_hop_vz = 0.180
double_jump_vz = 0.280
air_jumps = 1
air_accel = 0.006
air_speed = 0.070
air_friction = 0.002
gravity = 0.012
max_fall = 0.180
fast_fall = 0.260
land_lag = 3
[body]
radius = 0.30
height = 2.5
"""


def parse(text: str) -> CharacterDef:
    return parse_character(tomllib.loads(text), source="rook/fighter.toml", expected_id="rook")


def test_rook_ships_with_the_stats_from_the_plan() -> None:
    assert "rook" in list_character_ids()
    rook = load_character("rook")
    assert (rook.id, rook.display_name, rook.weight) == ("rook", "Rook", 98.0)
    stats = rook.movement
    assert (stats.walk_speed, stats.dash_speed, stats.run_speed) == (0.060, 0.105, 0.100)
    assert (stats.dash_frames, stats.jumpsquat, stats.land_lag, stats.air_jumps) == (12, 3, 3, 1)
    assert (stats.full_hop_vz, stats.short_hop_vz, stats.double_jump_vz) == (0.300, 0.180, 0.280)
    assert (stats.air_accel, stats.air_speed, stats.air_friction) == (0.006, 0.070, 0.002)
    assert (stats.gravity, stats.max_fall, stats.fast_fall) == (0.012, 0.180, 0.260)
    assert stats.traction == 0.006
    assert (rook.body.radius, rook.body.height) == (0.30, 2.5)


@pytest.mark.parametrize("character_id", list_character_ids())
def test_every_shipped_character_loads(character_id: str) -> None:
    assert load_character(character_id).id == character_id


def test_the_shipped_file_matches_the_reference_text() -> None:
    assert parse(ROOK) == load_character("rook")


def test_characters_are_immutable() -> None:
    rook = parse(ROOK)
    with pytest.raises(AttributeError):
        rook.weight = 1.0  # type: ignore[misc]
    with pytest.raises(AttributeError):
        rook.movement.run_speed = 1.0  # type: ignore[misc]


def test_unknown_character_lists_what_is_available(tmp_path: Path) -> None:
    path = tmp_path / "rook" / CHARACTER_FILE_NAME
    path.parent.mkdir()
    path.write_text(ROOK, encoding="utf-8")
    assert load_character("rook", tmp_path).id == "rook"
    with pytest.raises(DataError, match=r"no such character 'nope' \(available: rook\)"):
        load_character("nope", tmp_path)


def test_id_must_match_the_directory() -> None:
    with pytest.raises(DataError, match=r"id: is 'rook' but the directory is named 'bramble'"):
        parse_character(tomllib.loads(ROOK), source="x", expected_id="bramble")


def test_invalid_toml_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "rook" / CHARACTER_FILE_NAME
    path.parent.mkdir()
    path.write_text("id = ", encoding="utf-8")
    with pytest.raises(DataError, match=r"fighter\.toml: invalid TOML"):
        load_character("rook", tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("weight = 98", "weight = 98\nwieght = 1", r"unknown key\(s\) 'wieght'"),
        ("weight = 98", "", "weight: missing required key"),
        ("weight = 98", "weight = 0", "weight: must be greater than 0"),
        ("weight = 98", 'weight = "heavy"', "weight: must be a number"),
        ("run_speed = 0.100", "", r"movement\.run_speed: missing required key"),
        ("run_speed = 0.100", "run_speed = 0", r"movement\.run_speed: must be greater than 0"),
        ("run_speed = 0.100", "run_spede = 0.1", r"movement: unknown key\(s\) 'run_spede'"),
        ("jumpsquat = 3", "jumpsquat = 2.5", r"movement\.jumpsquat: must be a whole number"),
        ("jumpsquat = 3", "jumpsquat = 0", r"movement\.jumpsquat: must be 1 or greater"),
        ("air_jumps = 1", "air_jumps = -1", r"movement\.air_jumps: must be 0 or greater"),
        (
            "short_hop_vz = 0.180",
            "short_hop_vz = 0.4",
            r"movement\.short_hop_vz: must be less than full_hop_vz",
        ),
        ("fast_fall = 0.260", "fast_fall = 0.1", r"movement\.fast_fall: must be at least max_fall"),
        ("radius = 0.30", "radius = 0", r"body\.radius: must be greater than 0"),
        ("height = 2.5", "", r"body\.height: missing required key"),
        ("[body]", "[body]\nhurtbox = 1", r"body: unknown key\(s\) 'hurtbox'"),
    ],
)
def test_mistakes_are_reported_with_file_and_key(old: str, new: str, message: str) -> None:
    assert old in ROOK
    with pytest.raises(DataError, match=r"^rook/fighter\.toml: " + message):
        parse(ROOK.replace(old, new))


def test_zero_air_jumps_and_zero_land_lag_are_allowed() -> None:
    edited = ROOK.replace("air_jumps = 1", "air_jumps = 0").replace("land_lag = 3", "land_lag = 0")
    stats = parse(edited).movement
    assert (stats.air_jumps, stats.land_lag) == (0, 0)
