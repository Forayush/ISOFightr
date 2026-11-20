"""The boot splash, title, main menu and loading screen on a real window (``pytest -m gl``).

Plan note "13 - Game Modes UI and Flow", decision D-061 (M13 group 3).
"""

import itertools
from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS
from ui_helpers import MAX_COVER, ui_cover

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
    from isofightr.ui import logo, wipe

    flow = flow_for(window)
    flow.show_boot()
    assert name(window) == "BootView" and NoControllers.opened == 0, "nothing slow yet"
    window.current_view.on_draw()
    splash = frame(window)
    colours = {colour[:3] for _, colour in splash.getcolors(maxcolors=100000)}
    assert {logo.FACE, logo.SIDE} <= colours, "the logo is on screen at once"
    step(window, 1)
    assert name(window) == "BootView", "it is drawn before anything else happens"
    step(window, 2)
    assert name(window) == "TitleView" and NoControllers.opened == 1
    title = window.current_view
    assert title.wiping, "the title opens through the cloud, over the splash"
    assert not flow.world().gliding, "and the camera is already at its gate"
    step(window, wipe.WIPE_TICKS)
    assert not title.wiping


def test_the_title_drops_its_logo_in_over_the_isle(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids
    from isofightr.scenes import front
    from isofightr.scenes.menu_world_model import STATIONS, STROLL_BOUNDS

    flow = flow_for(window)
    flow.show_title()
    view = window.current_view
    world = flow.world()
    assert view.world is world and world.station is STATIONS["gate"]
    step(window, 1)
    high = view.logo.center_y
    assert high > front.LOGO_BOTTOM + view.logo.texture.height, "it starts above its place"
    step(window, front.LOGO_DROP_TICKS + 2)
    rest = view.logo.center_y - view.logo.height / 2
    assert abs(rest - front.LOGO_BOTTOM) <= 2, "and comes to rest"
    assert float(view.logo.center_x - view.logo.width / 2).is_integer()

    fighters = world.match.fighters
    assert [fighter.character.id for fighter in fighters] == list_character_ids()[:4]
    assert world.strollers_shown, "the roster strolls on the plaza"
    before = world.match.frame
    step(window, 10)
    assert world.match.frame == before + 10, "the island lives while the title is up"
    assert all(STROLL_BOUNDS.holds(f.pos.x, f.pos.y) for f in fighters)

    shot = frame(window)
    colours = shot.getcolors(maxcolors=200000)
    assert colours is not None and len(colours) > 60, "sky, island, sprites and logo"
    assert ui_cover(window, view) <= MAX_COVER, "the world is the screen"


def test_the_title_prompt_names_the_control_and_any_confirm_starts(window: Any) -> None:
    from isofightr.scenes import front
    from isofightr.ui.kit_art import Look

    flow = flow_for(window)
    flow.settings = flow.settings.with_key("solo", "attack", "F")
    flow.show_title()
    step(window, 2)
    view = window.current_view
    assert view.prompt_text() == "PRESS F OR ENTER"
    assert view.prompt.label.text == "PRESS F OR ENTER", "on the one button of the screen"
    assert view.prompt.look is Look.FOCUS and not view.prompt.pressed
    step(window, front.PROMPT_PRESS_TICKS - 2)
    assert view.prompt.pressed, "it presses itself now and then: it is a thing to press"
    step(window, 6)
    assert not view.prompt.pressed
    press(window, keys().F)
    assert name(window) == "MainMenuView"
    press(window, keys().K)
    assert name(window) == "TitleView", "special goes back to the title"
    click(window, 300, 200)
    assert name(window) == "MainMenuView", "a click anywhere starts too"


# --- main menu -----------------------------------------------------------------------------


def test_the_main_menu_is_five_blocks_beside_the_isle(window: Any) -> None:
    from isofightr.scenes import front
    from isofightr.scenes.menu_world_model import STATIONS
    from isofightr.ui import theme

    flow = flow_for(window)
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    entries = [key for key, _, _, _ in front.MENU_ENTRIES]
    assert entries == ["versus", "training", "fighters", "options", "quit"], "D-072, D-077"
    assert [item.key for item in view.menu.items] == entries == list(view.buttons)
    assert view.title == "MAIN MENU" and view.world.station is STATIONS["plaza"]
    rects = [button.rect for button in view.buttons.values()]
    for upper, lower in itertools.pairwise(rects):
        assert lower.top + theme.RAISE <= upper.bottom, "room for the cursor's block to rise"
    assert rects[-1].bottom > front.NOTE.top > theme.FOOTER_HEIGHT
    assert all(rect.right <= NATIVE_W // 2 for rect in rects), "the island has the rest"

    notes, leans = set(), set()
    for key in entries:
        assert view.selected == key
        assert view.buttons[key].button.lift == theme.RAISE, "the cursor's block stands up"
        assert sum(button.button.lift > 0 for button in view.buttons.values()) == 1
        notes.add(view.note.text)
        leans.add(view.world._nudge_goal)
        press(window, keys().S)
    assert view.selected == "versus", "the cursor wraps"
    assert len(notes) == len(entries), "the sign says a line about each entry"
    assert len(leans) >= 3, "and the camera leans toward what the cursor is on"
    assert "Stock 3" in view.note_line("versus") and "Keyboard (WASD)" in view.note_line("options")
    assert ui_cover(window, view) <= MAX_COVER


def test_the_main_menu_goes_where_its_buttons_say(window: Any) -> None:
    flow = flow_for(window)
    where = {
        "versus": "CharacterSelectView",
        "training": "CharacterSelectView",
        "fighters": "FightersView",
        "options": "RulesView",
    }
    for key, scene in where.items():
        flow.show_main_menu()
        step(window, 2)
        view = window.current_view
        for _ in range(len(view.buttons)):
            if view.selected != key:
                press(window, keys().S)
        assert view.selected == key
        press(window, keys().J)
        assert name(window) == scene, key
        if key == "training":
            assert window.current_view.setup.training
        for _ in range(3):  # character select first lets the player leave their slot
            if name(window) != "MainMenuView":
                press(window, keys().ESCAPE)
        assert name(window) == "MainMenuView", f"{key} leads back"
        assert flow.world()._nudge_goal == (0, 0) or name(window) == "MainMenuView"


def test_the_isle_sounds_a_press_a_glide_and_the_cloud(window: Any) -> None:
    """D-072 group 8: a block button thocks when pressed, the camera whooshes when it sets
    off for another station, and the cloud has a sound of its own (and no glide under it)."""
    from isofightr.audio.cues import UI_GLIDE, UI_PRESS, UI_WIPE

    flow = flow_for(window)
    flow.show_main_menu()
    flow.world().settle("plaza")
    step(window, 2)
    played = window.audio.backend.played
    played.clear()
    view = window.current_view
    for _ in range(len(view.buttons)):
        if view.selected != "versus":
            press(window, keys().S)
    press(window, keys().J)
    names = [sound.name for sound in played]
    assert UI_PRESS in names and UI_GLIDE in names, names
    assert name(window) == "CharacterSelectView"
    played.clear()
    css = window.current_view
    flow.show_stage_select(css.current_setup())
    step(window, 2)
    names = [sound.name for sound in played]
    assert UI_WIPE in names and UI_GLIDE not in names, names


def test_options_are_tabs_reached_by_the_tab_key_and_a_click(window: Any) -> None:
    from isofightr.scenes import options_view
    from isofightr.scenes.menu_world_model import STATIONS

    flow = flow_for(window)
    flow.show_options()
    step(window, 2)
    view = window.current_view
    assert name(window) == "RulesView" and view.in_options, "Options opens on its first tab"
    assert view.world.station is STATIONS["workshop"] and view.title == "OPTIONS"
    assert options_view.OPTION_TABS == ("rules", "controls", "display", "sound", "feel")
    assert view.option_tabs.active == 0
    seen = []
    for _ in range(len(options_view.OPTION_TABS) - 1):
        if name(window) == "ControlsView":
            break
        press(window, keys().TAB)
        seen.append((name(window), window.current_view.option_tab))
    assert seen == [("ControlsView", "controls")]
    # Strong is a key to test on Controls, and no longer changes tab anywhere (D-078); up
    # from the player tabs still reaches the options' tabs, and right opens the next one.
    controls = window.current_view
    press(window, keys().U)
    assert name(window) == "ControlsView", "strong does not leave Controls"
    controls.cursor = "tab:0"
    press(window, keys().W)
    assert controls.cursor == "options-tabs" and controls.option_tabs.focused
    press(window, keys().D)
    pages = []
    for _ in range(3):
        view = window.current_view
        pages.append((name(window), view.option_tab))
        press(window, keys().TAB)
    assert pages == [
        ("SettingsView", "display"),
        ("SettingsView", "sound"),
        ("SettingsView", "feel"),
    ]
    assert name(window) == "RulesView", "and round to the first"
    press(window, keys().COMMA)
    assert window.current_view.option_tab == "rules", "the down modifier no longer changes tab"
    press(window, keys().U)
    assert window.current_view.option_tab == "rules", "nor does strong"
    rect = options_view.tab_rect(window.current_view, "sound")
    click(window, rect.left + 5, rect.bottom + 5)
    assert window.current_view.option_tab == "sound", "a click opens a tab"
    for tab in options_view.SETTINGS_TABS:
        flow.show_settings(tab)
        step(window, 2)
        items = [item.key for item in window.current_view.menu.items]
        assert len(items) <= 6, "at most six rows a page"
    press(window, keys().ESCAPE)
    assert name(window) == "MainMenuView", "back leaves the options"


def test_the_mouse_picks_main_menu_buttons(window: Any) -> None:
    flow = flow_for(window)
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    rect = view.buttons["options"].rect
    viewport = view.window_viewport()
    x = round(viewport.left + (rect.left + 20.5) * viewport.scale)
    y = round(viewport.bottom + (rect.bottom + 10.5) * viewport.scale)
    view.on_mouse_motion(x, y, 1, 0)
    step(window, 1)
    assert view.selected == "options"
    click(window, 4, 60)
    assert name(window) == "MainMenuView", "a click beside the buttons does nothing"
    click(window, rect.left + 20, rect.bottom + 10)
    assert name(window) == "RulesView", "Options opens on its first tab"


def test_the_world_carries_on_from_screen_to_screen(window: Any) -> None:
    from isofightr.scenes.menu_world_model import GLIDE_TICKS, STATIONS, rest_pose

    flow = flow_for(window)
    flow.show_title()
    step(window, 5)
    world = flow.world()
    lived = world.ticks
    assert lived == 5 and flow.menu_ticks == 5
    flow.show_main_menu()
    assert window.current_view.world is world, "one Isle for every menu"
    assert world.station is STATIONS["plaza"] and world.gliding, "the camera glides there"
    step(window, 3)
    assert world.ticks == lived + 3 and flow.menu_ticks == 8, "and time does not start again"
    step(window, GLIDE_TICKS)
    assert not world.gliding
    flow.show_options()
    step(window, GLIDE_TICKS + 1)
    assert world.pose == rest_pose(STATIONS["workshop"]), "the lean is gone with the menu"
    shot = frame(window)
    colours = shot.getcolors(maxcolors=200000)
    assert colours is not None and len(colours) > 40, "the Isle is behind every menu"


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


# --- hero art (M13 group 4) ----------------------------------------------------------------


def test_the_sprite_bank_serves_hero_art_in_every_costume(window: Any) -> None:
    import json

    from isofightr.data.sprite_sheet import UI_PICTURES, load_sprite_set
    from isofightr.render.sprite_bank import SpriteBank

    window.switch_to()
    sprite_set = load_sprite_set("bramble")
    assert sprite_set is not None
    bank = SpriteBank(sprite_set)
    index = json.loads((sprite_set.folder.parent / "ui" / "ui.json").read_text(encoding="utf-8"))
    for name in UI_PICTURES:
        texture = bank.portrait(name, 0)
        assert texture is not None and [texture.width, texture.height] == index["sizes"][name]
        assert bank.portrait(name, 0) is texture, "made once"
    heroes = [bank.portrait("hero", costume) for costume in range(len(sprite_set.costumes))]
    pictures = {texture.image.tobytes() for texture in heroes if texture is not None}
    assert len(pictures) == len(sprite_set.costumes), "each costume recolours it"
    assert bank.portrait("bust", 0) is not None, "the small portraits are still there"


def test_loading_cards_show_hero_art_standing_on_the_name_plate(window: Any) -> None:
    from isofightr.scenes import loading_view
    from isofightr.scenes.setup import MatchSetup

    setup = MatchSetup(
        characters=("rook", "bramble", "zephyr", "mote"),
        devices=("keyboard:solo", "", "", ""),
        cpus=(0, 5, 5, 5),
    )
    _, view = to_loading(window, setup)
    while not view.ready:
        step(window, 1)
    step(window, loading_view.SLIDE_TICKS + 2)
    rects = loading_view.card_rects(4)
    for player, rect in enumerate(rects):
        art = view._busts[player]
        bank = view._banks[setup.characters[player]]
        costume = loading_view.player_costume(setup, player, len(bank.sprite_set.costumes))
        assert art.visible and art.texture is bank.portrait("hero", costume)
        assert art.scale == (1.0, 1.0), "one art pixel per screen pixel"
        left = art.center_x - art.texture.width / 2
        bottom = art.center_y - art.texture.height / 2
        assert bottom == rect.bottom + loading_view.ART_BOTTOM, "feet behind the plate"
        assert rect.left <= left and left + art.texture.width <= rect.right, "inside its card"
        assert bottom + art.texture.height <= rect.top - 17, "under the card's coloured strip"
        assert float(left).is_integer() and float(bottom).is_integer(), "on whole pixels"


def test_the_loading_screen_records_what_a_cpu_must_know(window: Any) -> None:
    """Decision D-071: a CPU learns every fighter's moves by performing them in a private
    sim. That takes about 0.1 s a character, so it is done here and not on the first tick."""
    from isofightr.ai import knowledge

    knowledge._CACHE.clear()
    _flow, view = to_loading(window)
    while not view.ready:
        step(window, 1)
    assert knowledge._CACHE == {}, "nobody to think for: nothing recorded"
    _flow, view = to_loading(window, versus(cpus=(0, 5)))
    while not view.ready:
        step(window, 1)
    assert view.battle is not None
    fighters = view.battle.match.fighters
    assert set(knowledge._CACHE) == {fighter.character.id for fighter in fighters}
    for fighter in fighters:
        cached = knowledge._CACHE[fighter.character.id][1]
        assert knowledge.knowledge_for(fighter.character) is cached


def test_the_vs_screen_shows_the_stage_and_goes_into_the_match_through_the_cloud(
    window: Any,
) -> None:
    from isofightr.scenes import loading_view

    _, view = to_loading(window)
    assert view.scenery is not None and view.tip is view.tip_sign.label
    for _ in range(loading_view.AUTO_TICKS + 5):
        if name(window) != "LoadingView":
            break
        step(window, 1)
    battle = window.current_view
    assert name(window) == "BattleView" and battle.wiping, "into the match through the cloud"
    assert battle.match.frame <= 5, "the match starts as it shows"
