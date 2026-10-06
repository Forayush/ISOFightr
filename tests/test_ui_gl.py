"""The UI foundation on a real window (``pytest -m gl``): the game's font as sprites, the
widgets, the menu backdrop, the mouse, control hints and the screen capture tool.

Plan note "13 - Game Modes UI and Flow", decision D-061 (M13 group 0).
"""

from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS

pytestmark = pytest.mark.gl


@pytest.fixture(autouse=True)
def no_real_controllers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever is plugged into this machine must not act in the tests."""
    import pyglet

    class NoControllers:
        def push_handlers(self, **handlers: Any) -> None:
            pass

        def remove_handlers(self, **handlers: Any) -> None:
            pass

        def get_controllers(self) -> list[Any]:
            return []

    monkeypatch.setattr(pyglet.input, "ControllerManager", NoControllers)


def flow_for(window: Any) -> Any:
    from isofightr.scenes.flow import GameFlow

    window.switch_to()
    return GameFlow(window, window.pixel_buffer, seed=1)


def step(window: Any, ticks: int = 1) -> None:
    for _ in range(ticks):
        window.current_view.on_update(TICK_SECONDS)
    window.current_view.on_draw()


def to_window(window: Any, x: int, y: int) -> tuple[int, int]:
    """The window position of the middle of a native pixel."""
    viewport = window.current_view.window_viewport()
    ratio = window.get_pixel_ratio()
    return (
        round((viewport.left + (x + 0.5) * viewport.scale) / ratio),
        round((viewport.bottom + (y + 0.5) * viewport.scale) / ratio),
    )


def kit(window: Any) -> Any:
    from isofightr.scenes.ui_kit import UiKitView

    view = UiKitView(window.pixel_buffer, flow_for(window))
    window.show_view(view)
    step(window, 2)
    return view


def test_a_text_label_lays_out_one_sprite_per_character(window: Any) -> None:
    from isofightr.ui import font, theme
    from isofightr.ui.font import TextSize
    from isofightr.ui.pixel_text import GlyphAtlas
    from isofightr.ui.widgets import UiLayer

    window.switch_to()
    layer = UiLayer(GlyphAtlas())
    label = layer.write("Rook 87%", 100, 50, TextSize.TITLE, theme.GOLD)
    shown = [sprite for sprite in layer.text if sprite.visible]
    assert len(shown) == len("Rook87%"), "the space has no sprite"
    assert len(layer.shadows) == len(layer.text), "every glyph has its shadow"
    assert tuple(shown[0].color)[:3] == theme.GOLD
    assert tuple(layer.shadows[0].color)[:3] == theme.TEXT_SHADOW[:3]
    assert shown[0].left == 100 and shown[0].bottom == 50
    assert label.width == font.text_width("Rook 87%", TextSize.TITLE)
    assert shown[-1].right <= 100 + label.width
    assert all(float(sprite.left).is_integer() for sprite in shown), "on whole pixels"
    assert all(float(sprite.bottom).is_integer() for sprite in shown)

    count = len(layer.text)
    label.text = "Rook 9%"
    assert len(layer.text) == count, "a shorter text reuses the sprites"
    assert sum(1 for sprite in layer.text if sprite.visible) == len("Rook9%")
    label.text = "Bramble 120%"
    assert len(layer.text) > count, "a longer one grows the pool"
    label.color = theme.RED
    assert all(tuple(sprite.color)[:3] == theme.RED for sprite in layer.text)
    label.visible = False
    assert not any(sprite.visible for sprite in layer.text)
    assert not any(sprite.visible for sprite in layer.shadows)
    label.visible = True
    label.alpha = 100
    assert all(sprite.alpha == 100 for sprite in layer.text if sprite.visible)

    centred = layer.write("VS", 320, 10, TextSize.DISPLAY, align="centre")
    right = layer.write("3:00", 600, 10, TextSize.BODY, align="right", shadow=False)
    assert centred.left == 320 - centred.width // 2
    assert right.left + right.width == 600
    plain = len(layer.shadows)
    right.text = "12:00"
    assert len(layer.shadows) == plain, "no shadow sprites for an unshadowed label"


def test_widgets_swap_their_art_without_new_sprites(window: Any) -> None:
    from isofightr.ui import theme
    from isofightr.ui.focus import Rect
    from isofightr.ui.kit_art import Look
    from isofightr.ui.pixel_text import GlyphAtlas
    from isofightr.ui.widgets import Button, Gauge, KeyCap, Stepper, Tab, Toggle, UiLayer

    window.switch_to()
    layer = UiLayer(GlyphAtlas())
    button = Button(layer, Rect(10, 10, 80, 22), "RULES", "gear")
    panels = len(layer.panels)
    resting = layer.panels[0].texture
    button.focus(True)
    assert button.look is Look.FOCUS and layer.panels[0].texture is not resting
    assert button.label.color == theme.TEXT_ON_FOCUS
    button.focus(False)
    assert button.look is Look.NORMAL and layer.panels[0].texture is resting, "art is cached"
    danger = Button(layer, Rect(100, 10, 80, 22), "DEFAULT", look=Look.DANGER)
    danger.focus(True)
    danger.focus(False)
    assert danger.look is Look.DANGER, "a danger button rests in its own look"

    toggle = Toggle(layer, Rect(10, 40, 40, 16))
    assert toggle.label.text == "OFF" and not toggle.on
    toggle.set(True, focused=True)
    assert toggle.label.text == "ON" and toggle.on

    stepper = Stepper(layer, Rect(10, 60, 86, 16), "1.0x")
    stepper.set("1.5x", focused=True)
    assert stepper.label.text == "1.5x" and stepper.label.color == theme.FOCUS_GLOW

    gauge = Gauge(layer, Rect(10, 80, 102, 9))
    gauge.value = 0.5
    half = gauge._body.sprite.texture
    gauge.value = 2.0
    assert gauge.value == 1.0 and gauge._body.sprite.texture is not half

    cap = KeyCap(layer, Rect(10, 100, 28, 28), "J")
    cap.set("L-SHIFT", Look.FOCUS)
    texts = [label.text for label in cap._labels.values()]
    assert sum(1 for text in texts if text) == 1, "one size is shown"
    assert texts[0] == "", "too wide for the big size on a small cap"

    tab = Tab(layer, Rect(10, 140, 64, 20), "P2", theme.SKY)
    assert tab.label.color == theme.SKY
    tab.active = True
    assert tab.active and tab.label.color == theme.TEXT_ON_FOCUS

    before = len(layer.panels)
    for _ in range(3):
        button.focus(True)
        button.focus(False)
        toggle.set(False)
        toggle.set(True)
    assert len(layer.panels) == before > panels


def test_the_backdrop_fills_the_screen_and_drifts(window: Any) -> None:
    from isofightr.capture import read_frame
    from isofightr.ui.backdrop import LAYERS, layer_shift

    window.switch_to()
    flow = flow_for(window)
    backdrop = flow.backdrop()
    assert flow.backdrop() is backdrop, "one shared backdrop"

    def shot(tick: int) -> Any:
        with window.pixel_buffer.drawing((255, 0, 255, 255)):
            backdrop.draw(tick)
        return read_frame(window)

    first = shot(0)
    colours = first.getcolors(maxcolors=100000)
    assert colours is not None and len(colours) > 4
    assert all(colour[:3] != (255, 0, 255) for _, colour in colours), "no gap in the sky"
    assert shot(0).tobytes() == first.tobytes()
    assert shot(600).tobytes() != first.tobytes(), "it moves"
    slow = LAYERS[1]
    seam = next(tick for tick in range(0, 40000, 20) if layer_shift(tick, slow.speed) > 640)
    late = shot(seam)
    assert all(colour[:3] != (255, 0, 255) for _, colour in late.getcolors(maxcolors=100000))


def test_menu_ticks_carry_from_scene_to_scene(window: Any) -> None:
    flow = flow_for(window)
    flow.show_title()
    step(window, 5)
    assert flow.menu_ticks == 5
    flow.show_main_menu()
    step(window, 3)
    assert flow.menu_ticks == 8, "the backdrop drifts on across scenes"


def test_the_mouse_moves_the_cursor_and_clicks_on_the_kit_screen(window: Any) -> None:
    import arcade

    view = kit(window)
    assert view.cursor == "play"
    rect = view.focus_map.rects["parry"]
    x, y = to_window(window, int(rect.centre[0]), int(rect.centre[1]))
    view.on_mouse_motion(x, y, 1, 0)
    step(window)
    assert view.cursor == "parry" and not view.parry
    view.on_mouse_press(x, y, arcade.MOUSE_BUTTON_LEFT, 0)
    step(window)
    assert view.parry and view.toggle.on

    off = to_window(window, 2, NATIVE_H - 2)
    view.on_mouse_press(*off, arcade.MOUSE_BUTTON_LEFT, 0)
    step(window)
    assert view.parry and view.cursor == "parry", "a click on nothing does nothing"

    view.on_key_press(arcade.key.D, 0)
    step(window)
    view.on_key_release(arcade.key.D, 0)
    step(window)
    assert view.cursor != "parry", "the keyboard still moves the cursor"
    view.on_mouse_press(x, y, arcade.MOUSE_BUTTON_RIGHT, 0)
    step(window)
    assert type(window.current_view).__name__ == "MainMenuView", "right click goes back"


def test_the_mouse_works_on_the_list_menus(window: Any) -> None:
    import arcade

    flow = flow_for(window)
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    rows = view.rows
    rules = [item.key for item in view.menu.items].index("rules")
    native = (rows.left + 30, rows.top - rules * rows.row_height - rows.row_height // 2)
    assert rows.row_at(*native) == rules
    assert (
        rows.row_at(rows.left - 5, native[1]) is None
        and rows.row_at(native[0], rows.top + 3) is None
    )
    view.on_mouse_motion(*to_window(window, *native), 0, 1)
    step(window)
    assert view.menu.cursor == rules
    view.on_mouse_press(*to_window(window, *native), arcade.MOUSE_BUTTON_LEFT, 0)
    step(window)
    assert type(window.current_view).__name__ == "RulesView"
    below = (native[0], rows.top - 40 * rows.row_height)
    assert window.current_view.rows.row_at(*below) is None


def test_the_mouse_is_mapped_through_the_letterbox(
    window: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from isofightr.render.pixel_scale import integer_scale_viewport

    view = kit(window)
    monkeypatch.setattr(view, "window_viewport", lambda: integer_scale_viewport(1366, 768))
    monkeypatch.setattr(window, "get_pixel_ratio", lambda: 1.0)
    assert view.native_point(42, 100) is None, "on the left bar"
    assert view.native_point(43, 24) == (0, 0)
    assert view.native_point(43 + 2 * 100, 24 + 2 * 50) == (100, 50)
    rect = view.focus_map.rects["pool"]
    view.on_mouse_motion(43 + 2 * rect.left + 2, 24 + 2 * rect.bottom + 2, 0, 0)
    assert view.cursor == "pool"
    view.on_mouse_motion(10, 10, 0, 0)
    assert view.cursor == "pool", "the letterbox moves nothing"


def test_the_footer_names_the_controls_of_the_device_that_acted(window: Any) -> None:
    import arcade

    from isofightr.settings import KEYBOARD_SOLO, Settings

    flow = flow_for(window)
    flow.settings = Settings().with_key(KEYBOARD_SOLO, "attack", "F")
    flow.show_main_menu()
    step(window, 2)
    view = window.current_view
    assert view._footer.text == "WASD: move   F: pick   K: back"
    view.on_key_press(arcade.key.DOWN, 0)
    step(window)
    view.on_key_release(arcade.key.DOWN, 0)
    step(window)
    assert view.active_device == "keyboard:arrows"
    assert view._footer.text == "arrows: move   NUM_4: pick   NUM_5: back"
    view.on_key_press(arcade.key.S, 0)
    step(window)
    assert view._footer.text.startswith("WASD")


@pytest.mark.parametrize(
    "screen",
    ["title", "main", "rules", "controls", "charselect", "stageselect", "settings", "kit", "hud",
     "pause", "training", "results"],
)  # fmt: skip
def test_every_screen_can_be_captured(window: Any, screen: str) -> None:
    from isofightr.capture import SCREENS, capture_screen

    assert screen in SCREENS
    sheet = capture_screen(window, screen, ticks=[3, 12])
    assert sheet.size == (NATIVE_W * 2, NATIVE_H)
    colours = sheet.getcolors(maxcolors=200000)
    assert colours is not None and len(colours) > 6, "something was drawn"
    expected = {
        "title": "TitleView",
        "main": "MainMenuView",
        "rules": "RulesView",
        "controls": "RebindView",
        "charselect": "CharacterSelectView",
        "stageselect": "StageSelectView",
        "settings": "SettingsView",
        "kit": "UiKitView",
        "hud": "BattleView",
        "pause": "BattleView",
        "training": "BattleView",
        "results": "ResultsView",
    }
    assert type(window.current_view).__name__ == expected[screen]
    if screen in ("pause", "training"):
        assert window.current_view.menu_open
    if screen == "hud":
        assert len(window.current_view.match.fighters) == 4


def test_a_screen_capture_follows_a_key_script_and_crops_and_scales(window: Any) -> None:
    from isofightr.capture import capture_screen, parse_script

    script = parse_script("ENTER@4,ENTER!5")
    sheet = capture_screen(
        window, "title", script, ticks=[2, 20], crop=(100, 50, 200, 100), scale=2
    )
    assert sheet.size == (2 * 200 * 2, 100 * 2)
    assert type(window.current_view).__name__ == "MainMenuView", "the script walked on"
    first, second = sheet.crop((0, 0, 400, 200)), sheet.crop((400, 0, 800, 200))
    assert first.tobytes() != second.tobytes()


def test_unknown_or_unbuilt_screens_are_refused(window: Any) -> None:
    from isofightr.capture import capture_screen

    with pytest.raises(ValueError, match="unknown screen"):
        capture_screen(window, "nope")
    with pytest.raises(ValueError, match="not built yet"):
        capture_screen(window, "loading")
