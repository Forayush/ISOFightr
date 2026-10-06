"""The boot splash, title, main menu and loading screen on a real window (``pytest -m gl``).

Plan note "13 - Game Modes UI and Flow", decision D-061 (M13 group 3).
"""

import itertools
from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS

pytestmark = pytest.mark.gl


class NoControllers:
    """Stands in for pyglet's ``ControllerManager``: nothing is plugged in."""

    opened = 0

    def __init__(self) -> None:
        type(self).opened += 1

    def push_handlers(self, **handlers: Any) -> None:
        pass

    def remove_handlers(self, **handlers: Any) -> None:
        pass

    def get_controllers(self) -> list[Any]:
        return []


@pytest.fixture(autouse=True)
def no_real_controllers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever is plugged into this machine must not act in the tests."""
    import pyglet

    NoControllers.opened = 0
    monkeypatch.setattr(pyglet.input, "ControllerManager", NoControllers)


def keys() -> Any:
    import arcade

    return arcade.key


def flow_for(window: Any, **options: Any) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    return GameFlow(window, window.pixel_buffer, seed=1, **options)


def step(window: Any, ticks: int = 1) -> None:
    for _ in range(ticks):
        window.current_view.on_update(TICK_SECONDS)
    window.current_view.on_draw()


def press(window: Any, key: int) -> None:
    view = window.current_view
    view.on_key_press(key, 0)
    view.on_update(TICK_SECONDS)
    window.current_view.on_key_release(key, 0)
    if window.current_view is not view:
        view.on_key_release(key, 0)
    step(window, 2)


def name(window: Any) -> str:
    return type(window.current_view).__name__


def click(window: Any, x: float, y: float) -> None:
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


def frame(window: Any) -> Any:
    from isofightr.capture import read_frame

    return read_frame(window)


def versus(**options: Any) -> Any:
    from isofightr.scenes.setup import MatchSetup

    return MatchSetup(
        characters=("rook", "mote"), devices=("keyboard:solo", "keyboard:arrows"), **options
    )


# --- one device hub ------------------------------------------------------------------------


def test_the_devices_are_opened_once_for_the_whole_session(window: Any) -> None:
    from dataclasses import replace

    flow = flow_for(window)
    flow.show_title()
    hub = window.current_view.hub
    assert NoControllers.opened == 1
    for show in (flow.show_main_menu, flow.show_rules, flow.show_controls, flow.show_settings):
        show()
        step(window, 2)
        assert window.current_view.hub is hub
    flow.start_battle(versus())
    step(window, 2)
    assert window.current_view.hub is hub, "a match from the menus uses them too"
    flow.show_main_menu()
    step(window, 2)
    assert NoControllers.opened == 1, "leaving the battle did not close and reopen them"
    assert hub.frame("keyboard:solo", {keys().J}).held, "and they still work"
    flow.settings = replace(flow.settings, deadzone=0.3)
    assert flow.hub() is hub and hub.settings.deadzone == 0.3, "it follows the settings"
    flow.update_settings(flow.settings.with_key("solo", "attack", "F"))
    assert flow.hub().frame("keyboard:solo", {keys().F}).held


def test_a_sandbox_battle_still_opens_and_closes_its_own_devices(window: Any) -> None:
    from isofightr.data.character_loader import load_character
    from isofightr.data.stage_loader import load_stage
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    rook = load_character("rook")
    view = BattleView(window.pixel_buffer, load_stage("training_grid"), [rook, rook])
    assert view.hub is None and view.inputs is not None, "the fixed assignment, as before"


# --- boot and title ------------------------------------------------------------------------


def test_the_boot_splash_shows_the_logo_then_the_title(window: Any) -> None:
    flow = flow_for(window)
    flow.show_boot()
    assert name(window) == "BootView" and NoControllers.opened == 0, "nothing slow yet"
    window.current_view.on_draw()
    splash = frame(window)
    colours = {colour[:3] for _, colour in splash.getcolors(maxcolors=100000)}
    from isofightr.ui import logo

    assert {logo.FACE, logo.SIDE} <= colours, "the logo is on screen at once"
    step(window, 1)
    assert name(window) == "BootView", "it is drawn before anything else happens"
    step(window, 2)
    assert name(window) == "TitleView" and NoControllers.opened == 1


def test_the_title_drops_its_logo_in_and_shows_the_fighters_idling(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids
    from isofightr.scenes import front
    from isofightr.sim.fighter import StateId

    flow = flow_for(window)
    flow.show_title()
    view = window.current_view
    step(window, 1)
    high = view.logo.center_y
    assert high > front.LOGO_BOTTOM + view.logo.texture.height, "it starts above its place"
    step(window, front.LOGO_DROP_TICKS + 2)
    rest = view.logo.center_y - view.logo.texture.height / 2
    assert abs(rest - front.LOGO_BOTTOM) <= 2, "and comes to rest"
    assert float(view.logo.left).is_integer() and float(view.logo.bottom).is_integer()

    fighters = view.island.match.fighters
    assert [fighter.character.id for fighter in fighters] == list_character_ids()[:4]
    assert all(fighter.state is StateId.IDLE for fighter in fighters)
    before = fighters[0].state_frame
    step(window, 10)
    assert fighters[0].state_frame == before + 10, "their idle animation runs"
    assert len({(round(f.pos.x + f.pos.y, 3)) for f in fighters}) == 1, "one row: none in front"
    xs = [fighter.pos.x - fighter.pos.y for fighter in fighters]
    assert xs == sorted(xs), "left to right across the screen"

    shot = frame(window)
    colours = shot.getcolors(maxcolors=200000)
    assert colours is not None and len(colours) > 60, "sky, island, sprites and logo"


def test_the_title_prompt_names_the_control_and_any_confirm_starts(window: Any) -> None:
    flow = flow_for(window)
    flow.settings = flow.settings.with_key("solo", "attack", "F")
    flow.show_title()
    step(window, 2)
    view = window.current_view
    assert view.prompt_text() == "PRESS F OR ENTER"
    assert view.prompt.visible
    step(window, 30)
    assert not view.prompt.visible, "it blinks"
    press(window, keys().F)
    assert name(window) == "MainMenuView"
    press(window, keys().K)
    assert name(window) == "TitleView", "special goes back to the title"
    click(window, 300, 200)
    assert name(window) == "MainMenuView", "a click anywhere starts too"


# --- main menu -----------------------------------------------------------------------------


def test_the_main_menu_has_a_button_and_a_preview_for_everything(window: Any) -> None:
    from isofightr.scenes import front
    from isofightr.scenes.rules_model import RULE_ROWS

    flow = flow_for(window)
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    entries = [key for key, _, _, _ in front.MENU_ENTRIES]
    assert entries == ["versus", "training", "rules", "controls", "settings", "quit"]
    assert [item.key for item in view.menu.items] == entries == list(view.buttons)
    assert set(view.pages) == set(entries)
    rects = [button.rect for button in view.buttons.values()]
    for upper, lower in itertools.pairwise(rects):
        assert lower.top <= upper.bottom, "the buttons do not overlap"
    assert all(not rect.overlaps(front.PREVIEW) for rect in rects)
    assert rects[-1].bottom >= 18 and front.PREVIEW.right <= NATIVE_W
    assert len(view.preview_lines("rules")) == len(RULE_ROWS), "every rule, at a glance"
    assert "Keyboard (WASD)" in view.preview_lines("controls")[0][0]
    assert set(view.islands) == {"versus", "training"}
    assert len(view.islands["training"].match.fighters) == 1

    shots = {}
    for key in entries:
        assert view.selected == key
        view.on_draw()
        shots[key] = frame(window).crop((300, 40, 630, 320)).tobytes()
        press(window, keys().S)
    assert view.selected == "versus", "the cursor wraps"
    assert len(set(shots.values())) == len(entries), "each button has its own preview"


def test_the_main_menu_goes_where_its_buttons_say(window: Any) -> None:
    flow = flow_for(window)
    where = {
        "versus": "CharacterSelectView",
        "training": "CharacterSelectView",
        "rules": "RulesView",
        "controls": "ControlsView",
        "settings": "SettingsView",
    }
    for key, scene in where.items():
        flow.show_main_menu()
        step(window, 2)
        view = window.current_view
        while view.selected != key:
            press(window, keys().S)
        press(window, keys().J)
        assert name(window) == scene, key
        if key == "training":
            assert window.current_view.setup.training
        for _ in range(3):  # character select first lets the player leave their slot
            if name(window) != "MainMenuView":
                press(window, keys().ESCAPE)
        assert name(window) == "MainMenuView", f"{key} leads back"


def test_the_mouse_picks_main_menu_buttons(window: Any) -> None:
    flow = flow_for(window)
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    rect = view.buttons["controls"].rect
    viewport = view.window_viewport()
    x = round(viewport.left + (rect.left + 20.5) * viewport.scale)
    y = round(viewport.bottom + (rect.bottom + 10.5) * viewport.scale)
    view.on_mouse_motion(x, y, 1, 0)
    step(window, 1)
    assert view.selected == "controls"
    click(window, 4, 100)
    assert name(window) == "MainMenuView", "a click beside the buttons does nothing"
    click(window, rect.left + 20, rect.bottom + 10)
    assert name(window) == "ControlsView"


# --- diorama -------------------------------------------------------------------------------


def test_a_diorama_is_drawn_over_what_is_already_there(window: Any) -> None:
    from isofightr.scenes.diorama import Diorama

    window.switch_to()
    island = Diorama(window.pixel_buffer, ["rook", "bramble"])
    magenta = (255, 0, 255, 255)
    with window.pixel_buffer.drawing(magenta):
        island.draw(320, 180)
    shot = frame(window)
    assert shot.getpixel((5, 5)) == magenta, "it does not paint a sky of its own"
    assert shot.getpixel((320, 190))[:3] != magenta[:3], "the island's top is there"
    with window.pixel_buffer.drawing(magenta):
        island.draw(120, 100)
    moved = frame(window)
    assert moved.getpixel((320, 190)) == magenta and moved.getpixel((120, NATIVE_H - 95)) != magenta
    hash_before = island.match.state_hash()
    island.draw(320, 180)
    assert island.match.state_hash() == hash_before, "drawing changes nothing"
    island.tick()
    assert island.match.frame == 1


# --- loading screen ------------------------------------------------------------------------


def to_loading(window: Any, setup: Any = None, **flow_options: Any) -> tuple[Any, Any]:
    flow = flow_for(window, loading=True, **flow_options)
    flow.begin_match(setup or versus())
    assert name(window) == "LoadingView"
    return flow, window.current_view


def test_the_loading_screen_builds_the_match_step_by_step(window: Any) -> None:
    from isofightr.scenes import loading_view

    flow, view = to_loading(window)
    assert view.steps_total == 1 + 2 * 2 + 1 and view.progress == 0.0 and not view.ready
    assert view.battle is None and not view._busts[0].visible
    step(window, 1)
    assert view.steps_done == 0, "the first frame is shown before any work"
    seen = []
    while not view.ready:
        step(window, 1)
        seen.append(view.progress)
        assert view.bar.value == pytest.approx(view.progress)
    assert seen == sorted(seen) and seen[-1] == 1.0 and len(seen) == view.steps_total
    assert view._busts[0].visible and view._busts[1].visible, "the portraits arrive on the way"
    assert view.battle is not None and name(window) == "LoadingView"
    assert view.tick_count < loading_view.MIN_TICKS
    assert view.status.text == "", "ready, but not yet skippable"
    press(window, keys().J)
    assert name(window) == "LoadingView", "it stays at least a second"
    step(window, loading_view.MIN_TICKS)
    assert view.status.text == "READY"
    press(window, keys().J)
    assert name(window) == "BattleView" and window.current_view is view.battle
    assert flow.matches_started == 1


def test_the_loading_screen_goes_on_by_itself(window: Any) -> None:
    from isofightr.scenes import loading_view

    to_loading(window)
    step(window, loading_view.AUTO_TICKS - 1)
    assert name(window) == "LoadingView"
    step(window, 2)
    assert name(window) == "BattleView"


def test_a_loaded_match_is_the_match_a_direct_start_would_be(window: Any) -> None:
    from isofightr.scenes import loading_view

    setup = versus(stage="random", start_damage=30, stocks=2)
    flow, view = to_loading(window, setup)
    step(window, loading_view.AUTO_TICKS - 1)
    window.current_view.on_update(TICK_SECONDS)
    loaded = window.current_view
    assert name(window) == "BattleView" and loaded.match.frame == 0, "shown, not yet played"

    direct_flow = flow_for(window)
    direct_flow.start_battle(setup)
    direct = window.current_view
    assert loaded.stage.id == direct.stage.id, "the same random stage"
    assert loaded.match.state_hash() == direct.match.state_hash(), "the same seed and rules"
    assert loaded.match.rules == direct.match.rules and loaded.setup == direct.setup
    assert loaded.renderer.banks is not direct.renderer.banks
    assert set(loaded.renderer.banks) == {"rook", "mote"}
    assert loaded.renderer.banks["rook"] is view._banks["rook"], "its sprites are handed over"
    assert flow.setup == setup


def test_cards_slide_in_from_the_sides_and_fit_any_player_count(window: Any) -> None:
    from isofightr.scenes import loading_view
    from isofightr.scenes.setup import MatchSetup

    for count in (1, 2, 3, 4):
        rects = loading_view.card_rects(count)
        assert len(rects) == count
        for rect in rects:
            assert rect.left >= 0 and rect.right <= NATIVE_W and rect.top <= NATIVE_H
        for first, second in itertools.pairwise(rects):
            assert first.right < second.left, "side by side"
    assert loading_view.card_rects(2)[1].left - loading_view.card_rects(2)[0].right > 80, "VS"

    four = MatchSetup(
        characters=("rook", "bramble", "zephyr", "mote"),
        devices=("keyboard:solo", "", "", ""),
        cpus=(0, 3, 0, 9),
        team_play=True,
        teams=(0, 1, 1, 0),
    )
    assert [loading_view.player_tag(four, player) for player in range(4)] == [
        "P1", "P2  CPU 3", "P3", "P4  CPU 9",
    ]  # fmt: skip
    assert [loading_view.player_costume(four, player, 6) for player in range(4)] == [1, 2, 2, 1]
    free = versus()
    assert [loading_view.player_costume(free, player, 6) for player in range(2)] == [0, 2]

    _, view = to_loading(window, four)
    step(window, 1)
    group, start = view.cards[0]
    assert start < 0 and view.cards[3][1] > 0, "left cards from the left, right from the right"
    left_now = min(sprite.left for sprite in group._sprites)
    step(window, loading_view.SLIDE_TICKS + 2)
    assert min(sprite.left for sprite in group._sprites) > left_now, "it moved in"
    rect = loading_view.card_rects(4)[0]
    assert min(sprite.left for sprite in group._sprites) == rect.left, "and rests in its place"
    assert view.steps_total == 1 + 2 * 4 + 1


def test_the_menus_start_matches_through_the_loading_screen_only_when_it_is_on(
    window: Any,
) -> None:
    from dataclasses import replace

    flow = flow_for(window)
    flow.show_stage_select(versus())
    step(window, 2)
    press(window, keys().ENTER)
    assert name(window) == "BattleView", "off: straight into the battle (tests, tools)"

    flow = flow_for(window, loading=True)
    flow.show_stage_select(versus())
    step(window, 2)
    press(window, keys().ENTER)
    assert name(window) == "LoadingView"
    assert window.current_view.plan.setup == replace(versus(), stage=window.current_view.stage.id)
    flow.start_battle(versus())
    assert name(window) == "BattleView", "start_battle itself never shows it"


def test_the_tip_changes_while_the_screen_is_up(window: Any) -> None:
    from isofightr.ui.tips import TIP_TICKS

    _, view = to_loading(window)
    step(window, 2)
    first = view.tip.text
    assert first.startswith("TIP: ")
    step(window, TIP_TICKS)
    assert view.tip.text != first and view.tip.text.startswith("TIP: ")
