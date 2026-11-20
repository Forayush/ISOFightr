"""Menu fixes from the user's play (decision D-078), on the real screens and with the
user's own arrows layout (S strong, Z and Left Ctrl the modifiers, X attack, C special, V
grab), where the bugs showed."""

from dataclasses import replace
from typing import Any

import pytest

from isofightr.config import TICK_SECONDS

pytestmark = pytest.mark.gl

ARROWS = "keyboard:arrows"
USER_ARROWS = {
    "move_up": "UP",
    "move_down": "DOWN",
    "move_left": "LEFT",
    "move_right": "RIGHT",
    "up": "Z",
    "down": "LCTRL",
    "attack": "X",
    "special": "C",
    "strong": "S",
    "grab": "V",
    "jump": "LSHIFT",
    "shield": "SPACE",
    "walk": "",
    "taunt": "NUM_9",
}


def keys() -> Any:
    import arcade

    return arcade.key


def user_settings() -> Any:
    from isofightr.settings import from_data

    loaded = from_data({"keyboard": {"arrows": dict(USER_ARROWS)}})
    return replace(loaded, slot_devices=(ARROWS, "", "", ""))


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


def new_flow(window: Any, settings: Any = None) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    options = {} if settings is None else {"settings": settings}
    return GameFlow(window, window.pixel_buffer, seed=1, **options)


def tab_of(window: Any) -> str:
    return str(getattr(window.current_view, "option_tab", ""))


def test_tab_reaches_every_options_page_and_wraps_round(window: Any) -> None:
    from isofightr.scenes.options_view import OPTION_TABS

    flow = new_flow(window, user_settings())
    flow.show_options("rules")
    step(window, 3)
    seen = [tab_of(window)]
    for _ in OPTION_TABS:
        press(window, keys().TAB)
        seen.append(tab_of(window))
    assert seen == [*OPTION_TABS, OPTION_TABS[0]], "the controls page used to stop it"


def test_a_pads_select_reaches_every_options_page(window: Any) -> None:
    from isofightr.scenes.options_view import OPTION_TABS
    from isofightr.ui.menu import MenuAction

    flow = new_flow(window)
    flow.show_options("rules")
    step(window, 3)
    for name in (*OPTION_TABS[1:], OPTION_TABS[0]):
        window.current_view.act("pad:0", MenuAction.NEXT_TAB)
        step(window, 2)
        assert tab_of(window) == name


@pytest.mark.parametrize("key", ["S", "Z", "LCTRL"])
def test_bound_buttons_no_longer_change_tab(window: Any, key: str) -> None:
    flow = new_flow(window, user_settings())
    for page in ("rules", "display"):
        flow.show_options(page)
        step(window, 3)
        press(window, getattr(keys(), key))
        assert tab_of(window) == page


def test_a_key_both_layouts_bind_moves_the_cursor_without_swinging(window: Any) -> None:
    """On the user's arrows layout S is strong; on WASD it is down. Testing the arrows
    layout, S moved the cursor down and the live fighter did a strong attack at every step."""
    from isofightr.sim.fighter import StateId

    flow = new_flow(window, user_settings())
    flow.show_options("controls")
    step(window, 3)
    view = window.current_view
    assert view.device == ARROWS
    fighter = view.live_fighter.match.fighters[0]
    before = view.cursor
    view.on_key_press(keys().S, 0)
    step(window, 6)
    assert view.cursor != before, "S still moves the cursor"
    assert fighter.state is not StateId.ATTACK, "and the fighter stays put"
    assert ("strong", 0) in view.caps and view.caps[("strong", 0)]._state[1].name == "LIT"
    view.on_key_release(keys().S, 0)
    step(window, 40)
    view.on_key_press(keys().X, 0)
    step(window, 3)
    assert fighter.state is StateId.ATTACK, "a key of its own still acts"
    view.on_key_release(keys().X, 0)


def open_select(window: Any) -> tuple[Any, Any]:
    flow = new_flow(window, user_settings())
    flow.show_character_select(flow.setup)
    step(window, 3)
    css = window.current_view
    for key in (keys().X, keys().V, keys().X, keys().X):  # join, step on, add a CPU, home
        press(window, key)
    assert css.slots[1].cpu and not css.focus
    return flow, css


def test_a_cpus_plate_says_how_to_get_back_to_it(window: Any) -> None:
    _, css = open_select(window)
    assert css.panels[1].line2.text == "V: change it", "it only said CPU"
    press(window, keys().V)
    assert css.focus == {ARROWS: 1}
    press(window, keys().RIGHT)
    assert css.character_of(css.slots[1]) != "mote" or css.slots[1].cpu


def test_a_click_on_a_cpus_plate_steps_onto_it(window: Any) -> None:
    _, css = open_select(window)
    rect = css.panels[1].rect
    css.click(rect.left + rect.width // 2, rect.bottom + 4)
    assert css.focus == {ARROWS: 1}


def test_back_from_a_keyboard_that_is_not_in_says_who_can_go_back(window: Any) -> None:
    _, css = open_select(window)
    press(window, keys().K)
    assert type(window.current_view).__name__ == "CharacterSelectView"
    assert "P1: C" in css.message, "it did nothing, under a footer promising K: back"
    css.message = ""
    step(window, 200)
    assert "back" not in css._footer.text.lower()
    assert "J: join" in css._footer.text


def test_the_rules_chip_shows_every_rule_with_a_time_limit_on(window: Any) -> None:
    from isofightr.scenes.select_view import CHIP

    flow = new_flow(window, user_settings())
    flow.show_character_select(replace(flow.setup, time_on=True, minutes=12, start_damage=150))
    step(window, 3)
    label = window.current_view.chip.label
    assert label.shown == label.text, label.text
    assert CHIP.left <= label.left and label.left + label.width <= CHIP.right


def test_text_in_a_box_is_shortened_instead_of_running_out(window: Any) -> None:
    from isofightr.ui.focus import Rect
    from isofightr.ui.pixel_text import GlyphAtlas
    from isofightr.ui.widgets import Button, UiLayer

    window.switch_to()
    layer = UiLayer(GlyphAtlas())
    button = Button(layer, Rect(10, 10, 120, 22), "A CAPTION FAR TOO LONG FOR IT", "gear")
    label = button.label
    assert label.text == "A CAPTION FAR TOO LONG FOR IT", "the text is kept"
    assert label.shown.endswith("..") and label.width <= label.max_width
    label.text = "OK"
    assert label.shown == "OK"


def test_the_pad_layout_fits_between_its_stepper_arrows(window: Any) -> None:
    flow = new_flow(window)
    flow.show_options("controls")
    step(window, 2)
    view = window.current_view
    view.reopen(2, "")
    step(window, 2)
    label = window.current_view.steppers["layout"].label
    assert label.text == "Right-stick modifiers" and label.shown == label.text
