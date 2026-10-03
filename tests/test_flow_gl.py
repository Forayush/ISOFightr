"""The whole couch loop, driven by key presses: need a real OpenGL window (``pytest -m gl``).

M6 exit criterion: "a complete couch match loop runs from boot to results and back without
touching the CLI". M7: joining with up to four devices, teams, settings and recording.
Plan note "13 - Game Modes UI and Flow".
"""

from collections.abc import Callable
from pathlib import Path
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


class FakeController:
    """Looks like a ``pyglet.input.Controller``: pollable buttons, stick events."""

    def __init__(self, name: str = "Fake Pad") -> None:
        self.name = name
        self.a = self.b = self.x = self.y = False
        self.leftshoulder = self.rightshoulder = False
        self.lefttrigger = self.righttrigger = 0.0
        self.handlers: dict[str, list[Callable[..., None]]] = {}

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def push_handlers(self, **handlers: Callable[..., None]) -> None:
        for name, handler in handlers.items():
            self.handlers.setdefault(name, []).append(handler)

    def remove_handlers(self, **handlers: Callable[..., None]) -> None:
        for name, handler in handlers.items():
            if handler in self.handlers.get(name, []):
                self.handlers[name].remove(handler)

    def move_stick(self, x: float, y: float) -> None:
        """Send a left stick event to everything listening."""
        from pyglet.math import Vec2

        for handler in list(self.handlers.get("on_stick_motion", [])):
            handler(self, "leftstick", Vec2(x, y))


class FakeManager:
    """Stands in for pyglet's ``ControllerManager``: a fixed list of controllers."""

    controllers: list[FakeController] = []  # noqa: RUF012 - shared on purpose, set per test

    def push_handlers(self, **handlers: Callable[..., None]) -> None:
        pass

    def remove_handlers(self, **handlers: Callable[..., None]) -> None:
        pass

    def get_controllers(self) -> list[FakeController]:
        return list(self.controllers)


@pytest.fixture
def pads(monkeypatch: pytest.MonkeyPatch) -> list[FakeController]:
    """Replace the machine's controllers with two fake ones (and hide any real ones)."""
    import pyglet

    fakes = [FakeController("One"), FakeController("Two")]
    monkeypatch.setattr(FakeManager, "controllers", fakes)
    monkeypatch.setattr(pyglet.input, "ControllerManager", FakeManager)
    return fakes


@pytest.fixture(autouse=True)
def no_real_controllers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever is plugged into this machine must not join the tests."""
    import pyglet

    monkeypatch.setattr(FakeManager, "controllers", [])
    monkeypatch.setattr(pyglet.input, "ControllerManager", FakeManager)


def start(window: Any, **flow_options: Any) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    flow = GameFlow(window, window.pixel_buffer, seed=1, **flow_options)
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
    if window.current_view is not view:
        view.on_key_release(key, 0)
    step(window, 2)


def tap_pad(window: Any, pad: FakeController, button: str = "a") -> None:
    """Tap a controller button."""
    setattr(pad, button, True)
    step(window, 1)
    setattr(pad, button, False)
    step(window, 2)


def name(window: Any) -> str:
    return type(window.current_view).__name__


def to_main_menu(window: Any, **flow_options: Any) -> Any:
    flow = start(window, **flow_options)
    press(window, keys().ENTER)
    assert name(window) == "MainMenuView"
    return flow


def set_one_stock(window: Any) -> None:
    """From the main menu: open Rules, take stocks down to 1, and come back."""
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().ENTER)
    assert name(window) == "RulesView"
    press(window, keys().S)
    press(window, keys().A)
    press(window, keys().A)
    assert window.current_view.setup.stocks == 1
    press(window, keys().ESCAPE)
    assert name(window) == "MainMenuView"


def two_players_to_stage_select(window: Any) -> None:
    """From the main menu: Versus, player 2 joins on the arrows keyboard, both ready."""
    press(window, keys().ENTER)
    assert name(window) == "CharacterSelectView"
    press(window, keys().NUM_4)
    press(window, keys().J)
    press(window, keys().NUM_4)
    assert name(window) == "StageSelectView"


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
    assert [item.key for item in window.current_view.menu.items] == [
        "versus",
        "training",
        "rules",
        "settings",
        "quit",
    ]
    set_one_stock(window)
    assert flow.setup.stocks == 1

    # Character select: P1 is already in on the WASD keyboard; P2 joins with its attack key.
    press(window, keys().ENTER)
    css = window.current_view
    assert name(window) == "CharacterSelectView"
    assert [slot.device for slot in css.slots] == ["keyboard:solo", "", "", ""]
    assert css._busts[0].visible and not css._busts[1].visible, "a bust for each joined player"
    press(window, keys().J)
    assert name(window) == "CharacterSelectView"
    assert "two players" in css.message, "one player cannot start a versus match"
    assert not css.slots[0].ready
    press(window, keys().NUM_4)
    assert css.slots[1].device == "keyboard:arrows" and not css.slots[1].ready
    press(window, keys().NUM_4)
    press(window, keys().J)

    # Stage select: move to Sky Ruins and start.
    sss = window.current_view
    assert name(window) == "StageSelectView"
    assert sss.setup.devices == ("keyboard:solo", "keyboard:arrows")
    assert flow.settings.slot_devices == ("keyboard:solo", "keyboard:arrows", "", "")
    assert sss.stage_ids[-1] == "random" and "final_plateau" in sss.stage_ids
    while sss.selected != "sky_ruins":
        press(window, keys().D)
    press(window, keys().ENTER)

    # Battle: countdown, GO!, a KO, GAME!, results.
    battle = window.current_view
    assert name(window) == "BattleView"
    assert battle.stage.id == "sky_ruins" and battle.match.rules.stocks == 1
    assert battle.devices == ("keyboard:solo", "keyboard:arrows")
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
    second = battle.match.fighters[1].pos
    battle.on_key_press(keys().LEFT, 0)
    step(window, 10)
    battle.on_key_release(keys().LEFT, 0)
    assert battle.match.fighters[1].pos != second, "player 2 is on the arrows"
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
    css = window.current_view
    assert name(window) == "CharacterSelectView"
    assert [slot.device for slot in css.slots[:2]] == ["keyboard:solo", "keyboard:arrows"]
    assert css.setup.stocks == 1, "the settings and the players are remembered"
    press(window, keys().NUM_5)  # player 2's special: leave
    press(window, keys().ESCAPE)  # player 1 leaves
    assert [slot.device for slot in css.slots] == ["", "", "", ""]
    press(window, keys().ESCAPE)
    assert name(window) == "MainMenuView"
    press(window, keys().K)  # special goes back
    assert name(window) == "TitleView"


def test_time_mode_shows_a_clock_and_ends_on_time(window: Any) -> None:
    to_main_menu(window)
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().ENTER)
    rules = window.current_view
    press(window, keys().D)
    assert rules.setup.mode.value == "time"
    press(window, keys().S)
    press(window, keys().A)
    press(window, keys().A)
    assert rules.menu.selected.text == "< 1 minute >"
    press(window, keys().K)
    two_players_to_stage_select(window)
    press(window, keys().ENTER)
    battle = window.current_view
    assert name(window) == "BattleView" and battle.match.time_left == 3600
    step(window, COUNTDOWN_FRAMES + 30)
    assert battle.clock.text == "1:00" and battle.hud.stocks_shown(0) == 0
    knock_out(window, 1)
    battle.match.time_left = 2
    step(window, 3)
    assert battle.match.result is not None and battle.match.result.winner == 0


# --- joining ------------------------------------------------------------------------------


def test_four_players_join_with_mixed_devices(window: Any, pads: list[FakeController]) -> None:
    to_main_menu(window)
    press(window, keys().ENTER)
    css = window.current_view
    assert css.hub.ids() == ["keyboard:solo", "keyboard:arrows", "pad:0", "pad:1"]
    tap_pad(window, pads[1])
    press(window, keys().NUM_4)
    tap_pad(window, pads[0])
    assert [slot.device for slot in css.slots] == [
        "keyboard:solo",
        "pad:1",
        "keyboard:arrows",
        "pad:0",
    ]
    assert css._panels[1].labels[1].text == "Pad 2"
    tap_pad(window, pads[0], "b")  # special: leave again
    assert css.slots[3].device == ""
    tap_pad(window, pads[0])
    for confirm in (keys().J, keys().NUM_4):
        press(window, confirm)
    tap_pad(window, pads[0])
    assert name(window) == "CharacterSelectView", "player 2 (pad 2) is not ready yet"
    tap_pad(window, pads[1])
    assert name(window) == "StageSelectView"
    press(window, keys().ENTER)
    battle = window.current_view
    assert len(battle.match.fighters) == 4
    assert battle.devices == ("keyboard:solo", "pad:1", "keyboard:arrows", "pad:0")
    step(window, COUNTDOWN_FRAMES + 2)

    # Each device drives its own fighter.
    from isofightr.sim.fighter import StateId

    pads[1].x = True
    step(window, 6)
    pads[1].x = False
    states = [fighter.state for fighter in battle.match.fighters]
    assert states[1] in (StateId.JUMP_SQUAT, StateId.JUMP)
    assert states[0] is states[2] is states[3] is StateId.IDLE


def test_an_unplugged_controller_pauses_the_match(
    window: Any, pads: list[FakeController], monkeypatch: pytest.MonkeyPatch
) -> None:
    to_main_menu(window)
    press(window, keys().ENTER)
    tap_pad(window, pads[0])
    press(window, keys().J)
    tap_pad(window, pads[0])
    press(window, keys().ENTER)
    battle = window.current_view
    step(window, COUNTDOWN_FRAMES + 5)
    frame = battle.match.frame
    battle.hub._disconnect(pads[0])
    step(window, 5)
    assert battle.menu_open and battle.match.frame <= frame + 1
    assert "pad:0 was unplugged" in battle.status_line()
    battle.hub._connect(pads[0])
    press(window, keys().ESCAPE)
    step(window, 5)
    assert not battle.menu_open and battle.match.frame > frame + 1


def test_slots_remember_their_devices_across_a_session(window: Any, tmp_path: Path) -> None:
    from isofightr.settings import load_settings

    path = tmp_path / "settings.toml"
    flow = to_main_menu(window, settings_path=path)
    two_players_to_stage_select(window)
    assert load_settings(path).slot_devices == ("keyboard:solo", "keyboard:arrows", "", "")

    start(window, settings=load_settings(path))
    press(window, keys().ENTER)
    press(window, keys().ENTER)
    css = window.current_view
    assert [slot.device for slot in css.slots[:2]] == ["keyboard:solo", "keyboard:arrows"]
    assert flow.settings.slot_devices[:2] == ("keyboard:solo", "keyboard:arrows")


# --- teams --------------------------------------------------------------------------------


def test_team_match_from_the_menus(window: Any, pads: list[FakeController]) -> None:
    flow = to_main_menu(window)
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().ENTER)
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().D)  # teams on
    assert window.current_view.setup.team_play
    press(window, keys().ESCAPE)
    assert flow.setup.team_play

    press(window, keys().ENTER)
    css = window.current_view
    press(window, keys().NUM_4)
    tap_pad(window, pads[0])
    assert [slot.team for slot in css.slots[:3]] == [0, 1, 2]
    # Player 3 moves to the red team: down to the team row, then left twice.
    pads[0].move_stick(0.0, -1.0)
    step(window, 2)
    pads[0].move_stick(0.0, 0.0)
    step(window, 2)
    assert css.slots[2].row == 1
    for _ in range(2):
        pads[0].move_stick(-1.0, 0.0)
        step(window, 2)
        pads[0].move_stick(0.0, 0.0)
        step(window, 2)
    assert css.slots[2].team == 0
    assert "< Red team >" in css._panels[2].labels[3].text
    press(window, keys().J)
    press(window, keys().NUM_4)
    tap_pad(window, pads[0])
    assert name(window) == "StageSelectView"
    press(window, keys().ENTER)
    battle = window.current_view
    assert battle.match.rules.teams == (0, 1, 0)
    assert [fighter.color_index for fighter in battle.match.fighters] == [0, 1, 0]
    step(window, COUNTDOWN_FRAMES + 2)
    knock_out(window, 1)
    for _ in range(4):
        if battle.match.result is not None:
            break
        step(window, 150)
        knock_out(window, 1)
    step(window, 200)
    assert name(window) == "ResultsView"
    assert window.current_view.ui.text is not None
    places = [line.split()[:2] for line in window.current_view.table_lines[1:]]
    assert places == [["1st", "P1"], ["1st", "P3"], ["2nd", "P2"]]


def test_everyone_on_one_team_cannot_start(window: Any) -> None:
    from dataclasses import replace

    flow = to_main_menu(window)
    flow.setup = replace(flow.setup, team_play=True, teams=(0, 0))
    press(window, keys().ENTER)
    css = window.current_view
    press(window, keys().NUM_4)
    assert [slot.team for slot in css.slots[:2]] == [0, 0]
    press(window, keys().J)
    press(window, keys().NUM_4)
    assert name(window) == "CharacterSelectView" and "one team" in css.message


# --- pause and training -------------------------------------------------------------------


def test_pause_menu_freezes_the_match_and_quits_to_character_select(window: Any) -> None:
    to_main_menu(window)
    two_players_to_stage_select(window)
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
    press(window, keys().UP)  # player 2 can drive the menu too: up from Resume wraps to Quit
    assert battle.pause_menu.selected.key == "quit"
    press(window, keys().J)
    assert name(window) == "CharacterSelectView"


def test_training_from_the_menu_has_the_training_tools(window: Any) -> None:
    from isofightr.ai.dummy import DummyBehavior
    from isofightr.sim.fighter import StateId

    to_main_menu(window)
    press(window, keys().S)
    press(window, keys().ENTER)
    css = window.current_view
    assert css.setup.training and css.slots[0].device == "keyboard:solo"
    press(window, keys().J)
    assert name(window) == "StageSelectView", "one player is enough for training"
    assert window.current_view.selected == "training_grid"
    assert window.current_view.setup.devices == ("keyboard:solo", "")
    press(window, keys().ENTER)
    battle = window.current_view
    assert battle.training and battle.match.rules.stocks is None
    assert len(battle.match.fighters) == 2, "a dummy was added"
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


# --- settings -----------------------------------------------------------------------------


def test_settings_apply_and_save(window: Any, tmp_path: Path) -> None:
    from isofightr.settings import load_settings

    path = tmp_path / "settings.toml"
    flow = to_main_menu(window, settings_path=path)
    for _ in range(3):
        press(window, keys().S)
    press(window, keys().ENTER)
    view = window.current_view
    assert name(window) == "SettingsView"
    assert view.menu.selected.text == "Window scale: < 2x >"
    press(window, keys().D)
    assert flow.settings.scale == 3 and load_settings(path).scale == 3
    assert window.get_size() == (640 * 3, 360 * 3)
    press(window, keys().A)
    assert window.get_size() == (640 * 2, 360 * 2)
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().A)
    assert flow.settings.screen_shake == 75
    for _ in range(4):
        press(window, keys().S)
    press(window, keys().D)
    assert flow.settings.gamepad_preset == "modifier_bumpers"
    press(window, keys().S)
    press(window, keys().D)
    assert flow.settings.deadzone == 0.25
    saved = load_settings(path)
    assert (saved.screen_shake, saved.gamepad_preset, saved.deadzone) == (
        75,
        "modifier_bumpers",
        0.25,
    )
    press(window, keys().ESCAPE)
    assert name(window) == "MainMenuView"
    press(window, keys().ENTER)
    assert window.current_view.hub.settings.deadzone == 0.25, "new scenes use the new settings"


def test_screen_shake_setting_scales_the_shake(window: Any) -> None:
    from dataclasses import replace

    flow = to_main_menu(window)
    flow.settings = replace(flow.settings, screen_shake=0)
    two_players_to_stage_select(window)
    press(window, keys().ENTER)
    battle = window.current_view
    step(window, 2)
    still = bytes(window.pixel_buffer.framebuffer.read(components=4))
    battle.effects.shake.start(4)
    battle.on_draw()
    assert bytes(window.pixel_buffer.framebuffer.read(components=4)) == still


def test_rebinding_a_key(window: Any, tmp_path: Path) -> None:
    from isofightr.settings import load_settings

    path = tmp_path / "settings.toml"
    flow = to_main_menu(window, settings_path=path)
    for _ in range(3):
        press(window, keys().S)
    press(window, keys().ENTER)
    for _ in range(8):
        press(window, keys().S)
    assert window.current_view.menu.selected.key == "keys_solo"
    press(window, keys().ENTER)
    view = window.current_view
    assert name(window) == "RebindView"
    for _ in range(6):
        press(window, keys().S)
    assert view.menu.selected.key == "attack" and view.menu.selected.label.endswith("J")
    press(window, keys().ENTER)
    assert view.waiting_for == "attack" and "press a key" in view.menu.selected.label
    press(window, keys().F)
    assert view.waiting_for is None
    assert flow.settings.keys["solo"]["attack"] == "F"
    assert load_settings(path).keys["solo"]["attack"] == "F"
    assert view.menu.selected.label.endswith("F")

    # Taking a key another action uses unbinds that action.
    press(window, keys().S)
    press(window, keys().ENTER)
    press(window, keys().F)
    assert flow.settings.keys["solo"]["special"] == "F"
    assert flow.settings.keys["solo"]["attack"] == ""
    press(window, keys().ENTER)
    press(window, keys().ESCAPE)  # Escape cancels the capture
    assert flow.settings.keys["solo"]["special"] == "F"

    # The new key works at once: F is now "special" = back.
    press(window, keys().F)
    assert name(window) == "SettingsView"


# --- recording from the menus -------------------------------------------------------------


def test_matches_started_from_the_menus_are_recorded(window: Any, tmp_path: Path) -> None:
    from isofightr.data.replay_io import load_replay, match_for
    from isofightr.sim.replay import play_back

    path = tmp_path / "night.json"
    to_main_menu(window, record=path)
    set_one_stock(window)
    two_players_to_stage_select(window)
    press(window, keys().ENTER)
    battle = window.current_view
    battle.on_key_press(keys().D, 0)
    step(window, COUNTDOWN_FRAMES + 40)
    battle.on_key_release(keys().D, 0)
    knock_out(window, 1)
    step(window, 200)
    assert name(window) == "ResultsView" and path.is_file()
    replay = load_replay(path)
    assert replay.characters == ("rook", "rook") and replay.rules.stocks == 1
    assert replay.ticks == battle.match.frame
    # The knock-out was forced from outside the sim, so this replay cannot match; but the
    # input up to that point is all there.
    assert not play_back(match_for(replay), replay)
    moving = [tick for tick in replay.inputs if tick[0].move.length() > 0]
    assert len(moving) >= COUNTDOWN_FRAMES

    press(window, keys().ENTER)  # rematch: a second file
    step(window, 30)
    press(window, keys().ESCAPE)
    press(window, keys().W)
    press(window, keys().J)
    assert name(window) == "CharacterSelectView"
    assert (tmp_path / "night-2.json").is_file()


def test_replay_playback_in_the_battle_scene(window: Any) -> None:
    from helpers import random_inputs
    from isofightr.data.character_loader import load_character
    from isofightr.data.replay_io import match_for
    from isofightr.data.stage_loader import load_stage
    from isofightr.scenes.battle import BattleView
    from isofightr.sim.match import MatchRules
    from isofightr.sim.replay import Recorder, Replay

    rules = MatchRules(stocks=None)
    recorder = Recorder("sky_ruins", ("rook", "rook"), 9, rules)
    match = match_for(Replay("sky_ruins", ("rook", "rook"), 9, rules, (), ""))
    for frames in random_inputs(4, 300, 2):
        recorder.record(frames)
        match.tick(frames)
    replay = recorder.finish(match)

    window.switch_to()
    rook = load_character("rook")
    view = BattleView(
        window.pixel_buffer, load_stage("sky_ruins"), [rook, rook], 9, rules=rules, replay=replay
    )
    window.show_view(view)
    view.on_key_press(keys().D, 0)  # live input is ignored during a replay
    for _ in range(310):
        step(window, 1)
    assert view.match.frame == 300 and view.replay_matches is True
    assert view.match.state_hash() == replay.final_hash
    assert view.banner_text() == "REPLAY END"
    assert view.status_line() == "REPLAY 300/300  matches the recording"


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
