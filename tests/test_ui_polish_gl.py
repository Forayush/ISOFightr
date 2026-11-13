"""The UI polish pass (decision D-070) on the real screens: nothing sits on anything else,
and a button that overwrites things only turns red under the cursor."""

import itertools
from typing import Any

import pytest

from isofightr.config import TICK_SECONDS

pytestmark = pytest.mark.gl


def keys() -> Any:
    import arcade

    return arcade.key


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


def new_flow(window: Any) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    return GameFlow(window, window.pixel_buffer, seed=1)


def test_the_settings_help_line_clears_the_footer_and_the_last_row(window: Any) -> None:
    from isofightr.ui import theme

    flow = new_flow(window)
    flow.show_settings()
    step(window, 2)
    view = window.current_view
    last = view.rows.rect(len(view.menu.items) - 1)
    assert view.help_rect.bottom >= theme.FOOTER_HEIGHT + 4, "a clear gap above the footer"
    assert last.bottom > view.help_rect.top, "and the list ends above it"


def test_reset_to_defaults_is_quiet_until_the_cursor_is_on_it(window: Any) -> None:
    from isofightr.ui import theme

    flow = new_flow(window)
    flow.show_settings()
    step(window, 2)
    view = window.current_view
    index = [item.key for item in view.menu.items].index("defaults")
    label, strip = view.rows._labels[index], view.rows._strips[index]
    assert label.color == theme.SALMON
    resting = strip.sprite.texture
    while view.menu.selected.key != "defaults":
        press(window, keys().S)
    assert label.color == theme.TEXT, "white on red under the cursor"
    assert strip.sprite.texture is not resting
    press(window, keys().S)
    assert label.color == theme.SALMON and strip.sprite.texture is resting


def test_rows_that_open_a_screen_end_in_an_arrow(window: Any) -> None:
    flow = new_flow(window)
    flow.show_settings()
    step(window, 2)
    rows = window.current_view.rows
    assert set(rows._arrows) == {"sound_test", "controls"}
    for key, arrow in rows._arrows.items():
        index = [item.key for item in rows.menu.items].index(key)
        row = rows.rect(index)
        assert row.left < arrow.rect.left and arrow.rect.right <= row.right
        assert row.bottom <= arrow.rect.bottom and arrow.rect.top <= row.top


def test_default_buttons_rest_in_the_caution_look(window: Any) -> None:
    from isofightr.ui.kit_art import Look

    flow = new_flow(window)
    flow.show_rules()
    step(window, 2)
    rules = window.current_view
    assert rules.buttons["default"].look is Look.CAUTION
    rules.buttons["default"].focus(True)
    assert rules.buttons["default"].look is Look.DANGER
    flow.show_controls()
    step(window, 2)
    assert window.current_view.buttons["default"].look is Look.CAUTION


@pytest.mark.parametrize("tab", [0, 2])
def test_the_controls_side_panel_keeps_its_title_clear_of_its_content(
    window: Any, tab: int
) -> None:
    from isofightr.scenes import controls_view

    flow = new_flow(window)
    flow.show_controls(tab=tab)
    step(window, 2)
    view = window.current_view
    side = controls_view.SIDE
    title_bottom = side.top - 12
    assert side.top <= controls_view.TILES_PANEL.top and side.bottom >= 140
    for cap in view.caps.values():
        rect = cap.rect
        apart = rect.right <= side.left or rect.bottom >= side.top or rect.top <= side.bottom
        assert apart, "the panel does not cover a key cap"
    if view.diagram is not None:
        assert view.diagram.rect.top < title_bottom, "the pad's triggers stay under the title"
        assert view.side_title.text == "CONTROLLER"


def test_the_controls_options_hang_from_the_top_with_the_device_first(window: Any) -> None:
    from isofightr.scenes import controls_view

    flow = new_flow(window)
    for tab in (0, 2):
        flow.show_controls(tab=tab)
        step(window, 2)
        view = window.current_view
        tops = {key: view.rects[key].top for key in view.steppers}
        assert max(tops, key=lambda key: tops[key]) == "device"
        assert tops["device"] == controls_view.INFO.top - 6, "level with the info panel's top"


def test_the_stage_pool_names_are_capitals_like_every_other_list(window: Any) -> None:
    flow = new_flow(window)
    flow.show_random_pool()
    step(window, 2)
    labels = window.current_view._labels
    assert labels and all(label.text == label.text.upper() for label in labels.values())


# --- group 2: the proposals --------------------------------------------------------------


def test_the_rules_are_under_three_titles_that_no_row_covers(window: Any) -> None:
    from isofightr.scenes import rules_view
    from isofightr.ui import theme

    flow = new_flow(window)
    flow.show_rules()
    step(window, 2)
    view = window.current_view
    assert list(view.title_rects) == ["MATCH", "MECHANICS", "DISPLAY"]
    rows = [view.rects[key] for key in rules_view.ROW_KEYS]
    for title in view.title_rects.values():
        assert rules_view.PANEL.bottom < title.bottom and title.top <= rules_view.PANEL.top
        assert not any(row.overlaps(title) for row in rows)
    assert all(a.bottom >= b.top for a, b in itertools.pairwise(rows)), "in order"
    assert rows[-1].bottom >= rules_view.PANEL.bottom + theme.GAP - 1
    assert view.buttons["back"].rect.top < rules_view.PANEL.bottom
    assert rules_view.HELP_BOTTOM >= theme.FOOTER_HEIGHT + 4


def test_the_keyboard_controls_screen_lists_the_fixed_keys(window: Any) -> None:
    from isofightr.scenes import controls_view

    flow = new_flow(window)
    flow.show_controls(tab=0)
    step(window, 2)
    view = window.current_view
    assert [line.split()[0] for line in view.fixed_lines] == ["ENTER", "ESC", "F11"]
    device = view.rects["device"]
    assert controls_view.FIXED.top < device.bottom, "under the device chooser"
    assert controls_view.FIXED.right <= controls_view.INFO.left
    flow.show_controls(tab=2)
    step(window, 2)
    assert window.current_view.fixed_lines == [], "a gamepad's options fill that room"


def test_the_main_menu_shows_facts_from_the_games_own_data(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids
    from isofightr.data.stage_loader import list_stage_ids
    from isofightr.scenes import front

    flow = new_flow(window)
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    facts = {caption: figure for figure, caption in view.preview_facts("versus")}
    assert facts["FIGHTERS"] == str(len(list_character_ids()))
    assert facts["STAGES"] == str(len(list_stage_ids()))
    assert view.preview_facts("rules") == [], "a page that is a list has none"
    assert front.FACT_BOTTOM + front.FACT_SIZE[1] < front.PREVIEW_SPOT[1] - 24, "under the island"
    assert front.ISLAND_PAGES["quit"] in view.islands
