"""The block kit's widgets and the cloud wipe on a real window (``pytest -m gl``): decision
D-072, M21 group 1.
"""

import itertools
from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS

pytestmark = pytest.mark.gl


def layer_on(window: Any, surface: Any = None) -> Any:
    from isofightr.ui import theme
    from isofightr.ui.pixel_text import GlyphAtlas
    from isofightr.ui.widgets import UiLayer

    window.switch_to()
    return UiLayer(GlyphAtlas(), surface or theme.STONE)


def test_a_layer_writes_in_its_surfaces_colours(window: Any) -> None:
    from isofightr.ui import theme

    stone = layer_on(window, theme.STONE)
    label = stone.write("Join with any keyboard.", 10, 10)
    assert label.color == theme.STONE.text and not stone.shadows, "ink on stone, no shadow"
    ink = layer_on(window, theme.INKED)
    light = ink.write("Paused", 10, 10)
    assert light.color == theme.INKED.text and len(ink.shadows) == len(ink.text)
    gold = stone.write("x", 10, 30, color=theme.GOLD, shadow=True)
    assert gold.color == theme.GOLD and stone.shadows, "a caller may still say"


def test_a_button_rises_under_the_cursor_and_sinks_when_pressed(window: Any) -> None:
    from isofightr.ui import theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.font import TextSize
    from isofightr.ui.kit_art import Look
    from isofightr.ui.widgets import PRESS_TICKS, Button

    layer = layer_on(window)
    rect = Rect(20, 40, 90, 22)
    button = Button(layer, rect, "VERSUS", "stock", TextSize.TITLE)
    body = layer.panels[0]

    def span() -> tuple[float, float]:
        """Where the body is drawn, bottom to top (its hit box keeps its first size)."""
        return (body.center_y - body.height / 2, body.center_y + body.height / 2)

    assert body.center_x - body.width / 2 == 20 and body.width == 90
    assert span() == (40, 62), "at rest it fills its rect"
    assert button.lift == 0 and button.face == Rect(20, 40 + theme.LIP, 90, 22 - theme.LIP)
    rest_text = button.label.bottom
    assert button.label.color == theme.STONE.text

    button.focus(True)
    assert button.look is Look.FOCUS and button.lift == theme.RAISE
    assert span() == (40, 62 + theme.RAISE), "it grows upward only"
    assert button.label.bottom == rest_text + theme.RAISE, "the caption rides the face"
    assert button.label.color == theme.INK

    button.press(tick=10)
    assert button.pressed and button.lift < 0
    assert span() == (40, 62) and button.label.bottom < rest_text
    button.settle(10 + PRESS_TICKS - 1)
    assert button.pressed, "it stays down for a few ticks"
    button.settle(10 + PRESS_TICKS)
    assert not button.pressed and button.lift == theme.RAISE, "then comes back up"
    button.focus(False)
    assert button.lift == 0 and button.label.bottom == rest_text

    quiet = Button(layer, Rect(120, 40, 90, 22), "DEFAULT", look=Look.CAUTION)
    assert quiet.lift == 0 and quiet.label.color == theme.STONE.warning
    quiet.focus(True)
    assert quiet.look is Look.DANGER and quiet.lift == theme.RAISE
    quiet.focus(False)
    assert quiet.look is Look.CAUTION


def test_a_block_switch_moves_its_word_with_its_face(window: Any) -> None:
    from isofightr.ui import theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.widgets import Toggle

    layer = layer_on(window)
    switch = Toggle(layer, Rect(10, 10, 40, 17), block=True)
    low = switch.label.bottom
    assert switch.label.text == "OFF" and switch.label.color == theme.INK
    switch.set(True)
    assert switch.on and switch.label.text == "ON" and switch.label.bottom > low
    flat = Toggle(layer, Rect(60, 10, 40, 16))
    flat.set(True)
    assert flat.on, "the flat switch of the screens not yet rebuilt still works"


def test_a_prompt_bar_shows_a_cap_and_a_word_for_each_control(window: Any) -> None:
    from isofightr.ui import theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.widgets import PromptBar

    layer = layer_on(window)
    strip = Rect(0, 0, NATIVE_W, theme.FOOTER_HEIGHT)
    bar = PromptBar(layer, strip)
    line = "WASD: move   J: pick   K: back   mouse: click"
    bar.set(line)
    assert bar.text == line and bar.shown[1] == ("J", "pick")
    caps = [cap for cap in bar._caps if cap.visible]
    assert len(caps) == 4
    assert all(cap.height == theme.PROMPT_HEIGHT for cap in caps)
    assert all(strip.bottom <= cap.bottom and cap.top <= strip.top for cap in caps)
    assert [label.text for label in bar._cap_labels] == ["WASD", "J", "K", "mouse"]
    assert [word.text for word in bar._words] == ["move", "pick", "back", "click"]
    assert strip.left + theme.PAD <= bar.left and bar.right <= strip.right - theme.PAD
    middle = (bar.left + bar.right) / 2
    assert abs(middle - NATIVE_W / 2) <= 1, "centred"
    for cap, label in zip(caps, bar._cap_labels, strict=False):
        assert cap.left < label.left and label.left + label.width < cap.right, "name on cap"
    lefts = [cap.left for cap in caps]
    assert lefts == sorted(lefts)

    count = len(layer.panels)
    bar.set("J: pick")
    assert sum(1 for cap in bar._caps if cap.visible) == 1, "caps not needed are hidden"
    assert [word.text for word in bar._words if word.text] == ["pick"]
    bar.set(line)
    assert len(layer.panels) == count, "and reused"

    bar.set("P2 JOINED ON PAD 1", color=theme.STONE.accent)
    assert not any(cap.visible for cap in bar._caps), "a message has no caps"
    assert bar._words[0].text == "P2 JOINED ON PAD 1"
    assert bar._words[0].color == theme.STONE.accent


def test_a_prompt_bar_draws_gamepad_face_buttons_as_discs(window: Any) -> None:
    from isofightr.ui import kit_art, theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.widgets import PromptBar

    layer = layer_on(window)
    bar = PromptBar(layer, Rect(0, 0, NATIVE_W, theme.FOOTER_HEIGHT))
    bar.set("stick: move   A: pick   B: back", pad=True)
    caps = [cap for cap in bar._caps if cap.visible]
    assert [round(cap.width) for cap in caps][1:] == [kit_art.PAD_BUTTON] * 2, "discs"
    assert caps[0].width > kit_art.PAD_BUTTON, "the stick is a plain cap with its name"
    bar.set("stick: move   A: pick   B: back", pad=False)
    assert all(cap.height == theme.PROMPT_HEIGHT for cap in bar._caps if cap.visible)


def test_a_long_hint_squeezes_its_gaps_before_it_runs_off(window: Any) -> None:
    from isofightr.ui import theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.widgets import PromptBar

    layer = layer_on(window)
    strip = Rect(0, 0, 330, theme.FOOTER_HEIGHT)
    bar = PromptBar(layer, strip)
    bar.set("WASD: fighter   U: costume   L: CPUs   up: rules   K: back")
    assert bar.left >= strip.left and bar.right <= strip.right


def test_a_tab_strip_raises_the_page_on_show(window: Any) -> None:
    from isofightr.ui import theme
    from isofightr.ui.kit_art import Look
    from isofightr.ui.widgets import TabStrip

    layer = layer_on(window)
    strip = TabStrip(layer, 10, 100, ("RULES", "CONTROLS", "DISPLAY"), 20)
    assert strip.active == 0 and not strip.focused
    assert [button.low for button in strip._buttons] == [False, True, True]
    assert strip._buttons[1].label.color == theme.STONE.text_muted
    assert strip._buttons[0].lift > strip._buttons[1].lift, "the others lie low"
    strip.set(2, focused=True)
    assert strip.active == 2 and strip._buttons[2].look is Look.FOCUS
    assert strip._buttons[0].low and strip._buttons[0].look is Look.NORMAL
    rects = strip.rects
    assert all(a.right < b.left for a, b in itertools.pairwise(rects))
    assert strip.at(rects[1].left + 3, rects[1].bottom + 3) == 1
    assert strip.at(rects[2].right + 20, rects[1].bottom + 3) is None
    assert strip.rect.left == 10 and strip.rect.right == rects[-1].right


def test_a_sign_and_a_pip_gauge(window: Any) -> None:
    from isofightr.ui import kit_art, theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.font import TextSize
    from isofightr.ui.widgets import PipGauge, Sign

    layer = layer_on(window)
    sign = Sign(layer, Rect(10, 10, 120, 16), "How many screen pixels each game pixel covers.")
    assert sign.text.endswith(".."), "one line, shortened to fit"
    assert sign.label.size is TextSize.TEXT and sign.label.color == theme.STONE.text
    gauge = PipGauge(layer, 10, 40, 10, 4)
    assert gauge.rect.width == kit_art.pips_width(10) and gauge.lit == 4
    first = gauge._body.sprite.texture
    gauge.lit = 99
    assert gauge.lit == 10 and gauge._body.sprite.texture is not first


def test_the_kit_screen_shows_both_surfaces(window: Any) -> None:
    from isofightr.scenes.flow import GameFlow
    from isofightr.scenes.ui_kit import UiKitView
    from isofightr.ui import theme

    window.switch_to()
    view = UiKitView(window.pixel_buffer, GameFlow(window, window.pixel_buffer))
    window.show_view(view)
    for _ in range(3):
        view.on_update(TICK_SECONDS)
    view.on_draw()
    assert view.title == "UI KIT"
    assert view.live.buttons["play"].surface is theme.STONE
    assert view.still.buttons["play"].surface is theme.INKED
    assert view.buttons["play"].lift == theme.RAISE, "the cursor starts on it"
    assert view.live.tabs.active == 0 and view.still.tabs.active == 1


def test_a_scene_opens_through_the_cloud(window: Any) -> None:
    from isofightr.capture import read_frame
    from isofightr.scenes.flow import GameFlow
    from isofightr.scenes.ui_kit import UiKitView
    from isofightr.ui import wipe

    window.switch_to()
    flow = GameFlow(window, window.pixel_buffer)
    # The scene that is ending: all magenta, put aside as its last frame.
    with window.pixel_buffer.drawing((255, 0, 255, 255)):
        pass
    window.pixel_buffer.keep()
    assert window.pixel_buffer.has_kept
    view = UiKitView(window.pixel_buffer, flow)
    view.start_wipe()
    window.show_view(view)

    def shot() -> Any:
        view.on_draw()
        return read_frame(window).convert("RGB")

    first = shot()
    assert view.wiping
    assert first.getpixel((NATIVE_W // 2, 5)) == (255, 0, 255), "the old scene is still there"
    for _ in range(wipe.CLOSE_TICKS):
        view.on_update(TICK_SECONDS)
    covered = shot()
    colours = {colour for _, colour in covered.getcolors(1 << 16)}
    assert (255, 0, 255) not in colours and len(colours) <= 3, "nothing but cloud"
    for _ in range(wipe.OPEN_TICKS):
        view.on_update(TICK_SECONDS)
    clear = shot()
    assert not view.wiping
    plain = UiKitView(window.pixel_buffer, flow)
    window.show_view(plain)
    for _ in range(wipe.WIPE_TICKS):
        plain.on_update(TICK_SECONDS)
    plain.fade_ticks = 0
    plain.on_draw()
    assert len({colour for _, colour in clear.getcolors(1 << 16)}) > 10, "the scene shows"
    assert (255, 0, 255) not in {colour for _, colour in clear.getcolors(1 << 16)}


def test_a_scene_with_no_frame_kept_starts_under_the_cloud(window: Any) -> None:
    from isofightr.capture import read_frame
    from isofightr.scenes.flow import GameFlow
    from isofightr.scenes.ui_kit import UiKitView

    window.switch_to()
    view = UiKitView(window.pixel_buffer, GameFlow(window, window.pixel_buffer))
    view.start_wipe(from_kept=False)
    window.show_view(view)
    view.on_draw()
    colours = read_frame(window).convert("RGB").getcolors(1 << 16)
    assert len(colours) <= 3, "covered from the first frame"
    assert NATIVE_H  # the buffer is the native size whatever the window is
