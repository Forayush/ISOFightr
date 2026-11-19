"""The Fighters screen on a real window (``pytest -m gl``): every character's card under
its fighter at the ring (decision D-077).

The cards' content, layout and colours are tested without a window in
``tests/test_fighter_cards.py``.
"""

from typing import Any

import pytest

from isofightr.config import TICK_SECONDS
from ui_helpers import ui_cover

pytestmark = pytest.mark.gl

MAX_FIGHTERS_COVER = 0.5
"""The most of the screen the cards may cover: a sheet to read, so more than the 0.35 of the
screens that show the world (decision D-077); the fighters stand clear above them."""
SETTLED = 70
"""Ticks after which every fighter has dropped in and every card has risen into place."""


class NoControllers:
    """Stands in for pyglet's ``ControllerManager``: nothing is plugged in."""

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

    monkeypatch.setattr(pyglet.input, "ControllerManager", NoControllers)


def keys() -> Any:
    import arcade

    return arcade.key


def flow_for(window: Any) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    return GameFlow(window, window.pixel_buffer, seed=1)


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


def mouse_at(view: Any, x: float, y: float) -> tuple[int, int]:
    viewport = view.window_viewport()
    ratio = view.window.get_pixel_ratio()
    return (
        round((viewport.left + (x + 0.5) * viewport.scale) / ratio),
        round((viewport.bottom + (y + 0.5) * viewport.scale) / ratio),
    )


def open_fighters(window: Any) -> Any:
    """Walk from the main menu to the Fighters screen, then let it settle."""
    flow = flow_for(window)
    flow.show_main_menu()
    step(window, 2)
    menu = window.current_view
    for _ in range(len(menu.buttons)):
        if menu.selected != "fighters":
            press(window, keys().S)
    assert menu.selected == "fighters"
    assert "fighters" in menu.note.text and "archetypes" in menu.note.text
    press(window, keys().J)
    step(window, SETTLED)
    return window.current_view


def test_fighters_opens_from_the_main_menu_with_everyone_on_the_ring(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids
    from isofightr.render.placeholder_art import NO_PLAYER
    from isofightr.scenes.menu_world_model import STATIONS

    view = open_fighters(window)
    assert type(view).__name__ == "FightersView"
    assert view.title == "FIGHTERS" and view.world.station is STATIONS["gallery"]
    ids = list_character_ids()
    assert [card.id for card in view.cards] == ids, "the roster's order"
    world = view.world
    for slot, card in enumerate(view.cards):
        stand_in = world.ring[slot]
        assert stand_in is not None and stand_in.character == card.id
        assert stand_in.color_index == NO_PLAYER, "nobody's player: no coloured ring"
        assert stand_in.pose(world.ticks).lift == 0, "down from the drop"
        assert world.pads[slot] == card.colours.ramp, "the spot is in the archetype's colour"
    assert view.focus == 0 and view.widgets[0].focused
    assert [widget.group._offset for widget in view.widgets] == [(0, 2), (0, 0), (0, 0), (0, 0)]
    assert ui_cover(window, view) <= MAX_FIGHTERS_COVER


def test_the_cursor_browses_cheers_and_changes_costume(window: Any) -> None:
    from isofightr.scenes.menu_world_model import Mood

    view = open_fighters(window)
    world = view.world
    press(window, keys().D)
    assert view.focus == 1 and view.widgets[1].group._offset == (0, 2)
    assert world.ring[1].mood is Mood.READY, "the fighter the cursor reaches taunts"
    press(window, keys().J)
    assert world.ring[1].mood is Mood.WIN, "attack: it cheers"
    press(window, keys().D)
    assert world.ring[1].mood is Mood.IDLE and world.ring[2].mood is Mood.READY
    press(window, keys().A)
    press(window, keys().A)
    press(window, keys().A)
    assert view.focus == len(view.cards) - 1, "left wraps round"
    slot = view.focus
    before = world.ring[slot].costume
    press(window, keys().U)
    assert world.ring[slot].costume == view.costumes[slot] == (before + 1) % 6
    assert view.widgets[slot].shown_costume == view.costumes[slot], "its chip is ringed"
    assert world.ring[slot].mood is not Mood.DROP_IN, "the same fighter: no drop"
    press(window, keys().ESCAPE)
    assert type(window.current_view).__name__ == "MainMenuView"
    assert world.ring == [None] * 4 and world.pads == [None] * 4, "the ring is cleared"


def test_the_mouse_puts_the_cursor_on_a_card_and_a_click_cheers(window: Any) -> None:
    import arcade

    from isofightr.scenes.menu_world_model import Mood

    view = open_fighters(window)
    rect = view.widgets[3].rect
    view.on_mouse_motion(*mouse_at(view, rect.left + 30, rect.bottom + 40), 1, 0)
    step(window, 1)
    assert view.focus == 3
    view.on_mouse_press(
        *mouse_at(view, rect.left + 30, rect.bottom + 40), arcade.MOUSE_BUTTON_LEFT, 0
    )
    step(window, 2)
    assert view.world.ring[3].mood is Mood.WIN
    view.on_mouse_press(*mouse_at(view, 4, 300), arcade.MOUSE_BUTTON_RIGHT, 0)
    step(window, 2)
    assert type(window.current_view).__name__ == "MainMenuView"


def test_more_fighters_than_spots_turn_the_page(
    window: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fifth character goes on a second page: stepping past the fourth card opens it, and
    stepping on from the last card comes back to the first."""
    from isofightr.scenes import fighters_view

    roster = ["bramble", "mote", "rook", "zephyr", "rook"]
    monkeypatch.setattr(fighters_view, "list_character_ids", lambda: roster)
    view = open_fighters(window)
    assert view.shown == [0, 1, 2, 3] and view.page_label is not None
    assert view.page_label.text == "Page 1 of 2"
    for _ in range(4):
        press(window, keys().D)
    view = window.current_view
    assert view.focus == 4 and view.shown == [4] and view.page == 1
    step(window, SETTLED)
    assert view.world.ring[0] is not None and view.world.ring[1] is None
    press(window, keys().D)
    view = window.current_view
    assert view.focus == 0 and view.page == 0
