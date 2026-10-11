"""The sound test screen, driven with keys and the mouse (decision D-063, M14 group 2)."""

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


def open_settings(window: Any) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    flow = GameFlow(window, window.pixel_buffer, seed=1)
    flow.show_settings()
    step(window, 2)
    return flow


def test_settings_opens_the_sound_test_and_back_returns(window: Any) -> None:
    open_settings(window)
    view = window.current_view
    assert view.menu.item("sound_test").label == "Sound test"
    while view.menu.selected.key != "sound_test":
        press(window, keys().S)
    assert "song" in view.help_label.text
    press(window, keys().J)
    assert type(window.current_view).__name__ == "SoundTestView"
    assert window.audio.song == "menu", "the menu's music carries on until something is picked"
    press(window, keys().K)
    assert type(window.current_view).__name__ == "SettingsView"
    last = window.current_view.rows.rect(len(window.current_view.menu.items) - 1)
    assert last.bottom > 18 + 22, "the longer list still clears the help line and the footer"


def test_confirm_plays_and_back_stops_then_leaves(window: Any) -> None:
    flow = open_settings(window)
    flow.show_sound_test()
    step(window, 2)
    view = window.current_view
    audio = window.audio
    titles = [track.title for track in view.listed]
    assert "Sound Check" in titles and view.status.text == "UNDER THE CURSOR"
    while view.selected.id != "sound_check":
        press(window, keys().S)
    assert view.title.text == "SOUND CHECK"
    assert [label.text for label in view.facts] == [
        "THE SOUND TEST",
        "100 BPM",
        "G MAJOR",
        "4/4 TIME",
        "0:53",
    ]
    assert view.bar_levels == [0] * len(view.bars)
    press(window, keys().J)
    assert audio.song == "sound_check" and view.playing.id == "sound_check"
    assert audio.backend.played[-1].name == "sound_check" and audio.backend.played[-1].loop
    assert view.status.text == "NOW PLAYING" and max(view.bar_levels) > 0
    press(window, keys().S)
    assert view.title.text == "SOUND CHECK", "what plays stays on show while the cursor moves"
    press(window, keys().K)
    assert audio.song == "" and view.playing is None, "back stops it"
    assert type(window.current_view).__name__ == "SoundTestView" and max(view.bar_levels) == 0
    press(window, keys().K)
    assert type(window.current_view).__name__ == "SettingsView", "back again leaves"
    assert audio.song == "menu", "and the menu's music is back"


def test_the_sounds_list_scrolls_and_plays_over_the_music(window: Any) -> None:
    from isofightr.scenes import sound_test_model as model

    flow = open_settings(window)
    flow.show_sound_test()
    step(window, 2)
    view = window.current_view
    audio = window.audio
    press(window, keys().D)
    assert view.tab == model.SOUNDS and view.tabs[model.SOUNDS].active
    assert len(view.listed) > model.VISIBLE_ROWS
    first_name = view._names[0].text
    for _ in range(model.VISIBLE_ROWS + 3):
        press(window, keys().S)
    assert view.firsts[model.SOUNDS] == 4 and view._names[0].text != first_name
    assert view.count_label.text == f"{model.VISIBLE_ROWS + 4} / {len(view.listed)}"
    chosen = view.selected.id
    before = len(audio.backend.played)
    press(window, keys().J)
    assert chosen in [played.name for played in audio.backend.played[before:]]
    assert audio.song == "menu" and view.playing is None, "a sound effect does not stop the music"
    press(window, keys().W)
    press(window, keys().A)
    assert view.tab == model.MUSIC and view.cursors[model.SOUNDS] == model.VISIBLE_ROWS + 2
    press(window, keys().W)
    assert view.cursors[model.MUSIC] == len(view.listed) - 1, "up from the top goes to the end"
    victory = next(index for index, track in enumerate(view.listed) if track.id == "victory")
    view.cursors[model.MUSIC] = victory
    press(window, keys().J)
    assert audio.backend.played[-1].name == "victory" and not audio.backend.played[-1].loop
    press(window, keys().K)


def test_the_mouse_picks_rows_and_tabs(window: Any) -> None:
    from isofightr.scenes import sound_test_model as model

    flow = open_settings(window)
    flow.show_sound_test()
    step(window, 2)
    view = window.current_view
    third = view.row_rects[2]
    assert view.hover(third.left + 10, third.bottom + 5) and view.cursors[model.MUSIC] == 2
    tab = view.tabs[model.SOUNDS].rect
    assert not view.hover(tab.left + 10, tab.bottom + 5), "a tab changes list and plays nothing"
    assert view.tab == model.SOUNDS
    assert not view.hover(5, 5)
    empty = model.VISIBLE_ROWS - 1
    view.tab = model.MUSIC
    step(window, 1)
    rect = view.row_rects[empty]
    assert not view.hover(rect.left + 10, rect.bottom + 5), "no row there in the short list"
