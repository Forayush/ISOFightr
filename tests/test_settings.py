"""Tests for user settings and ``settings.toml``, and what M7 added to the match setup.

Plan note "13 - Game Modes UI and Flow" ("Settings", "Modes": teams).
"""

import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from helpers import place
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.input.gamepad import PadState, gamepad_frame, process_stick
from isofightr.scenes.setup import MatchSetup, can_start, results_table
from isofightr.settings import (
    CONFIG_DIR_ENV,
    DEFAULT_KEYS,
    KEYBOARD_ACTIONS,
    PRESET_BUMPERS,
    Settings,
    config_dir,
    from_data,
    load_settings,
    save_settings,
    settings_path,
    to_toml,
)
from isofightr.sim.constants import COUNTDOWN_FRAMES
from isofightr.sim.input_frame import InputFrame
from isofightr.sim.match import Match, MatchRules

ROOK = load_character("rook")

# --- settings -----------------------------------------------------------------------------


def test_defaults() -> None:
    settings = Settings()
    assert (settings.scale, settings.fullscreen, settings.screen_shake) == (2, False, 100)
    assert (settings.master_volume, settings.music_volume, settings.sfx_volume) == (10, 8, 10)
    assert settings.deadzone == 0.20 and settings.gamepad_preset == "right_stick_modifiers"
    assert settings.keys["solo"]["attack"] == "J" and settings.keys["arrows"]["jump"] == "NUM_0"
    assert settings.slot_devices == ("keyboard:solo", "", "", "")
    assert set(DEFAULT_KEYS["solo"]) == set(DEFAULT_KEYS["arrows"]) == set(KEYBOARD_ACTIONS)


def test_settings_survive_the_file_exactly(tmp_path: Path) -> None:
    settings = replace(
        Settings().with_key("solo", "attack", "F").with_key("arrows", "walk", "RCTRL"),
        scale=3,
        fullscreen=True,
        screen_shake=25,
        master_volume=4,
        music_volume=0,
        sfx_volume=7,
        gamepad_preset=PRESET_BUMPERS,
        deadzone=0.30,
        reduce_flashing=True,
        slot_devices=("pad:1", "keyboard:solo", "", "pad:0"),
    )
    path = tmp_path / "nested" / "settings.toml"
    save_settings(path, settings)
    assert load_settings(path) == settings
    assert b"\r" not in path.read_bytes()
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["video"] == {
        "scale": 3,
        "fullscreen": True,
        "screen_shake": 25,
        "camera_zoom": "static",
        "reduce_flashing": True,
    }
    assert parsed["keyboard"]["solo"]["attack"] == "F"
    assert to_toml(settings) == path.read_text(encoding="utf-8")


def test_a_missing_or_broken_file_gives_the_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nothing.toml") == Settings()
    broken = tmp_path / "settings.toml"
    broken.write_text("scale = = 3", encoding="utf-8")
    assert load_settings(broken) == Settings()


def test_bad_values_fall_back_one_by_one() -> None:
    settings = from_data(
        {
            "video": {"scale": 9, "fullscreen": "yes", "screen_shake": 50},
            "audio": {"master": 99, "music": -3, "sfx": "loud"},
            "gamepad": {"preset": "sideways", "deadzone": 0.3},
            "keyboard": {"solo": {"attack": "Q", "jump": 5}, "mouse": {"attack": "X"}},
            "players": {"devices": ["pad:0", 7]},
            "unknown": {"anything": 1},
        }
    )
    assert (settings.scale, settings.fullscreen, settings.screen_shake) == (2, False, 50)
    assert (settings.master_volume, settings.music_volume, settings.sfx_volume) == (10, 0, 10)
    assert settings.gamepad_preset == "right_stick_modifiers" and settings.deadzone == 0.30
    assert settings.keys["solo"]["attack"] == "Q" and settings.keys["solo"]["jump"] == "SPACE"
    assert settings.slot_devices == ("pad:0", "", "", "")
    assert from_data({"video": 3, "audio": []}) == Settings()


def test_rebinding_takes_the_key_away_from_its_old_action() -> None:
    settings = Settings().with_key("solo", "special", "J")
    assert settings.keys["solo"]["special"] == "J" and settings.keys["solo"]["attack"] == ""
    assert settings.keys["arrows"] == dict(DEFAULT_KEYS["arrows"]), "other layouts untouched"
    assert Settings().keys["solo"]["attack"] == "J", "the original is not changed"
    assert settings.with_default_keys("solo").keys["solo"] == dict(DEFAULT_KEYS["solo"])


def test_config_dir_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    assert config_dir() == tmp_path and settings_path() == tmp_path / "settings.toml"
    monkeypatch.delenv(CONFIG_DIR_ENV)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert config_dir() == tmp_path / "roaming" / "ISOFightr"


def test_deadzone_setting_reaches_the_stick() -> None:
    assert process_stick(0.25, 0.0) != (0.0, 0.0)
    assert process_stick(0.25, 0.0, deadzone=0.30) == (0.0, 0.0)
    assert process_stick(1.0, 0.0, deadzone=0.30) == (1.0, 0.0)
    pad = PadState(left_x=0.25)
    assert gamepad_frame(pad, deadzone=0.30) == InputFrame()
    assert gamepad_frame(pad).move.length() > 0


# --- match setup --------------------------------------------------------------------------


def test_setup_carries_teams_and_the_optional_rules_into_the_match_rules() -> None:
    setup = MatchSetup(
        characters=("rook",) * 4,
        team_play=True,
        teams=(0, 1, 1, 0),
        friendly_fire=True,
        launch_rate=1.5,
        parry=True,
        air_dodge_helpless=True,
        short_hop_macro=False,
        stocks=2,
    )
    assert setup.rules() == MatchRules(
        stocks=2,
        countdown_frames=COUNTDOWN_FRAMES,
        launch_rate=1.5,
        teams=(0, 1, 1, 0),
        friendly_fire=True,
        parry=True,
        air_dodge_helpless=True,
        short_hop_macro=False,
    )
    assert MatchSetup().rules().short_hop_macro, "the macro is on unless the Rules screen says"
    free = replace(setup, team_play=False)
    assert free.rules().teams is None, "team numbers are ignored in a free-for-all"
    timed = replace(setup, stock_on=False, time_on=True, minutes=5)
    assert timed.rules().time_frames == 5 * 3600 and timed.rules().stocks is None
    assert replace(setup, training=True).rules() == MatchRules(stocks=None)


def test_when_a_match_can_start() -> None:
    versus = MatchSetup()
    assert "two players" in can_start(versus, 1)
    assert can_start(versus, 2) == "" and can_start(versus, 4) == ""
    teams = MatchSetup(team_play=True, teams=(0, 0, 0))
    assert "one team" in can_start(teams, 3)
    assert can_start(replace(teams, teams=(0, 0, 1)), 3) == ""
    training = MatchSetup(training=True)
    assert can_start(training, 1) == "" and can_start(training, 0) != ""


def test_results_table_gives_a_team_one_place() -> None:
    rules = MatchRules(stocks=1, teams=(0, 1, 0, 1))
    match = Match.create(load_stage("training_grid"), [ROOK] * 4, rules=rules)
    for player in (1, 3):
        place(match, match.fighters[player], 5.5, 5.5, z=-9.0)
        match.tick([InputFrame()] * 4)
    assert match.result is not None and match.result.winners == (0, 2)
    places = [line.split()[:2] for line in results_table(match)[1:]]
    assert places == [["1st", "P1"], ["1st", "P3"], ["2nd", "P2"], ["2nd", "P4"]]
