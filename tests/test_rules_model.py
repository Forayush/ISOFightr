"""The Rules screen's model and the saved rules (plan note 13, decision D-061).

Pure: no window. The screen itself is driven in ``tests/test_flow_gl.py``.
"""

import tomllib
from dataclasses import fields, replace
from pathlib import Path

import pytest

from isofightr.data.stage_loader import list_stage_ids
from isofightr.scenes import rules_model
from isofightr.scenes.rules_model import (
    ROW_KEYS,
    RULE_ROWS,
    row_on,
    row_value,
    rule_chips,
    step_row,
    to_saved,
    toggle_pool,
    toggle_row,
    with_default_rules,
    with_saved,
)
from isofightr.scenes.setup import MatchSetup
from isofightr.settings import (
    LAUNCH_RATES,
    RULE_FLAGS,
    SavedRules,
    Settings,
    from_data,
    load_settings,
    rules_from_data,
    save_settings,
    to_toml,
)
from isofightr.sim.constants import COUNTDOWN_FRAMES
from isofightr.sim.match import MatchRules
from isofightr.ui.icons import load_icons

STAGES = ["a", "b", "c"]


# --- the defaults are the rules the game had before M13 -------------------------------------


def test_the_default_setup_gives_exactly_the_rules_from_before_this_milestone() -> None:
    assert MatchSetup().rules() == MatchRules(
        stocks=3,
        time_frames=None,
        countdown_frames=COUNTDOWN_FRAMES,
        launch_rate=1.0,
        teams=None,
        friendly_fire=False,
        parry=False,
        air_dodge_helpless=False,
        short_hop_macro=True,
        start_damage=0.0,
    )
    setup = MatchSetup()
    assert (setup.hud_display, setup.score_display, setup.player_tags, setup.pausing) == (
        True,
        False,
        False,
        True,
    )
    assert setup.random_pool == () and setup.pool(STAGES) == STAGES, "every stage is in"
    assert to_saved(setup) == SavedRules(), "and they are what DEFAULT restores"
    assert with_saved(MatchSetup(), Settings().rules) == MatchSetup()


def test_default_puts_every_rule_back_and_keeps_who_is_playing() -> None:
    changed = MatchSetup(
        characters=("mote", "rook", "bramble"),
        stage="twin_isles",
        devices=("pad:0", "keyboard:solo", ""),
        cpus=(0, 0, 7),
        teams=(1, 0, 1),
        stock_on=False,
        stocks=9,
        time_on=True,
        minutes=7,
        launch_rate=2.0,
        start_damage=120,
        team_play=True,
        friendly_fire=True,
        parry=True,
        short_hop_macro=False,
        air_dodge_helpless=True,
        hud_display=False,
        score_display=True,
        player_tags=True,
        pausing=False,
        random_pool=("sky_ruins",),
    )
    restored = with_default_rules(changed)
    assert to_saved(restored) == SavedRules()
    assert restored.rules() == replace(MatchSetup().rules())
    kept = ("characters", "stage", "devices", "cpus", "teams", "training")
    assert all(getattr(restored, name) == getattr(changed, name) for name in kept)
    saved = {field.name for field in fields(SavedRules)}
    assert saved <= {field.name for field in fields(MatchSetup)}, "every rule is a setup field"


# --- rows ------------------------------------------------------------------------------------


def test_rows_are_only_rules_the_game_has_and_each_has_an_icon_and_help() -> None:
    assert ROW_KEYS == (
        "time",
        "stock",
        "launch_rate",
        "start_damage",
        "team_play",
        "friendly_fire",
        "parry",
        "short_hop_macro",
        "air_dodge_helpless",
        "hud_display",
        "score_display",
        "player_tags",
        "pausing",
    )
    icons = load_icons()
    for row in RULE_ROWS:
        assert row.icon in icons, row.key
        assert row.help.endswith(".") and len(row.help) <= 76, row.key
        assert row.has_value or row.has_switch
        assert row.label == row.label.upper()
    assert "dice" in icons, "the random pool button"
    switches = {row.key for row in RULE_ROWS if row.has_switch} - {"time", "stock"}
    assert switches == set(RULE_FLAGS)
    assert rules_model.row("parry").label == "PARRY"


def test_value_rows_step_and_stay_in_range() -> None:
    setup = MatchSetup()
    assert [row_value(setup, key) for key in ROW_KEYS[:4]] == ["3:00", "3", "1.0x", "0%"]
    assert row_value(setup, "parry") == ""
    assert step_row(setup, "stock", 1).stocks == 4 and step_row(setup, "stock", -9).stocks == 1
    assert step_row(setup, "time", 2).minutes == 5 and step_row(setup, "time", 200).minutes == 99
    assert step_row(setup, "parry", 1) == setup, "no value to step"

    rates = [setup.launch_rate]
    for _ in range(10):
        setup = step_row(setup, "launch_rate", 1)
        rates.append(setup.launch_rate)
    assert rates[:4] == [1.0, 1.25, 1.5, 2.0] and rates[-1] == 2.0, "stops at the end"
    assert row_value(setup, "launch_rate") == "2.0x"
    assert row_value(replace(setup, launch_rate=0.75), "launch_rate") == "0.75x"
    for _ in range(10):
        setup = step_row(setup, "launch_rate", -1)
    assert setup.launch_rate == LAUNCH_RATES[0] == 0.5
    assert step_row(replace(setup, launch_rate=1.1), "launch_rate", 1).launch_rate == 1.25

    damage = MatchSetup()
    assert step_row(damage, "start_damage", -1).start_damage == 0
    assert step_row(damage, "start_damage", 3).start_damage == 30
    assert row_value(step_row(damage, "start_damage", 3), "start_damage") == "30%"
    assert step_row(damage, "start_damage", 99).start_damage == 300
    assert step_row(damage, "start_damage", 4).rules().start_damage == 40.0


@pytest.mark.parametrize("key", RULE_FLAGS)
def test_each_switch_row_flips_its_own_field_and_nothing_else(key: str) -> None:
    setup = MatchSetup()
    flipped = toggle_row(setup, key)
    assert row_on(flipped, key) is (not row_on(setup, key))
    assert replace(flipped, **{key: getattr(setup, key)}) == setup
    assert toggle_row(flipped, key) == setup


def test_the_sim_rules_follow_the_switches() -> None:
    setup = MatchSetup(characters=("rook",) * 4, teams=(0, 1, 0, 1))
    assert toggle_row(setup, "parry").rules().parry
    assert toggle_row(setup, "air_dodge_helpless").rules().air_dodge_helpless
    assert not toggle_row(setup, "short_hop_macro").rules().short_hop_macro
    assert toggle_row(setup, "friendly_fire").rules().friendly_fire
    assert toggle_row(setup, "team_play").rules().teams == (0, 1, 0, 1)
    for display in ("hud_display", "score_display", "player_tags", "pausing"):
        assert toggle_row(setup, display).rules() == setup.rules(), "presentation only"


def test_time_and_stock_are_independent_but_one_always_stays_on() -> None:
    setup = MatchSetup()
    assert (row_on(setup, "stock"), row_on(setup, "time")) == (True, False)
    both = toggle_row(setup, "time")
    assert (both.stock_on, both.time_on) == (True, True)
    rules = both.rules()
    assert rules.stocks == 3 and rules.time_frames == 3 * 3600
    time_only = toggle_row(both, "stock")
    assert (time_only.stock_on, time_only.time_on) == (False, True)
    assert time_only.rules().stocks is None and time_only.rules().time_frames == 3 * 3600
    back = toggle_row(time_only, "time")
    assert (back.stock_on, back.time_on) == (True, False), "the last one off turns the other on"
    assert toggle_row(setup, "stock").time_on and not toggle_row(setup, "stock").stock_on
    assert row_on(setup, "launch_rate") is None
    assert toggle_row(setup, "launch_rate").launch_rate == 1.25, "confirm steps a value row"
    impossible = MatchSetup(stock_on=False, time_on=False)
    assert impossible.rules().stocks == 3, "a setup with neither still has stocks"


def test_the_random_pool_keeps_at_least_one_stage() -> None:
    setup = MatchSetup()
    one_out = toggle_pool(setup, "b", STAGES)
    assert one_out.random_pool == ("a", "c") and one_out.pool(STAGES) == ["a", "c"]
    two_out = toggle_pool(one_out, "a", STAGES)
    assert two_out.pool(STAGES) == ["c"]
    assert toggle_pool(two_out, "c", STAGES) == two_out, "the last one stays"
    back_in = toggle_pool(toggle_pool(two_out, "a", STAGES), "b", STAGES)
    assert back_in.random_pool == (), "all of them is stored as 'every stage'"
    assert toggle_pool(setup, "nope", STAGES) == setup
    stale = MatchSetup(random_pool=("gone", "also_gone"))
    assert stale.pool(STAGES) == STAGES, "a pool naming no real stage means every stage"
    assert MatchSetup(random_pool=("c", "gone")).pool(STAGES) == ["c"]
    real = list_stage_ids()
    assert MatchSetup().pool(real) == real


def test_rule_chips_sum_the_rules_up() -> None:
    assert rule_chips(MatchSetup()) == ["STOCK 3", "1.0x", "TEAMS OFF"]
    busy = MatchSetup(time_on=True, minutes=5, start_damage=50, team_play=True, launch_rate=1.5)
    assert rule_chips(busy) == ["STOCK 3", "TIME 5:00", "1.5x", "START 50%", "TEAMS ON"]
    assert rule_chips(MatchSetup(stock_on=False, time_on=True))[0] == "TIME 3:00"


# --- persistence ---------------------------------------------------------------------------


def test_the_rules_round_trip_through_the_settings_file(tmp_path: Path) -> None:
    rules = SavedRules(
        stock_on=False,
        stocks=7,
        time_on=True,
        minutes=12,
        launch_rate=0.75,
        start_damage=130,
        team_play=True,
        friendly_fire=True,
        parry=True,
        short_hop_macro=False,
        air_dodge_helpless=True,
        hud_display=False,
        score_display=True,
        player_tags=True,
        pausing=False,
        random_pool=("sky_ruins", "lily_pads"),
    )
    path = tmp_path / "settings.toml"
    save_settings(path, replace(Settings(), rules=rules))
    assert load_settings(path).rules == rules
    assert load_settings(path) == replace(Settings(), rules=rules), "nothing else moved"
    setup = with_saved(MatchSetup(characters=("mote", "rook")), rules)
    assert to_saved(setup) == rules and setup.characters == ("mote", "rook")
    text = to_toml(Settings())
    assert "[rules]" in text and from_data(tomllib.loads(text)) == Settings()
    assert "launch_rate = 1.0" in text and "random_pool = []" in text


def test_a_file_without_rules_gets_the_defaults() -> None:
    assert from_data({}).rules == SavedRules()
    assert from_data({"video": {"scale": 3}}).rules == SavedRules()
    assert rules_from_data(None) == SavedRules()
    assert rules_from_data("nonsense") == SavedRules()
    assert rules_from_data([1, 2]) == SavedRules()


def test_bad_rule_values_fall_back_one_at_a_time() -> None:
    table = {
        "stocks": 0,
        "minutes": "five",
        "launch_rate": 3.3,
        "start_damage": 45,
        "parry": "yes",
        "short_hop_macro": 0,
        "hud_display": False,
        "score_display": True,
        "random_pool": ["sky_ruins", 7, "", "sky_ruins", "twin_isles"],
        "unknown_rule": True,
        "time_on": True,
    }
    rules = rules_from_data(table)
    assert rules.stocks == 3 and rules.minutes == 3, "out of range and the wrong type"
    assert rules.launch_rate == 1.0 and rules.start_damage == 0
    assert rules.parry is False and rules.short_hop_macro is True, "not booleans: defaults"
    assert rules.hud_display is False and rules.score_display is True, "the good ones are kept"
    assert rules.random_pool == ("sky_ruins", "twin_isles"), "strings only, no repeats"
    assert rules.time_on and rules.stock_on
    for good, value in (("stocks", 99), ("minutes", 1), ("start_damage", 300)):
        assert getattr(rules_from_data({good: value}), good) == value
    assert rules_from_data({"stocks": True}).stocks == 3, "true is not a number"
    assert rules_from_data({"stocks": 100}).stocks == 3
    assert rules_from_data({"start_damage": 310}).start_damage == 0
    assert rules_from_data({"start_damage": -10}).start_damage == 0
    assert rules_from_data({"launch_rate": 2}).launch_rate == 2.0, "a whole number is fine"
    assert rules_from_data({"random_pool": "sky_ruins"}).random_pool == ()


def test_stock_and_time_both_off_in_the_file_is_put_right() -> None:
    rules = rules_from_data({"stock_on": False, "time_on": False, "stocks": 5})
    assert (rules.stock_on, rules.time_on, rules.stocks) == (True, False, 5)
    assert rules_from_data({"stock_on": False, "time_on": True}).stock_on is False


def test_a_corrupt_settings_file_never_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text('[rules]\nstocks = "lots"\nrandom_pool = 3\n[rules.extra]\nx = 1\n', "utf-8")
    assert load_settings(path).rules == SavedRules()
    path.write_text("[rules\nstocks = ", "utf-8")
    assert load_settings(path) == Settings()
    path.write_text("rules = 5\n", "utf-8")
    assert load_settings(path).rules == SavedRules()
