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
from isofightr.sim.input_frame import Button
from isofightr.sim.math3d import Vec3

pytestmark = pytest.mark.gl

BELOW_THE_STAGE = Vec3(5.0, 5.0, -9.0)
KEYBOARD_PAIR = ("keyboard:solo", "keyboard:arrows")


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
        self.leftstick = self.rightstick = self.start = False
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

    def move_dpad(self, x: float, y: float) -> None:
        """Send a d-pad event (up positive) to everything listening."""
        from pyglet.math import Vec2

        for handler in list(self.handlers.get("on_dpad_motion", [])):
            handler(self, Vec2(x, y))

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


def test_the_rules_screen_turns_the_short_hop_macro_off(window: Any) -> None:
    flow = to_main_menu(window)
    assert flow.setup.short_hop_macro, "on by default (decision D-053)"
    press(window, keys().S)
    press(window, keys().S)
    press(window, keys().ENTER)
    assert name(window) == "RulesView"
    from isofightr.scenes.rules_model import ROW_KEYS

    rules = window.current_view
    assert ROW_KEYS.index("short_hop_macro") == ROW_KEYS.index("parry") + 1
    while rules.cursor != "short_hop_macro":
        press(window, keys().S)
    press(window, keys().D)
    assert window.current_view.setup.short_hop_macro is False
    press(window, keys().ESCAPE)
    assert flow.setup.short_hop_macro is False
    assert flow.setup.rules().short_hop_macro is False


def test_one_player_and_a_cpu_can_play_versus(window: Any) -> None:
    to_main_menu(window)
    press(window, keys().ENTER)
    css = window.current_view
    assert name(window) == "CharacterSelectView"
    press(window, keys().L)  # grab adds a CPU in the next free slot
    assert css.slots[1].cpu == 5 and css.slots[1].owner == "keyboard:solo"
    assert css.focus == {"keyboard:solo": 1}
    press(window, keys().S)  # to the level row
    press(window, keys().D)
    press(window, keys().D)
    assert css.slots[1].cpu == 7
    press(window, keys().L)  # a second CPU, then remove it again
    assert css.slots[2].cpu == 5
    press(window, keys().K)
    assert not css.slots[2].taken and "keyboard:solo" not in css.focus
    press(window, keys().J)  # ready (the CPU always is)
    assert name(window) == "StageSelectView"
    assert window.current_view.setup.cpus == (0, 7)
    assert window.current_view.setup.devices == ("keyboard:solo", "")
    press(window, keys().ENTER)
    battle = window.current_view
    assert name(window) == "BattleView"
    assert [battle.cpu_level_of(player) for player in (0, 1)] == [0, 7]
    for _ in range(300):
        step(window, 1)
    assert battle.match.fighters[1].pos != battle.match.stage.spawn_point(1), "the CPU moved"


def test_leaving_takes_your_cpus_with_you(window: Any) -> None:
    to_main_menu(window)
    press(window, keys().ENTER)
    css = window.current_view
    press(window, keys().L)
    press(window, keys().J)  # back to P1's own slot
    assert css.slots[1].cpu and not css.focus
    press(window, keys().K)  # leave
    assert not any(slot.taken for slot in css.slots)


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
        "controls",
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
    assert css.panels[0].art.visible and not css.panels[1].art.visible, "art for the joined"
    assert css.panels[0].name.text == "ROOK" and css.panels[1].prompt[1].text == "TO JOIN"
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
    go_to_stage(window, sss, "sky_ruins")
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
    assert len(results._winners) == 1, "the winner's victory animation"
    sprite = results._winners[0][2]
    seen = set()
    for _ in range(40):
        step(window, 1)
        seen.add(sprite.texture)
    assert len(seen) >= 3, "it animates"
    assert sprite.center_x < 120 and sprite.scale_x == 2

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
    press(window, keys().J)  # the time limit's switch
    assert rules.setup.time_on and rules.setup.stock_on
    press(window, keys().A)
    press(window, keys().A)
    assert rules.setup.minutes == 1 and rules._steppers["time"].label.text == "1:00"
    press(window, keys().S)
    press(window, keys().J)  # stock off: the old time mode
    assert rules.setup.time_on and not rules.setup.stock_on
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
    assert css.panels[1].tag.text == "P2  PAD 2"
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
    while window.current_view.cursor != "team_play":
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
    assert css.panels[2].line1.text == "\u2190 RED TEAM \u2192", "the team row, under the cursor"
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


def test_menus_play_the_menu_theme_and_blips_and_results_play_the_fanfare(window: Any) -> None:
    backend = window.audio.backend
    window.audio.stop_music()
    backend.played.clear()
    to_main_menu(window)
    assert window.audio.song == "menu"
    press(window, keys().S)
    assert backend.names()[-1] == "ui_move"
    press(window, keys().W)
    set_one_stock(window)
    two_players_to_stage_select(window)
    assert window.audio.song == "menu", "one theme through all the menus"
    assert backend.names().count("menu") == 1
    press(window, keys().ENTER)
    battle = window.current_view
    assert window.audio.song == battle.stage.id
    step(window, 250)
    knock_out(window, 1)
    step(window, 200)
    assert name(window) == "ResultsView"
    assert window.audio.song == "victory" and "game" in backend.names()


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
    assert [item.key for item in battle.pause_menu.items] == ["resume", "moves", "help", "quit"]
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
        "dummy_level",
        "moves",
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


def test_the_move_list_shows_each_players_own_keys(window: Any) -> None:
    to_main_menu(window)
    two_players_to_stage_select(window)
    press(window, keys().ENTER)
    battle = window.current_view
    press(window, keys().ESCAPE)
    while battle.pause_menu.selected.key != "moves":
        press(window, keys().S)
    press(window, keys().J)
    assert battle.menu_open and battle.move_list_player == 0
    title = battle._moves_title.text
    assert title.startswith("P1 ROOK MOVES (keys)")
    left = [label.text for label in battle._moves_columns[0].labels]
    assert "AIR" in left
    aerials = left[left.index("AIR") + 1 :][:6]
    assert [line.split("  ")[0].strip() for line in aerials] == [
        "Neutral air",
        "Forward air",
        "Back air",
        "Up air",
        "Down air",
        "Short-hop air",
    ]
    assert aerials[3].endswith("I + J") and aerials[5].endswith("SPACE + J together")
    step(window, 1)
    press(window, keys().D)
    assert battle.move_list_player == 1
    assert battle._moves_title.text.startswith("P2 ROOK MOVES (keys)")
    p2_left = [label.text for label in battle._moves_columns[0].labels]
    assert p2_left[left.index("AIR") + 4].endswith("NUM_8 + NUM_4"), "P2's up air"
    press(window, keys().ESCAPE)
    assert battle.menu_open and battle.move_list_player is None, "back to the pause menu"
    press(window, keys().ESCAPE)
    assert not battle.menu_open


# --- settings -----------------------------------------------------------------------------


def test_settings_apply_and_save(window: Any, tmp_path: Path) -> None:
    from isofightr.settings import load_settings

    path = tmp_path / "settings.toml"
    flow = to_main_menu(window, settings_path=path)
    for _ in range(4):
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

    # The gamepad layout and the deadzone now live on the controls screen (D-061).
    assert "gamepad_preset" not in [item.key for item in view.menu.items]
    while view.menu.selected.key != "controls":
        press(window, keys().S)
    press(window, keys().ENTER)
    assert name(window) == "ControlsView"
    controls = window.current_view
    controls.cursor = "device"
    press(window, keys().D)
    press(window, keys().D)
    controls = window.current_view
    assert controls.device == "pad:0" and controls.cursor == "device"
    assert flow.settings.slot_devices[0] == "pad:0", "the tab's player will join with it"
    controls.cursor = "layout"
    press(window, keys().D)
    assert flow.settings.pad(0).layout == "modifier_bumpers"
    assert flow.settings.pad(1).layout == "right_stick_modifiers", "this pad only"
    controls.cursor = "deadzone"
    press(window, keys().D)
    assert flow.settings.deadzone == 0.25
    saved = load_settings(path)
    assert (saved.screen_shake, saved.pad(0).layout, saved.deadzone) == (
        75,
        "modifier_bumpers",
        0.25,
    )
    press(window, keys().ESCAPE)
    assert name(window) == "SettingsView", "back to where it was opened from"
    press(window, keys().ESCAPE)
    assert name(window) == "MainMenuView"
    press(window, keys().ENTER)
    assert window.current_view.hub.settings.deadzone == 0.25, "new scenes use the new settings"


def test_resetting_the_settings_keeps_the_controls_and_the_rules(window: Any) -> None:
    from dataclasses import replace

    from isofightr.settings import SavedRules, Settings

    flow = to_main_menu(window)
    flow.settings = replace(
        Settings().with_key("solo", "taunt", "G"),
        scale=2,
        music_volume=3,
        rules=SavedRules(stocks=7),
    )
    flow.show_settings()
    step(window, 2)
    view = window.current_view
    while view.menu.selected.key != "defaults":
        press(window, keys().S)
    press(window, keys().ENTER)
    assert flow.settings.music_volume == Settings().music_volume
    assert flow.settings.bound_keys("solo", "taunt") == ("G",)
    assert flow.settings.rules.stocks == 7


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


def open_controls(window: Any, tab: int = 0, **flow_options: Any) -> tuple[Any, Any]:
    flow = start(window, **flow_options)
    flow.show_controls(tab=tab)
    step(window, 2)
    assert name(window) == "ControlsView"
    return flow, window.current_view


def test_rebinding_a_key(window: Any, tmp_path: Path) -> None:
    from isofightr.settings import load_settings
    from isofightr.ui.kit_art import Look

    path = tmp_path / "settings.toml"
    flow = to_main_menu(window, settings_path=path)
    for _ in range(3):
        press(window, keys().S)
    assert window.current_view.menu.selected.key == "controls"
    press(window, keys().ENTER)
    view = window.current_view
    assert name(window) == "ControlsView" and view.device == "keyboard:solo"
    assert view.cursor == "move_up:0", "it opens on the first cap"
    press(window, keys().D)
    assert view.cursor == "attack:0", "the stick walks from tile to tile"
    assert view.caps[("attack", 0)]._state == ("J", Look.FOCUS)
    press(window, keys().ENTER)
    assert view.listening == ("attack", 0) and view.info()[1][0] == "for ATTACK (primary)."
    step(window, 1)
    assert view.caps[("attack", 0)]._state[0] == "?", "the cap shows it is waiting"
    assert view.info_title.text == "PRESS A KEY"
    press(window, keys().F)
    assert view.listening is None
    assert flow.settings.keys["solo"]["attack"] == "F"
    assert load_settings(path).keys["solo"]["attack"] == "F"
    assert view.caps[("attack", 0)]._state[0] == "F"

    # Taking a key another action uses unbinds that action.
    press(window, keys().D)
    assert view.cursor == "special:0"
    press(window, keys().ENTER)
    press(window, keys().F)
    assert flow.settings.keys["solo"]["special"] == "F"
    assert flow.settings.keys["solo"]["attack"] == ""
    assert view.caps[("attack", 0)]._state == ("n/a", Look.DANGER), "n/a, in red"
    assert "F was taken from ATTACK" in view.message
    assert view.info_lines[2].text == view.message
    press(window, keys().ENTER)
    assert view.listening == ("special", 0)
    press(window, keys().ESCAPE)  # Escape cancels the capture
    assert view.listening is None and name(window) == "ControlsView"
    assert flow.settings.keys["solo"]["special"] == "F"
    step(window, 2)
    assert "NOT BOUND: ATTACK" in [label.text for label in view.info_lines] or view.message

    # The new key works at once: F is now "special" = back.
    press(window, keys().F)
    assert name(window) == "MainMenuView"


def test_enter_cannot_be_bound_and_keeps_the_cap_waiting(window: Any) -> None:
    flow, view = open_controls(window)
    view.cursor = "jump:0"
    press(window, keys().J)
    assert view.listening == ("jump", 0)
    press(window, keys().ENTER)
    assert view.listening == ("jump", 0) and "cannot be bound" in view.message
    assert flow.settings.bound_keys("solo", "jump") == ("SPACE",)
    press(window, keys().V)
    assert view.listening is None and flow.settings.bound_keys("solo", "jump") == ("V",)


def test_a_second_key_per_action_and_clearing_a_cap(window: Any) -> None:
    flow, view = open_controls(window)
    view.cursor = "jump:0"
    press(window, keys().S)
    assert view.cursor == "jump:1", "the small cap sits under the big one"
    press(window, keys().ENTER)
    press(window, keys().V)
    assert flow.settings.bound_keys("solo", "jump") == ("SPACE", "V")
    assert view.caps[("jump", 1)]._state[0] == "V" and view.cursor == "jump:1"

    hub_frame = view.hub.frame("keyboard:solo", {keys().V})
    assert hub_frame.held == Button.JUMP, "the second key works at once"
    assert view.hub.frame("keyboard:solo", {keys().SPACE}).held == Button.JUMP

    press(window, keys().L)  # grab clears the cap under the cursor
    assert flow.settings.bound_keys("solo", "jump") == ("SPACE",)
    view.cursor = "taunt:1"
    press(window, keys().ENTER)
    press(window, keys().G)
    assert flow.settings.bound_keys("solo", "taunt") == ("T", "G")
    view.cursor = "taunt:0"
    press(window, keys().L)
    assert flow.settings.bound_keys("solo", "taunt") == ("G",), "the second key moves up"


def test_the_live_test_lights_the_caps_of_held_keys(window: Any) -> None:
    from isofightr.ui.kit_art import Look

    _, view = open_controls(window)
    view.cursor = "back"
    view.on_key_press(keys().U, 0)
    step(window, 2)
    assert view.caps[("strong", 0)]._state == ("U", Look.LIT)
    assert view.live.text == "U" and view.side_note.text == ""
    assert view.caps[("attack", 0)]._state == ("J", Look.NORMAL)
    view.on_key_release(keys().U, 0)
    step(window, 2)
    assert view.caps[("strong", 0)]._state == ("U", Look.NORMAL)
    assert view.live.text == "" and "LIGHTS UP" in view.side_note.text


def test_default_resets_this_device_after_a_confirm(window: Any) -> None:
    flow, view = open_controls(window)
    flow.settings = flow.settings.with_key("solo", "attack", "F").with_key(
        "arrows", "attack", "RSHIFT"
    )
    view.hub.apply_settings(flow.settings)
    view.cursor = "default"
    press(window, keys().ENTER)
    assert view.confirming_default and view.buttons["default"].label.text == "SURE?"
    assert flow.settings.bound_keys("solo", "attack") == ("F",), "nothing yet"
    press(window, keys().D)
    assert not view.confirming_default and view.cursor == "back", "moving away cancels"
    press(window, keys().A)
    press(window, keys().ENTER)
    press(window, keys().ENTER)
    assert flow.settings.bound_keys("solo", "attack") == ("J",)
    assert flow.settings.bound_keys("arrows", "attack") == ("RSHIFT",), "only this device"
    assert not view.confirming_default and "default controls" in view.message


def test_tabs_show_each_players_device(window: Any, pads: list[FakeController]) -> None:
    flow, view = open_controls(window)
    assert [tab.active for tab in view.tabs] == [True, False, False, False]
    view.cursor = "tab:0"
    press(window, keys().D)
    assert view.cursor == "tab:1"
    press(window, keys().ENTER)
    view = window.current_view
    assert view.tab == 1 and view.device == "keyboard:arrows" and view.cursor == "tab:1"
    assert view.caps[("attack", 0)]._state[0] == "NUM 4"
    press(window, keys().D)
    press(window, keys().ENTER)
    view = window.current_view
    assert view.tab == 2 and view.device == "pad:0" and view.pad and view.diagram is not None
    assert view.caps[("jump", 0)]._state[0] == "X" and view.caps[("jump", 1)]._state[0] == "Y"
    assert view.caps[("stick", 0)]._state[0] == "L-STICK"
    assert ("move_up", 0) not in view.caps and "layout" in view.steppers
    assert view.side_note.text == "", "pad 1 is plugged in"
    flow.show_controls(tab=3)
    step(window, 2)
    assert window.current_view.device == "pad:1"


def test_rebinding_a_gamepad_button_changes_what_the_game_does(
    window: Any, pads: list[FakeController], tmp_path: Path
) -> None:
    from isofightr.settings import load_settings
    from isofightr.ui.kit_art import Look

    path = tmp_path / "settings.toml"
    flow, view = open_controls(window, tab=2, settings_path=path)
    pad = pads[0]
    assert view.device == "pad:0"
    assert view.hub.frame("pad:0", set()).held == 0
    view.cursor = "taunt:0"
    tap_pad(window, pad, "a")  # the pad's own A confirms
    assert view.listening == ("taunt", 0) and view.info()[1][1].startswith("Start")
    pad.move_dpad(0.0, 1.0)
    step(window, 1)
    pad.move_dpad(0.0, 0.0)
    step(window, 2)
    assert view.listening is None
    assert flow.settings.pad(0).taunt == ("dpup",) and flow.settings.pad(0).layout == "custom"
    assert load_settings(path).pad(0).taunt == ("dpup",)
    assert flow.settings.pad(1).taunt == (), "the other pad is untouched"
    assert view.steppers["layout"].label.text == "Custom"
    pad.move_dpad(0.0, 1.0)
    assert view.hub.frame("pad:0", set()).held == Button.TAUNT, "the game sees it at once"
    step(window, 2)
    assert view.caps[("taunt", 0)]._state == ("D-UP", Look.LIT), "and the live test lights it"
    pad.move_dpad(0.0, 0.0)
    step(window, 2)

    # Swap attack onto B: B is taken from special, which is left with nothing.
    view.cursor = "attack:0"
    tap_pad(window, pad, "a")
    assert view.listening == ("attack", 0)
    tap_pad(window, pad, "b")
    assert flow.settings.pad(0).attack == ("b",) and flow.settings.pad(0).special == ()
    assert view.caps[("special", 0)]._state == ("n/a", Look.DANGER)
    assert "NOT BOUND: SPECIAL" in [label.text for label in view.info_lines] or view.message
    pad.b = True
    assert view.hub.frame("pad:0", set()).held == Button.ATTACK
    pad.b = False
    step(window, 2)

    # A no longer attacks, but it still confirms in menus; Start cancels a waiting cap.
    assert name(window) == "ControlsView"
    view.cursor = "special:0"
    tap_pad(window, pad, "a")
    assert view.listening == ("special", 0), "A confirmed although nothing is bound to it"
    tap_pad(window, pad, "start")
    assert view.listening is None and flow.settings.pad(0).special == ()
    tap_pad(window, pad, "b")
    assert name(window) == "MainMenuView", "B goes back although it is bound to attack"


def test_a_gamepad_that_is_not_plugged_in_can_be_looked_at_but_not_rebound(window: Any) -> None:
    flow, view = open_controls(window, tab=2)
    assert view.device == "pad:0" and view.side_note.text == "NOT CONNECTED"
    view.cursor = "attack:0"
    press(window, keys().ENTER)
    assert view.listening is None and "not connected" in view.message
    view.cursor = "layout"
    press(window, keys().D)
    assert flow.settings.pad(0).layout == "modifier_bumpers", "layouts need no pad"
    view.cursor = "stick"
    press(window, keys().D)
    assert flow.settings.pad(0).right_stick == "modifiers"
    assert view.steppers["layout"].label.text == "Custom"


def test_the_mouse_rebinds_and_steps_on_the_controls_screen(window: Any) -> None:
    flow, view = open_controls(window)
    cap = view.rects["grab:0"]
    click(window, cap.left + 5, cap.bottom + 5)
    assert view.cursor == "grab:0" and view.listening == ("grab", 0)
    click(window, 300, 300)
    assert view.listening == ("grab", 0), "a click does nothing while a cap waits"
    press(window, keys().H)
    assert flow.settings.bound_keys("solo", "grab") == ("H",)
    device = view.rects["device"]
    click(window, device.right - 4, device.bottom + 5)
    view = window.current_view
    assert view.device == "keyboard:arrows"
    click(window, view.rects["device"].left + 4, device.bottom + 5)
    assert window.current_view.device == "keyboard:solo"
    tab = window.current_view.rects["tab:3"]
    click(window, tab.left + 20, tab.bottom + 8)
    assert window.current_view.tab == 3


def test_start_pauses_a_match_and_the_d_pad_moves_in_menus(
    window: Any, pads: list[FakeController]
) -> None:
    from isofightr.scenes.setup import MatchSetup

    flow = to_main_menu(window)
    menu = window.current_view.menu
    pads[0].move_dpad(0.0, -1.0)
    step(window, 1)
    pads[0].move_dpad(0.0, 0.0)
    step(window, 2)
    assert menu.cursor == 1, "the d-pad moves the cursor"

    flow.start_battle(MatchSetup(characters=("rook", "mote"), devices=("pad:0", "keyboard:solo")))
    step(window, COUNTDOWN_FRAMES + 5)
    battle = window.current_view
    tap_pad(window, pads[0], "start")
    assert battle.menu_open
    frame = battle.match.frame
    step(window, 3)
    assert battle.match.frame == frame, "the match is frozen"
    tap_pad(window, pads[0], "start")
    assert not battle.menu_open, "Start closes the pause menu again"

    flow.start_battle(
        MatchSetup(characters=("rook", "mote"), devices=("pad:0", "keyboard:solo"), pausing=False)
    )
    step(window, COUNTDOWN_FRAMES + 5)
    tap_pad(window, pads[0], "start")
    assert not window.current_view.menu_open, "not when the rules have pausing off"


def test_the_help_and_the_move_list_follow_a_rebind(window: Any) -> None:
    from isofightr.scenes.setup import MatchSetup

    flow = start(window)
    flow.settings = flow.settings.with_key("solo", "attack", "F")
    flow.start_battle(MatchSetup(characters=("rook", "mote"), devices=KEYBOARD_PAIR))
    step(window, 3)
    battle = window.current_view
    assert any("F attack" in line for line in battle._help_text)
    assert not any("J attack" in line for line in battle._help_text)
    _, left, right = battle.move_list_lines(0)
    assert any(line.rstrip().endswith(" F") for line in [*left, *right]), "the jab is on F"


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


# --- the Rules screen (M13 group 1, decision D-061) ---------------------------------------


def open_rules(window: Any, **flow_options: Any) -> tuple[Any, Any]:
    flow = start(window, **flow_options)
    flow.show_rules()
    step(window, 2)
    assert name(window) == "RulesView"
    return flow, window.current_view


def go_to(window: Any, key: str) -> None:
    """Walk the rules cursor down to a row or button."""
    for _ in range(40):
        if window.current_view.cursor == key:
            return
        press(window, keys().S)
    raise AssertionError(f"never reached {key}")


def click(window: Any, x: float, y: float) -> None:
    """Left-click the middle of a native pixel."""
    import arcade

    view = window.current_view
    viewport = view.window_viewport()
    ratio = window.get_pixel_ratio()
    view.on_mouse_press(
        round((viewport.left + (x + 0.5) * viewport.scale) / ratio),
        round((viewport.bottom + (y + 0.5) * viewport.scale) / ratio),
        arcade.MOUSE_BUTTON_LEFT,
        0,
    )
    step(window, 2)


def test_every_rules_row_changes_its_own_rule(window: Any) -> None:
    from isofightr.scenes.rules_model import ROW_KEYS, RULE_ROWS, row_on, row_value

    flow, rules = open_rules(window)
    assert rules.cursor == "time" and list(rules._rows) == list(ROW_KEYS)
    for row in RULE_ROWS:
        go_to(window, row.key)
        before = rules.setup
        if row.has_value:
            press(window, keys().D)
            assert row_value(rules.setup, row.key) != row_value(before, row.key), row.key
            assert rules._steppers[row.key].label.text == row_value(rules.setup, row.key)
            press(window, keys().A)
            assert rules.setup == before
        if row.has_switch:
            press(window, keys().J)
            assert row_on(rules.setup, row.key) is (not row_on(before, row.key)), row.key
            assert rules._switches[row.key].on is row_on(rules.setup, row.key)
            assert flow.setup == rules.setup, "kept at once, not on leaving"
            press(window, keys().J)
            if row.key not in ("time", "stock"):
                assert rules.setup == before
    assert set(rules._steppers) == {row.key for row in RULE_ROWS if row.has_value}
    assert set(rules._switches) == {row.key for row in RULE_ROWS if row.has_switch}


def test_the_last_of_time_and_stock_cannot_be_switched_off(window: Any) -> None:
    _, rules = open_rules(window)
    go_to(window, "stock")
    press(window, keys().J)
    assert rules.setup.time_on and not rules.setup.stock_on, "the clock came on instead"
    assert rules._switches["time"].on and not rules._switches["stock"].on
    press(window, keys().W)
    press(window, keys().J)
    assert rules.setup.stock_on and not rules.setup.time_on
    press(window, keys().J)
    assert rules.setup.stock_on and rules.setup.time_on
    assert "most stocks" in rules.help.text, "the help line explains both on"


def test_default_restores_every_rule_at_once(window: Any) -> None:
    from isofightr.scenes.setup import MatchSetup

    flow, rules = open_rules(window)
    for key, key_press in (
        ("stock", keys().D),
        ("start_damage", keys().D),
        ("parry", keys().J),
        ("hud_display", keys().J),
        ("pausing", keys().J),
    ):
        go_to(window, key)
        press(window, key_press)
    assert flow.setup.rules() != MatchSetup().rules() and not flow.setup.pausing
    go_to(window, "pool")
    press(window, keys().D)
    assert rules.cursor == "default"
    press(window, keys().J)
    assert name(window) == "RulesView", "no confirm step, and it stays on the screen"
    assert rules.setup == MatchSetup() and flow.setup == MatchSetup()
    assert rules._steppers["stock"].label.text == "3" and not rules._switches["parry"].on
    press(window, keys().D)
    assert rules.cursor == "back"
    press(window, keys().D)
    assert rules.cursor == "back", "the buttons do not wrap"
    press(window, keys().J)
    assert name(window) == "MainMenuView"


def test_the_rules_cursor_wraps_through_rows_and_buttons(window: Any) -> None:
    _, rules = open_rules(window)
    press(window, keys().W)
    assert rules.cursor == "back", "up from the first row"
    press(window, keys().S)
    assert rules.cursor == "time"
    go_to(window, "pausing")
    press(window, keys().S)
    assert rules.cursor == "pool"
    press(window, keys().W)
    assert rules.cursor == "pausing"


def test_the_mouse_steps_and_switches_rules(window: Any) -> None:
    _, rules = open_rules(window)
    stepper = rules._steppers["stock"].rect
    y = stepper.bottom + stepper.height // 2
    click(window, stepper.right - 6, y)
    assert rules.cursor == "stock" and rules.setup.stocks == 4, "the right half steps up"
    click(window, stepper.left + 6, y)
    click(window, stepper.left + 6, y)
    assert rules.setup.stocks == 2, "the left half steps down"
    switch = rules._switches["parry"].rect
    click(window, switch.left + 5, switch.bottom + 5)
    assert rules.setup.parry and rules.cursor == "parry"
    row = rules.rects["player_tags"]
    click(window, row.left + 60, row.bottom + 5)
    assert rules.setup.player_tags, "anywhere on a switch row flips it"
    launch = rules.rects["launch_rate"]
    click(window, launch.left + 60, launch.bottom + 5)
    assert rules.setup.launch_rate == 1.25, "a value row without a switch steps forward"
    default = rules.buttons["default"].rect
    click(window, default.left + 10, default.bottom + 5)
    assert rules.setup.stocks == 3 and not rules.setup.parry
    click(window, 4, 200)
    assert name(window) == "RulesView", "a click on nothing does nothing"


def test_rules_are_saved_and_loaded_at_start(window: Any, tmp_path: Path) -> None:
    from isofightr.scenes.setup import MatchSetup
    from isofightr.settings import load_settings

    path = tmp_path / "settings.toml"
    open_rules(window, settings_path=path)
    go_to(window, "stock")
    press(window, keys().D)
    go_to(window, "start_damage")
    press(window, keys().D)
    press(window, keys().D)
    go_to(window, "score_display")
    press(window, keys().J)
    saved = load_settings(path).rules
    assert (saved.stocks, saved.start_damage, saved.score_display) == (4, 20, True)

    again = start(window, settings=load_settings(path), settings_path=path)
    assert again.setup.stocks == 4 and again.setup.start_damage == 20 and again.setup.score_display
    assert again.setup.rules().start_damage == 20.0
    path.write_text("[rules]\nstocks = -4\nparry = 3\nstart_damage = 40\n", "utf-8")
    broken = start(window, settings=load_settings(path), settings_path=path)
    assert broken.setup == MatchSetup(start_damage=40), "bad values fall back one by one"


def test_rules_can_lead_back_somewhere_else(window: Any) -> None:
    flow = start(window)
    flow.show_rules(lambda: flow.show_character_select(flow.setup))
    step(window, 2)
    press(window, keys().K)
    assert name(window) == "CharacterSelectView"


def test_the_random_stage_pool_keeps_one_stage_and_random_picks_from_it(window: Any) -> None:
    from dataclasses import replace

    from isofightr.data.stage_loader import list_stage_ids

    flow, _ = open_rules(window)
    go_to(window, "pool")
    press(window, keys().J)
    assert name(window) == "RandomPoolView"
    pool = window.current_view
    stages = list_stage_ids()
    assert pool.stages == stages and pool.cursor == stages[0]
    keep = stages[2]
    for stage_id in stages:
        if stage_id != keep:
            while pool.cursor != stage_id:
                press(window, keys().S)
            press(window, keys().J)
    assert flow.setup.pool(stages) == [keep] and flow.setup.random_pool == (keep,)
    while pool.cursor != keep:
        press(window, keys().S)
    press(window, keys().J)
    assert flow.setup.pool(stages) == [keep], "the last stage cannot be taken out"
    press(window, keys().K)
    assert name(window) == "RulesView" and window.current_view.cursor == "pool"
    assert window.current_view.buttons["pool"].label.text.endswith(f"1/{len(stages)}")

    setup = replace(
        flow.setup, stage="random", characters=("rook", "rook"), devices=("keyboard:solo", "")
    )
    for _ in range(6):
        flow.start_battle(setup)
        assert window.current_view.stage.id == keep
    everything = replace(setup, random_pool=())
    seen = set()
    for _ in range(40):
        flow.start_battle(everything)
        seen.add(window.current_view.stage.id)
    assert len(seen) > 1, "with every stage in, random still varies"


def go_to_stage(window: Any, view: Any, stage_id: str) -> None:
    """Walk stage select's cursor to a stage, a row at a time, then along the row."""
    from isofightr.scenes.stage_info import STAGE_COLUMNS

    target = view.stage_ids.index(stage_id)
    for _ in range(20):
        if view.selected == stage_id:
            return
        row, target_row = view.cursor // STAGE_COLUMNS, target // STAGE_COLUMNS
        key = keys().S if row < target_row else keys().W if row > target_row else keys().D
        press(window, key)
    raise AssertionError(f"could not reach {stage_id}")


def battle_with(window: Any, **options: Any) -> Any:
    from isofightr.scenes.setup import MatchSetup

    flow = start(window)
    setup = MatchSetup(
        characters=("rook", "mote"), devices=("keyboard:solo", "keyboard:arrows"), **options
    )
    flow.start_battle(setup)
    step(window, COUNTDOWN_FRAMES + 5)
    return window.current_view


def test_hud_display_off_keeps_only_the_clock_and_the_countdown(window: Any) -> None:
    from isofightr.capture import read_frame

    shown = battle_with(window, time_on=True)
    assert shown.hud_display and shown.clock.text
    with_hud = read_frame(window)
    hidden = battle_with(window, time_on=True, hud_display=False, player_tags=True)
    assert not hidden.hud_display and hidden.clock.text == shown.clock.text
    without = read_frame(window)
    assert with_hud.tobytes() != without.tobytes()
    low = (0, 250, 640, 360)  # the HUD's strip at the bottom of the picture
    assert with_hud.crop(low).tobytes() != without.crop(low).tobytes()
    top = (260, 0, 380, 30)  # the clock
    assert with_hud.crop(top).tobytes() == without.crop(top).tobytes(), "the clock stays"
    fresh = start(window)
    from isofightr.scenes.setup import MatchSetup

    fresh.start_battle(
        MatchSetup(characters=("rook", "mote"), devices=KEYBOARD_PAIR, hud_display=False)
    )
    step(window, 5)
    assert window.current_view.banner.text == "3", "the countdown still shows"


def test_score_display_shows_kos_minus_falls(window: Any) -> None:
    plain = battle_with(window)
    assert plain.hud.score_shown(0) == "", "off by default"
    battle = battle_with(window, score_display=True)
    assert battle.hud.score_shown(0) == "0" and battle.hud.score_shown(1) == "0"
    knock_out(window, 1)
    step(window, 2)
    assert battle.hud.score_shown(1) == "-1" and battle.hud.score_shown(0) == "0"


def test_player_tags_float_over_the_fighters(window: Any) -> None:
    plain = battle_with(window)
    assert not plain.tag_shown(0), "off by default"
    battle = battle_with(window, player_tags=True, cpus=(0, 4))
    assert battle.tag_shown(0) and battle.tag_shown(1)
    names = [name_label.text for name_label, _ in battle._tags]
    assert names == ["P1", "CPU"]
    name_label, arrow = battle._tags[0]
    fighter = battle.match.fighters[0]
    [(x, head)] = battle._screen_positions([fighter], fighter.character.body.height)
    [(_, feet)] = battle._screen_positions([fighter], 0.0)
    assert abs(name_label.x - x) <= 1 and arrow.bottom > head > feet, "above the head"
    assert name_label.bottom > arrow.bottom
    knock_out(window, 0)
    step(window, 2)
    assert not battle.tag_shown(0) and battle.tag_shown(1), "no tag while out of play"


def test_pausing_off_disables_the_pause_menu_in_versus_only(window: Any) -> None:
    from isofightr.scenes.setup import training_setup

    battle = battle_with(window, pausing=False)
    press(window, keys().ESCAPE)
    assert not battle.menu_open and not battle.paused and "pausing is off" in battle._message
    frame = battle.match.frame
    step(window, 3)
    assert battle.match.frame == frame + 3, "the match runs on"
    allowed = battle_with(window)
    press(window, keys().ESCAPE)
    assert allowed.menu_open

    flow = start(window)
    flow.setup = flow.setup.__class__(pausing=False)
    flow.start_battle(training_setup())
    step(window, 3)
    press(window, keys().ESCAPE)
    assert window.current_view.menu_open, "training can always pause"


def hold_keys(window: Any, *held: int) -> None:
    """Hold keys down together for one tick, then let them go."""
    view = window.current_view
    for key in held:
        view.on_key_press(key, 0)
    view.on_update(TICK_SECONDS)
    for key in held:
        window.current_view.on_key_release(key, 0)
        if window.current_view is not view:
            view.on_key_release(key, 0)
    step(window, 2)


def test_backspace_attack_and_special_quit_a_match_that_cannot_pause(window: Any) -> None:
    battle = battle_with(window, pausing=False)
    hold_keys(window, keys().BACKSPACE, keys().J)
    hold_keys(window, keys().J, keys().K)
    assert window.current_view is battle, "all three, together"
    hold_keys(window, keys().BACKSPACE, keys().NUM_4, keys().NUM_5)
    assert name(window) == "CharacterSelectView", "either keyboard player can quit"

    allowed = battle_with(window)
    hold_keys(window, keys().BACKSPACE, keys().J, keys().K)
    assert window.current_view is allowed, "with pausing on, the pause menu has Quit"

    hinted = battle_with(window, pausing=False)
    press(window, keys().ESCAPE)
    assert "BACKSPACE" in hinted._message


# --- character select: the roster grid, costumes, the rules chip (M13 group 5) --------------


def open_select(window: Any, **flow_options: Any) -> tuple[Any, Any]:
    flow = to_main_menu(window, **flow_options)
    press(window, keys().ENTER)
    assert name(window) == "CharacterSelectView"
    return flow, window.current_view


def test_the_roster_grid_lists_every_character_and_random(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids

    _, css = open_select(window)
    assert css.tiles == (*list_character_ids(), "random")
    assert len(css.tile_rects) == len(css.tiles)
    for first, second in zip(css.tile_rects, css.tile_rects[1:], strict=False):
        assert not first.overlaps(second)
    assert all(not rect.overlaps(panel.rect) for rect in css.tile_rects for panel in css.panels)
    assert css.character_of(css.slots[0]) == "rook", "the setup's character, as before"
    assert css.detail_name.text == "ROOK" and css.detail_kind.text == "the all-rounder"
    assert all(0.0 < css.gauges[stat].value <= 1.0 for stat in css.gauges)


def test_a_cursor_walks_the_roster_and_the_panel_and_detail_follow(window: Any) -> None:
    _, css = open_select(window)
    slot, panel = css.slots[0], css.panels[0]
    start = slot.character
    press(window, keys().D)
    assert slot.character == (start + 1) % len(css.tiles)
    hovered = css.character_of(slot)
    assert panel.name.text == hovered.upper() and css.detail_name.text == hovered.upper()
    assert css.cursors[0].sprite.visible and css.cursor_tags[0].text == "P1"
    tile = css.tile_rects[slot.character]
    assert abs(css.cursors[0].sprite.center_x - (tile.left + tile.width / 2)) < 1
    while css.character_of(slot) != "random":
        press(window, keys().D)
    assert panel.name.text == "RANDOM" and panel.unknown.visible and not panel.art.visible
    assert css.detail_kind.text == "the wildcard"
    assert not any(swatch.sprite.visible for swatch in panel.swatches), "no costume for Random"
    press(window, keys().D)
    assert slot.character == 0, "the cursor wraps along the row"
    press(window, keys().A)
    assert css.character_of(slot) == "random"


def test_bramble_and_zephyr_show_opposite_stat_bars(window: Any) -> None:
    _, css = open_select(window)
    slot = css.slots[0]
    bars = {}
    for _ in range(len(css.tiles)):
        bars[css.character_of(slot)] = {stat: css.gauges[stat].value for stat in css.gauges}
        press(window, keys().D)
    assert bars["bramble"]["weight"] == 1.0 and bars["zephyr"]["weight"] == pytest.approx(0.2)
    assert bars["zephyr"]["speed"] == 1.0 and bars["bramble"]["speed"] == pytest.approx(0.2)
    assert bars["bramble"]["power"] > bars["zephyr"]["power"]
    assert bars["random"] == dict.fromkeys(bars["random"], 0.0)


def test_strong_changes_costume_and_two_players_never_share_one(window: Any) -> None:
    flow, css = open_select(window)
    first, second = css.slots[0], css.slots[1]
    assert first.costume == 0, "player 1 starts in the character's own colours"
    press(window, keys().U)
    assert first.costume == 1 and css.shown_costume(0) == 1
    shown = [swatch.sprite.visible for swatch in css.panels[0].swatches]
    assert shown == [True] * 6, "six costumes, six swatches"
    press(window, keys().I)  # the up modifier is the same as strong
    assert first.costume == 2
    press(window, keys().COMMA)  # the down modifier goes back
    press(window, keys().COMMA)
    press(window, keys().COMMA)
    assert first.costume == 5, "it wraps"
    press(window, keys().U)
    assert first.costume == 0

    press(window, keys().NUM_4)  # player 2 joins, on the same character
    while css.character_of(second) != css.character_of(first):
        press(window, keys().RIGHT)
    assert second.costume != first.costume, "never the same costume on the same character"
    taken = second.costume
    for _ in range(6):
        press(window, keys().U)
        assert first.costume != taken, "player 1 skips the one player 2 wears"
    art_one, art_two = css.panels[0].art.texture, css.panels[1].art.texture
    assert art_one is not art_two

    press(window, keys().J)
    press(window, keys().NUM_4)
    assert name(window) == "StageSelectView"
    setup = window.current_view.setup
    assert setup.costumes == (first.costume, second.costume)
    press(window, keys().ENTER)
    battle = window.current_view
    fighters = battle.match.fighters
    assert [battle.costume(fighter, 6) for fighter in fighters] == list(setup.costumes)
    assert flow.setup.costumes == setup.costumes, "a rematch keeps them"


def test_a_ready_player_cannot_change_character_or_costume(window: Any) -> None:
    _, css = open_select(window)
    slot = css.slots[0]
    press(window, keys().NUM_4)
    press(window, keys().J)
    assert slot.ready and css.panels[0].sash.sprite.visible
    assert css.panels[0].sash_text.text == "READY!" and "cancel" in css.panels[0].line2.text
    before = (slot.character, slot.costume)
    press(window, keys().D)
    press(window, keys().U)
    assert (slot.character, slot.costume) == before
    press(window, keys().K)
    assert not slot.ready and css.slots[0].device, "back un-readies first"


def test_random_is_resolved_when_the_match_starts(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids

    _, css = open_select(window)
    while css.character_of(css.slots[0]) != "random":
        press(window, keys().D)
    press(window, keys().NUM_4)
    assert css.current_setup().characters[0] == "random", "not yet"
    press(window, keys().J)
    press(window, keys().NUM_4)
    assert name(window) == "StageSelectView"
    picked = window.current_view.setup.characters
    assert picked[0] in list_character_ids() and "random" not in picked


def test_the_rules_chip_opens_the_rules_and_everyone_is_still_there_after(window: Any) -> None:
    flow, css = open_select(window)
    press(window, keys().NUM_4)
    press(window, keys().D)
    character = css.slots[0].character
    assert css.chip.label.text == "STOCK 3  1.0x  TEAMS OFF"
    press(window, keys().W)
    assert css.slots[0].row == -1 and css.chip.look.value == "focus"
    press(window, keys().K)
    assert css.slots[0].row == 0 and css.slots[0].device, "back leaves the chip, not the slot"
    press(window, keys().W)
    press(window, keys().J)
    assert name(window) == "RulesView"
    go_to(window, "stock")
    press(window, keys().D)
    go_to(window, "team_play")
    press(window, keys().J)
    press(window, keys().K)
    assert window.current_view is css, "the same screen, not a new one"
    assert [slot.device for slot in css.slots[:2]] == ["keyboard:solo", "keyboard:arrows"]
    assert css.slots[0].character == character and css.slots[0].row == 0
    step(window, 2)
    assert css.setup.stocks == 4 and css.setup.team_play
    assert css.chip.label.text == "STOCK 4  1.0x  TEAMS ON"
    assert css.panels[1].line1.text == "BLUE TEAM", "team rows appeared"
    assert not any(swatch.sprite.visible for swatch in css.panels[0].swatches), (
        "team colours, not costumes, in a team match"
    )
    assert flow.setup.stocks == 4


def test_training_has_no_rules_chip_and_no_cpus(window: Any) -> None:
    to_main_menu(window)
    press(window, keys().S)
    press(window, keys().ENTER)
    css = window.current_view
    assert css.setup.training and css.chip is None
    press(window, keys().W)
    assert css.slots[0].row == 0, "nothing above the roster"
    press(window, keys().L)
    assert not css.slots[1].taken, "grab adds no CPU in training"
    assert css.panels[1].prompt[2].text == ""


def test_a_cpu_gets_a_cursor_while_it_is_set_up(window: Any) -> None:
    _, css = open_select(window)
    press(window, keys().L)
    cpu = css.slots[1]
    assert cpu.cpu == 5 and css.cursor_tags[1].text == "CPU" and css.cursors[1].sprite.visible
    assert css.panels[1].tag.text == "P2  CPU 5" and css.detail_slot == 1
    before, own = cpu.character, css.slots[0].character
    press(window, keys().D)
    assert cpu.character != before and css.slots[0].character == own, "the CPU's cursor moved"
    assert css.panels[1].name.text == css.character_of(cpu).upper()
    costume = cpu.costume
    press(window, keys().U)
    assert cpu.costume != costume, "strong changes the CPU's costume while it is set up"
    press(window, keys().S)
    assert cpu.row == 1 and css.panels[1].line1.text == "\u2190 LEVEL 5 \u2192"
    press(window, keys().J)
    assert not css.focus and not css.cursors[1].sprite.visible, "done: its cursor goes"
    assert css.panels[1].line1.text == "LEVEL 5"


def test_the_mouse_picks_fighters_costumes_and_the_rules(window: Any) -> None:
    _, css = open_select(window)
    slot = css.slots[0]
    target = css.tiles.index("mote")
    rect = css.tile_rects[target]
    click(window, rect.left + 10, rect.bottom + 20)
    assert slot.character == target and css.panels[0].name.text == "MOTE"
    swatch = css.panels[0].swatch_rects[3]
    click(window, swatch.left + 3, swatch.bottom + 3)
    assert slot.costume == 3
    click(window, 300, 250)
    assert slot.character == target and name(window) == "CharacterSelectView"
    banner = css.panels[0].banner_rect
    click(window, banner.left + 20, banner.bottom + 10)
    assert slot.ready or "two players" in css.message
    chip = css.chip.rect
    click(window, chip.left + 30, chip.bottom + 8)
    assert name(window) == "RulesView"


def test_the_toast_says_why_a_match_cannot_start(window: Any) -> None:
    _, css = open_select(window)
    press(window, keys().J)
    assert "two players" in css.message and css._status.text == css.message
    assert css.toast.sprite.visible
    press(window, keys().D)
    assert css.message == "" and not css.toast.sprite.visible, "it clears on the next input"


# --- stage select: previews, the random pool, the rules chips (M13 group 6) -----------------


def open_stage_select(window: Any, **setup_options: Any) -> tuple[Any, Any]:
    from isofightr.scenes.setup import MatchSetup

    flow = start(window)
    options = {"characters": ("rook", "mote"), "devices": ("keyboard:solo", "keyboard:arrows")}
    flow.show_stage_select(MatchSetup(**{**options, **setup_options}))
    step(window, 2)
    assert name(window) == "StageSelectView"
    return flow, window.current_view


def test_stage_select_shows_the_stage_under_the_cursor(window: Any) -> None:
    from isofightr.data.stage_loader import list_stage_ids

    _, sss = open_stage_select(window, stage="sky_ruins")
    assert sss.stage_ids == [*list_stage_ids(), "random"]
    assert sss.selected == "sky_ruins" and sss.name_label.text == "SKY RUINS"
    assert sss.description.text.endswith(".") and sss.music_label.text
    sky = sss.preview.sprite.texture
    assert sky.width == 400 and sky.height == 206
    for first, second in zip(sss.tile_rects, sss.tile_rects[1:], strict=False):
        assert not first.overlaps(second)
    go_to_stage(window, sss, "final_plateau")
    assert sss.name_label.text == "FINAL PLATEAU" and sss.preview.sprite.texture is not sky
    go_to_stage(window, sss, "random")
    assert sss.name_label.text == "RANDOM" and "pool" in sss.description.text
    assert sss.chips, "the rules as chips"


def test_grab_takes_a_stage_out_of_the_random_pool_and_the_rules_see_it(window: Any) -> None:
    from isofightr.data.stage_loader import list_stage_ids

    flow, sss = open_stage_select(window, stage="final_plateau")
    stages = list_stage_ids()
    assert (
        sss.pool == stages and sss.pool_label.text == f"RANDOM POOL {len(stages)} / {len(stages)}"
    )
    press(window, keys().L)
    assert "final_plateau" not in sss.pool and flow.setup.random_pool
    assert "final_plateau" not in flow.settings.rules.random_pool, "saved with the rules"
    assert sss.pool_label.text == f"RANDOM POOL {len(stages) - 1} / {len(stages)}"
    press(window, keys().L)
    assert sss.pool == stages and flow.setup.random_pool == (), "every stage again"
    go_to_stage(window, sss, "random")
    press(window, keys().L)
    assert sss.pool == stages, "Random itself is not in the pool"

    for stage_id in stages[1:]:
        go_to_stage(window, sss, stage_id)
        press(window, keys().L)
    assert sss.pool == stages[:1]
    go_to_stage(window, sss, stages[0])
    press(window, keys().L)
    assert sss.pool == stages[:1], "the last stage stays"

    go_to_stage(window, sss, "random")
    press(window, keys().J)
    assert name(window) == "BattleView" and window.current_view.stage.id == stages[0], (
        "Random picks from the pool"
    )


def test_clicking_a_box_toggles_the_pool_and_a_tile_fights_there(window: Any) -> None:
    _, sss = open_stage_select(window, stage="sky_ruins")
    index = sss.stage_ids.index("lily_pads")
    box = sss.checkboxes[index]
    click(window, box.rect.left + 3, box.rect.bottom + 3)
    step(window, 1)
    assert sss.selected == "lily_pads" and "lily_pads" not in sss.pool
    rect = sss.tile_rects[sss.stage_ids.index("twin_isles")]
    click(window, rect.left + 20, rect.bottom + 30)
    step(window, 1)
    assert name(window) == "BattleView" and window.current_view.stage.id == "twin_isles"


def test_training_stage_select_has_no_pool_boxes(window: Any) -> None:
    from isofightr.scenes.setup import training_setup

    flow = start(window)
    flow.show_stage_select(training_setup())
    step(window, 2)
    sss = window.current_view
    assert all(box is None for box in sss.checkboxes) and not sss.chips
    pool = sss.pool
    press(window, keys().L)
    assert sss.pool == pool and sss.pool_label.text == ""


def test_character_select_draws_the_stage_pictures_ahead(window: Any) -> None:
    from isofightr.data.stage_loader import list_stage_ids
    from isofightr.render import stage_preview

    open_select(window)
    step(window, len(list_stage_ids()) + 1)
    assert not stage_preview.warm_next(window), "every stage has its picture already"
