"""The whole couch loop, driven by key presses: need a real OpenGL window (``pytest -m gl``).

M6 exit criterion: "a complete couch match loop runs from boot to results and back without
touching the CLI". Plan note "13 - Game Modes UI and Flow".
"""

from typing import Any

import pytest

from isofightr.config import TICK_SECONDS
from isofightr.sim.constants import COUNTDOWN_FRAMES
from isofightr.sim.math3d import Vec3

pytestmark = pytest.mark.gl

BELOW_THE_STAGE = Vec3(5.0, 5.0, -9.0)


def keys() -> Any:
    """Arcade's key codes, imported lazily (the default test run has no display)."""
    import arcade

    return arcade.key


def start(window: Any, seed: int = 1) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    flow = GameFlow(window, window.pixel_buffer, seed=seed)
    flow.show_title()
    step(window, 2)
    return flow


def step(window: Any, ticks: int = 1) -> None:
    """Run ticks on whatever view is showing, drawing it as well."""
    for _ in range(ticks):
        window.current_view.on_update(TICK_SECONDS)
    window.current_view.on_draw()


def press(window: Any, key: int) -> None:
    """Tap a key: down for one tick, up for one tick."""
    view = window.current_view
    view.on_key_press(key, 0)
    view.on_update(TICK_SECONDS)
    window.current_view.on_key_release(key, 0)
    if window.current_view is view:
        view.on_key_release(key, 0)
    step(window, 2)


def name(window: Any) -> str:
    return type(window.current_view).__name__


def to_character_select(window: Any) -> Any:
    flow = start(window)
    press(window, keys().ENTER)
    assert name(window) == "MainMenuView"
    press(window, keys().ENTER)
    assert name(window) == "CharacterSelectView"
    return flow


def knock_out(window: Any, player: int) -> None:
    view = window.current_view
    view.match.fighters[player].pos = BELOW_THE_STAGE
    step(window, 1)


# --- the loop -----------------------------------------------------------------------------


def test_boot_to_results_and_back_without_the_cli(window: Any) -> None:
    flow = start(window)
    assert name(window) == "TitleView"
    press(window, keys().J)  # attack confirms too
    assert name(window) == "MainMenuView"
    assert window.current_view.menu.lines()[0] == "> Versus"
    press(window, keys().ENTER)

    # Character select: two Rooks, stock mode; take the stocks down to 1.
    css = window.current_view
    assert name(window) == "CharacterSelectView"
    assert [item.key for item in css.menu.items] == ["p1", "p2", "mode", "count", "next"]
    for _ in range(3):
        press(window, keys().S)
    assert css.menu.selected.key == "count"
    press(window, keys().A)
    press(window, keys().A)
    assert css.setup.stocks == 1 and css.menu.selected.text == "< 1 stock >"
    press(window, keys().S)
    press(window, keys().J)

    # Stage select: move to Sky Ruins and start.
    sss = window.current_view
    assert name(window) == "StageSelectView"
    assert sss.stage_ids[-1] == "random" and "final_plateau" in sss.stage_ids
    while sss.selected != "sky_ruins":
        press(window, keys().D)
    press(window, keys().ENTER)

    # Battle: countdown, GO!, a KO, GAME!, results.
    battle = window.current_view
    assert name(window) == "BattleView"
    assert battle.stage.id == "sky_ruins" and battle.match.rules.stocks == 1
    assert not battle.show_help, "no debug help text in a real match"
    assert battle.banner_text() == "3" and battle.hud.stocks_shown(0) == 1
    start_pos = battle.match.fighters[0].pos
    battle.on_key_press(keys().D, 0)
    step(window, COUNTDOWN_FRAMES - 3)
    assert battle.match.fighters[0].pos == start_pos, "no moving during the countdown"
    assert battle.banner_text() == "1"
    step(window, 6)
    battle.on_key_release(keys().D, 0)
    assert battle.banner_text() == "GO!" and battle.match.fighters[0].pos != start_pos
    step(window, 60)
    assert battle.banner_text() == ""

    knock_out(window, 1)
    assert battle.match.result is not None and battle.match.result.winner == 0
    assert battle.banner_text() == "GAME!" and battle.hud.stocks_shown(1) == 0
    frame = battle.match.frame
    step(window, 30)
    assert battle.match.frame == frame + 10, "slow motion: one sim tick in three"
    step(window, 130)
    results = window.current_view
    assert name(window) == "ResultsView"
    assert results.table_lines[1].split()[:2] == ["1st", "P1"]
    assert results.table_lines[2].split()[:2] == ["2nd", "P2"]

    # Rematch plays the same setup again; then back to character select.
    press(window, keys().ENTER)
    assert name(window) == "BattleView" and window.current_view is not battle
    assert window.current_view.match.rules.stocks == 1 and flow.matches_started == 2
    assert window.current_view.match.rng.state != battle.match.rng.state, "a new seed"
    step(window, COUNTDOWN_FRAMES + 2)
    knock_out(window, 0)
    step(window, 200)
    assert name(window) == "ResultsView"
    assert window.current_view.table_lines[1].split()[:2] == ["1st", "P2"]
    press(window, keys().S)
    press(window, keys().ENTER)
    assert name(window) == "CharacterSelectView"
    assert window.current_view.setup.stocks == 1, "the settings are remembered"
    press(window, keys().ESCAPE)
    assert name(window) == "MainMenuView"
    press(window, keys().K)  # special goes back
    assert name(window) == "TitleView"


def test_time_mode_shows_a_clock_and_ends_on_time(window: Any) -> None:
    to_character_select(window)
    css = window.current_view
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().D)
    assert css.setup.mode.value == "time"
    press(window, keys().S)
    press(window, keys().A)
    press(window, keys().A)
    assert css.menu.selected.text == "< 1 minute >"
    press(window, keys().S)
    press(window, keys().ENTER)
    press(window, keys().ENTER)
    battle = window.current_view
    assert name(window) == "BattleView" and battle.match.time_left == 3600
    step(window, COUNTDOWN_FRAMES + 30)
    assert battle.clock.text == "1:00" and battle.hud.stocks_shown(0) == 0
    knock_out(window, 1)
    battle.match.time_left = 2
    step(window, 3)
    assert battle.match.result is not None and battle.match.result.winner == 0


# --- pause menu ---------------------------------------------------------------------------


def test_pause_menu_freezes_the_match_and_quits_to_character_select(window: Any) -> None:
    to_character_select(window)
    for _ in range(4):
        press(window, keys().S)
    press(window, keys().ENTER)
    press(window, keys().ENTER)
    battle = window.current_view
    assert name(window) == "BattleView"
    step(window, 5)
    frame = battle.match.frame
    press(window, keys().ESCAPE)
    assert battle.menu_open
    step(window, 20)
    assert battle.match.frame == frame, "paused"
    assert [item.key for item in battle.pause_menu.items] == ["resume", "help", "quit"]
    press(window, keys().ESCAPE)
    assert not battle.menu_open
    step(window, 5)
    assert battle.match.frame > frame

    press(window, keys().ENTER)
    press(window, keys().W)  # up from Resume wraps to Quit
    assert battle.pause_menu.selected.key == "quit"
    press(window, keys().J)
    assert name(window) == "CharacterSelectView"


def test_training_from_the_menu_has_the_training_tools(window: Any) -> None:
    from isofightr.ai.dummy import DummyBehavior
    from isofightr.sim.fighter import StateId

    start(window)
    press(window, keys().ENTER)
    press(window, keys().S)
    press(window, keys().ENTER)
    css = window.current_view
    assert css.setup.training and [item.key for item in css.menu.items] == ["p1", "p2", "next"]
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().ENTER)
    assert window.current_view.selected == "training_grid"
    press(window, keys().ENTER)
    battle = window.current_view
    assert battle.training and battle.match.rules.stocks is None
    assert battle.banner_text() == "" and battle.dummy is DummyBehavior.STAND

    press(window, keys().ESCAPE)
    menu = battle.pause_menu
    assert [item.key for item in menu.items] == [
        "resume",
        "dummy",
        "damage",
        "hitboxes",
        "info",
        "reset",
        "help",
        "quit",
    ]
    press(window, keys().S)
    for _ in range(3):
        press(window, keys().D)
    assert battle.dummy is DummyBehavior.SHIELD
    press(window, keys().S)
    for _ in range(4):
        press(window, keys().D)
    assert battle.match.fighters[1].damage == 40.0
    assert menu.selected.text == "Dummy damage: < 40% >"
    press(window, keys().S)
    press(window, keys().D)
    assert battle.show_hitboxes
    press(window, keys().K)  # special closes the menu
    assert not battle.menu_open
    step(window, 5)
    assert battle.match.fighters[1].state is StateId.SHIELD, "the dummy is shielding"


# --- HUD ----------------------------------------------------------------------------------


def test_hud_shows_names_stocks_and_off_screen_markers(window: Any) -> None:
    from isofightr.data.character_loader import load_character
    from isofightr.data.stage_loader import load_stage
    from isofightr.scenes.battle import BattleView
    from isofightr.sim.match import MatchRules

    window.switch_to()
    rook = load_character("rook")
    view = BattleView(
        window.pixel_buffer, load_stage("training_grid"), [rook, rook], rules=MatchRules(stocks=7)
    )
    window.show_view(view)
    step(window, 1)
    assert view.hud.stocks_shown(0) == 1 and view.hud._stock_text[0].text == "x7"
    view.match.fighters[0].stocks = 3
    step(window, 1)
    assert view.hud.stocks_shown(0) == 3 and view.hud._stock_text[0].text == ""
    assert not view.hud.bubble_shown(0) and not view.hud.bubble_shown(1)

    view.camera.clamped = True
    view.match.fighters[1].pos = Vec3(30.0, 5.0, 0.0)  # far off to the right; no tick runs
    view.camera.snap_to([view.match.fighters[0].pos])
    view.on_draw()
    assert view.hud.bubble_shown(1) and not view.hud.bubble_shown(0)
