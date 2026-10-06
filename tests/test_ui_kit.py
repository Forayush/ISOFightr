"""The UI theme, widget art, icons, backdrop, tweens, focus map and hints (decision D-061).

All pure: no window. The drawing side is covered by ``tests/test_ui_gl.py``.
"""

import json
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.paths import REPO_ROOT
from isofightr.render import placeholder_art
from isofightr.settings import KEYBOARD_ARROWS, KEYBOARD_SOLO, PRESET_BUMPERS, Settings
from isofightr.ui import anim, backdrop, icons, kit_art, theme
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.hints import device_labels, hint_text
from isofightr.ui.kit_art import Look
from isofightr.ui.menu import MenuAction

PALETTE_FILE = REPO_ROOT / "art_src" / "palettes" / "resurrect64.toml"


def resurrect64() -> set[tuple[int, int, int]]:
    with PALETTE_FILE.open("rb") as file:
        return {theme.rgb(value) for value in tomllib.load(file)["colors"]}


def colours(image: Image.Image) -> set[tuple[int, int, int]]:
    """Every colour of an image's visible pixels."""
    return {pixel[:3] for pixel in image.convert("RGBA").getdata() if pixel[3] > 0}


# --- theme -----------------------------------------------------------------------------------


def test_every_theme_colour_is_a_resurrect_64_entry() -> None:
    palette = resurrect64()
    assert set(theme.PALETTE) <= palette
    roles = [value for name, value in vars(theme).items() if name.isupper()]
    for value in roles:
        if isinstance(value, tuple) and len(value) in (3, 4) and isinstance(value[0], int):
            assert value[:3] in palette, value


def test_player_colours_match_the_fighters_rings() -> None:
    for index in range(4):
        assert theme.player_color(index) == placeholder_art.player_color(index)[:3]
    assert theme.player_color(5) == theme.player_color(1), "indices wrap"


# --- widget art ------------------------------------------------------------------------------

ART = {
    "panel": lambda: kit_art.panel(120, 60),
    "button": lambda: kit_art.button(80, 22),
    "button_focus": lambda: kit_art.button(80, 22, Look.FOCUS),
    "button_danger": lambda: kit_art.button(80, 22, Look.DANGER),
    "button_lit": lambda: kit_art.button(80, 22, Look.LIT),
    "button_disabled": lambda: kit_art.button(80, 22, Look.DISABLED),
    "key": lambda: kit_art.key_cap(28, 28),
    "key_focus": lambda: kit_art.key_cap(50, 28, Look.FOCUS),
    "tab_on": lambda: kit_art.tab(64, 20, theme.RED, True),
    "tab_off": lambda: kit_art.tab(64, 20, theme.SKY, False),
    "toggle_on": lambda: kit_art.toggle(40, 16, True),
    "toggle_off": lambda: kit_art.toggle(40, 16, False, True),
    "stepper": lambda: kit_art.stepper(86, 16, True),
    "gauge": lambda: kit_art.gauge(100, 9, 0.6, segmented=True),
    "checkbox": lambda: kit_art.checkbox(11, True, True),
    "swatch": lambda: kit_art.swatch(10, theme.GREEN, True),
    "focus": lambda: kit_art.focus_frame(60, 30),
    "divider": lambda: kit_art.divider(100),
}


@pytest.mark.parametrize("name", sorted(ART))
def test_widget_art_uses_only_palette_colours(name: str) -> None:
    image = ART[name]()
    assert colours(image) and colours(image) <= resurrect64()


def test_corners_are_angled_two_across_for_one_down() -> None:
    mask = kit_art.shape_mask(40, 20, corner=4)
    first = [next(x for x in range(40) if mask.getpixel((x, y))) for y in range(20)]
    assert first[:6] == [8, 6, 4, 2, 0, 0], "the top-left corner steps 2 px per row"
    last = [max(x for x in range(40) if mask.getpixel((x, y))) for y in range(20)]
    assert last[-6:] == [39, 39, 37, 35, 33, 31], "and so does the bottom-right one"
    assert first[-1] == 0 and last[0] == 39, "the other two corners are square"
    square = kit_art.shape_mask(40, 20, corner=4, corners=kit_art.NO_CORNERS)
    assert square.getpixel((0, 0)) == 255
    tiny = kit_art.shape_mask(6, 3, corner=4)
    assert tiny.getbbox() is not None, "a corner never eats a small shape"


def test_a_panel_has_a_border_all_the_way_round() -> None:
    image = kit_art.panel(60, 30)
    mask = kit_art.shape_mask(60, 30)
    for y in range(30):
        row = [x for x in range(60) if mask.getpixel((x, y))]
        for x in (row[0], row[-1]):
            assert image.getpixel((x, y)) == theme.PANEL_BORDER
    assert image.getpixel((30, 15)) == theme.PANEL_FILL
    assert image.getpixel((0, 0))[3] == 0, "outside the angled corner"


def test_looks_differ_and_caption_colours_follow() -> None:
    bodies = {look: kit_art.button(60, 20, look).tobytes() for look in Look}
    assert len(set(bodies.values())) == len(Look)
    assert kit_art.text_color(Look.FOCUS) == theme.TEXT_ON_FOCUS
    assert kit_art.text_color(Look.NORMAL) == theme.TEXT == kit_art.text_color(Look.DANGER)
    assert kit_art.text_color(Look.DISABLED) == theme.TEXT_DIM


def test_a_tab_leans_and_fills_only_when_active() -> None:
    mask = kit_art.slant_mask(40, 11)
    top = next(x for x in range(40) if mask.getpixel((x, 0)))
    bottom = next(x for x in range(40) if mask.getpixel((x, 10)))
    assert (top, bottom) == (5, 0), "2:1: five pixels of lean over eleven rows"
    rows = {sum(1 for x in range(40) if mask.getpixel((x, y))) for y in range(11)}
    assert len(rows) == 1, "a parallelogram: every row is as wide"
    active = kit_art.tab(40, 11, theme.RED, True)
    idle = kit_art.tab(40, 11, theme.RED, False)
    assert active.getpixel((20, 5))[:3] == theme.RED
    assert idle.getpixel((20, 5))[:3] != theme.RED and theme.RED in colours(idle)


def test_a_gauge_fills_from_the_left() -> None:
    def lit(fraction: float) -> int:
        image = kit_art.gauge(52, 8, fraction)
        return sum(1 for x in range(52) if image.getpixel((x, 4)) == theme.GAUGE_FILL)

    assert [lit(0.0), lit(0.5), lit(1.0)] == [0, 25, 50]
    assert lit(-1.0) == 0 and lit(7.0) == 50, "clamped"
    segmented = kit_art.gauge(52, 8, 1.0, segmented=True)
    assert 0 < sum(1 for x in range(52) if segmented.getpixel((x, 4)) == theme.GAUGE_FILL) < 50


def test_the_focus_frame_is_hollow_and_a_key_cap_has_a_front_lip() -> None:
    frame = kit_art.focus_frame(40, 20)
    assert frame.getpixel((20, 10))[3] == 0
    assert frame.getpixel((20, 0))[:3] == frame.getpixel((20, 1))[:3] == theme.FOCUS
    cap = kit_art.key_cap(28, 28)
    assert cap.getpixel((14, 27 - 1))[:3] == theme.INK, "the lip under the top face"
    assert cap.getpixel((14, 12)) == theme.BUTTON_FILL


def test_tint_recolours_only_the_white_pixels() -> None:
    image = Image.new("RGBA", (3, 1))
    image.putdata([(255, 255, 255, 255), (*theme.MIST, 255), (0, 0, 0, 0)])
    tinted = kit_art.tint(image, theme.GOLD)
    assert list(tinted.getdata()) == [(*theme.GOLD, 255), (*theme.MIST, 255), (0, 0, 0, 0)]
    assert image.getpixel((0, 0)) == (255, 255, 255, 255), "the original is left alone"


# --- icons -----------------------------------------------------------------------------------

REQUIRED_ICONS = (
    "arrow_left",
    "arrow_right",
    "arrow_up",
    "arrow_down",
    "check",
    "gear",
    "controller",
    "keyboard",
    "stock",
    "clock",
    "crown",
    "stage",
    "speaker",
)


def recipes() -> dict[str, Image.Image]:
    with icons.ICON_SOURCE.open("rb") as file:
        return icons.parse_icons(tomllib.load(file))


def test_the_packed_icon_sheet_is_up_to_date_with_its_recipes() -> None:
    built = recipes()
    packed = icons.load_icons()
    assert list(packed) == list(built), "run tools/build_ui_art.py"
    for name, image in built.items():
        assert packed[name].tobytes() == image.tobytes(), f"{name}: run tools/build_ui_art.py"
    assert json.loads(icons.ICON_INDEX.read_text(encoding="utf-8"))["size"] == theme.ICON_SIZE


def test_icons_are_square_palette_locked_and_all_there() -> None:
    built = recipes()
    assert set(REQUIRED_ICONS) <= set(built)
    palette = resurrect64()
    for name, image in built.items():
        assert image.size == (theme.ICON_SIZE, theme.ICON_SIZE), name
        assert colours(image) <= palette, name
        assert (255, 255, 255) in colours(image), f"{name} has nothing to recolour"
    assert len({image.tobytes() for image in built.values()}) == len(built), "no two alike"


def test_derived_icons_are_flips_and_turns() -> None:
    built = recipes()
    left, right = built["arrow_left"], built["arrow_right"]
    assert right.tobytes() == left.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes()
    up, down = built["arrow_up"], built["arrow_down"]
    assert up.tobytes() == down.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
    ys = [y for y in range(12) for x in range(12) if down.getpixel((x, y))[3]]
    widest = max(range(12), key=lambda y: sum(1 for x in range(12) if down.getpixel((x, y))[3]))
    assert widest < sum(ys) / len(ys), "the down arrow is widest at the top"


def test_bad_icon_recipes_are_rejected_and_a_missing_sheet_is_survived(tmp_path: Path) -> None:
    base = {"size": 2, "legend": {".": "", "#": "ffffff"}}
    with pytest.raises(icons.IconError, match="not 2 by 2"):
        icons.parse_icons({**base, "icons": {"a": "#.\n#"}})
    with pytest.raises(icons.IconError, match="not in the legend"):
        icons.parse_icons({**base, "icons": {"a": "#.\n?#"}})
    with pytest.raises(icons.IconError, match="unknown 'b'"):
        icons.parse_icons({**base, "icons": {"a": "#.\n.#"}, "derived": {"c": "flip:b"}})
    with pytest.raises(icons.IconError, match="unknown operation"):
        icons.parse_icons({**base, "icons": {"a": "#.\n.#"}, "derived": {"c": "spin:a"}})
    assert icons.load_icons(tmp_path / "none.png", tmp_path / "none.json") == {}


# --- backdrop --------------------------------------------------------------------------------


def test_the_backdrop_layers_are_up_to_date_and_palette_locked() -> None:
    painted = backdrop.paint_layers()
    assert list(painted) == [layer.image for layer in backdrop.LAYERS]
    palette = resurrect64()
    for name, image in painted.items():
        with Image.open(backdrop.BACKDROP_DIR / name) as saved:
            assert saved.convert("RGBA").tobytes() == image.convert("RGBA").tobytes(), (
                f"{name}: run tools/build_ui_art.py"
            )
        assert colours(image) <= palette, name
        assert image.height == NATIVE_H and image.width >= NATIVE_W


def test_layers_scroll_slowly_and_wrap() -> None:
    speeds = [layer.speed for layer in backdrop.LAYERS]
    assert speeds[0] == 0.0 and speeds == sorted(speeds), "nearer layers move faster"
    assert max(speeds) <= 0.25, "slow: it is a backdrop"
    assert backdrop.layer_shift(0, 0.2) == 0
    assert backdrop.layer_shift(100, 0.2) == 20
    assert backdrop.layer_shift(10_000_000, 0.2, 1280) < 1280
    assert backdrop.layer_shift(6400, 0.2, 1280) == 0, "back where it started"


def test_drifting_tiles_climb_sway_and_stay_near_the_screen() -> None:
    start, later = backdrop.drift_positions(0), backdrop.drift_positions(600)
    assert len(start) == len(backdrop.DRIFT_TILES)
    assert all(b[1] != a[1] for a, b in zip(start, later, strict=True)), "every tile moved"
    for tick in range(0, 40_000, 997):
        for (x, y, size), tile in zip(
            backdrop.drift_positions(tick), backdrop.DRIFT_TILES, strict=True
        ):
            assert abs(x - tile.x) <= tile.sway
            assert -backdrop.DRIFT_MARGIN <= y < NATIVE_H + backdrop.DRIFT_MARGIN
            assert size == tile.size
    assert backdrop.drift_positions(123) == backdrop.drift_positions(123), "a pure function"


def test_a_drift_tile_is_a_translucent_palette_block() -> None:
    for half in backdrop.TILE_HALF_WIDTHS:
        image = backdrop.build_drift_tile(half)
        assert image.size == (half * 2, half * 2)
        assert colours(image) <= resurrect64()
        alphas = {pixel[3] for pixel in image.getdata()}
        assert alphas == {0, backdrop.TILE_ALPHA}
        assert image.width % 2 == 0, "even, so it sits on whole pixels"


# --- tweens ----------------------------------------------------------------------------------

EASES = (
    anim.linear,
    anim.ease_in,
    anim.ease_out,
    anim.ease_in_out,
    anim.ease_out_back,
    anim.bounce,
)


@pytest.mark.parametrize("ease", EASES)
def test_every_ease_starts_at_0_ends_at_1_and_clamps(ease: anim.Ease) -> None:
    assert ease(0.0) == pytest.approx(0.0, abs=1e-9)
    assert ease(1.0) == pytest.approx(1.0)
    assert ease(-3.0) == ease(0.0) and ease(9.0) == ease(1.0)


def test_ease_shapes() -> None:
    assert anim.ease_out(0.5) > 0.5 > anim.ease_in(0.5)
    assert anim.ease_in_out(0.5) == pytest.approx(0.5)
    assert max(anim.ease_out_back(step / 50) for step in range(51)) > 1.05, "it overshoots"
    values = [anim.bounce(step / 100) for step in range(101)]
    dips = sum(1 for a, b, c in zip(values, values[1:], values[2:], strict=False) if a > b < c)
    assert dips == 3 and max(values) <= 1.0, "three bounces, never past the target"


def test_progress_slide_and_count_up() -> None:
    assert [anim.progress(tick, 10, 20) for tick in (0, 10, 20, 30, 99)] == [0, 0, 0.5, 1, 1]
    assert anim.progress(5, 5, 0) == 1.0 and anim.progress(4, 5, 0) == 0.0
    assert anim.slide(0, 10, 20, -100, 40) == -100 and anim.slide(30, 10, 20, -100, 40) == 40
    middle = anim.slide(20, 10, 20, -100, 40)
    assert -100 < middle < 40 and isinstance(middle, int)
    counts = [anim.count_up(tick, 0, 30, 187) for tick in range(0, 40)]
    assert counts[0] == 0 and counts[-1] == 187 and counts == sorted(counts)
    assert anim.count_up(30, 0, 30, 12.6) == 13


def test_pulse_blink_wave_shake_and_pop() -> None:
    assert anim.pulse(0, 60) == pytest.approx(0.0) and anim.pulse(30, 60) == pytest.approx(1.0)
    assert all(0.0 <= anim.pulse(tick, 60) <= 1.0 for tick in range(200))
    assert [anim.blink(tick, 4) for tick in range(6)] == [True, True, False, False, True, True]
    offsets = [anim.wave(tick, 0, 3, 40) for tick in range(40)]
    assert max(offsets) == 3 and min(offsets) == -3
    assert anim.wave(10, 0, 3, 40) != anim.wave(10, 2, 3, 40), "letters are out of step"
    assert anim.shake(5, 0) == 0
    jitter = {anim.shake(tick, 2) for tick in range(30)}
    assert jitter == {-2, 0, 2} and anim.shake(7, 2) == anim.shake(7, 2)
    assert anim.pop(0, 10, 12) == 1.0 and anim.pop(10, 10, 12) == 1.5
    assert anim.pop(22, 10, 12) == pytest.approx(1.0)
    assert anim.lerp(2.0, 4.0, 0.25) == 2.5 and anim.clamp01(-1) == 0.0


# --- focus map -------------------------------------------------------------------------------


def grid() -> FocusMap:
    """Two rows of three, and a wide button under them."""
    rects = {
        f"{row}{column}": Rect(10 + column * 40, 100 - row * 30, 30, 20)
        for row in range(2)
        for column in range(3)
    }
    rects["wide"] = Rect(10, 30, 110, 20)
    return FocusMap(rects)


def test_rects_know_their_edges() -> None:
    rect = Rect(10, 20, 30, 40)
    assert (rect.right, rect.top, rect.centre) == (40, 60, (25.0, 40.0))
    assert rect.contains(10, 20) and rect.contains(39, 59) and not rect.contains(40, 59)
    assert rect.inset(5) == Rect(15, 25, 20, 30) and rect.inset(-2) == Rect(8, 18, 34, 44)
    assert rect.overlaps(Rect(39, 59, 5, 5)) and not rect.overlaps(Rect(40, 20, 5, 5))


def test_directions_move_to_the_nearest_thing_that_way() -> None:
    focus = grid()
    assert focus.move("00", MenuAction.RIGHT) == "01"
    assert focus.move("01", MenuAction.RIGHT) == "02"
    assert focus.move("02", MenuAction.RIGHT) == "02", "nothing further: stay"
    assert focus.move("01", MenuAction.DOWN) == "11"
    assert focus.move("11", MenuAction.UP) == "01"
    assert focus.move("12", MenuAction.DOWN) == "wide"
    assert focus.move("wide", MenuAction.UP) == "11", "straight above its middle"
    assert (
        focus.move("00", MenuAction.CONFIRM) == "00" and focus.move("nope", MenuAction.UP) == "nope"
    )


def test_wrapping_goes_round_to_the_far_side() -> None:
    focus = FocusMap(grid().rects, wrap=True)
    assert focus.move("02", MenuAction.RIGHT) == "00"
    assert focus.move("00", MenuAction.LEFT) == "02"
    assert focus.move("wide", MenuAction.DOWN) == "01"


def test_the_mouse_picks_what_is_under_it() -> None:
    focus = grid()
    assert focus.at(15, 105) == "00" and focus.at(95, 75) == "12" and focus.at(60, 40) == "wide"
    assert focus.at(45, 105) is None, "the gap between two tiles"


# --- hints -----------------------------------------------------------------------------------


def test_hints_name_the_real_controls_of_each_device() -> None:
    settings = Settings()
    template = "{stick}: move   {attack}: pick   {special}: back"
    solo = device_labels(settings, "keyboard:" + KEYBOARD_SOLO)
    assert hint_text(template, solo) == "WASD: move   J: pick   K: back"
    arrows = device_labels(settings, "keyboard:" + KEYBOARD_ARROWS)
    assert hint_text(template, arrows) == "arrows: move   NUM_4: pick   NUM_5: back"
    pad = device_labels(settings, "pad:0")
    assert hint_text(template, pad) == "LS: move   A: pick   B: back"
    rebound = settings.with_key(KEYBOARD_SOLO, "attack", "F")
    assert hint_text("{attack}", device_labels(rebound, "keyboard:solo")) == "F"


def test_an_unbound_or_unknown_action_keeps_its_name() -> None:
    unbound = Settings().with_key(KEYBOARD_SOLO, "attack", "")
    labels = device_labels(unbound, "keyboard:solo")
    assert hint_text("{attack}: pick", labels) == "attack: pick"
    assert hint_text("{grab}: add CPU", device_labels(Settings(), "")) == "grab: add CPU"
    bumpers = Settings(gamepad_preset=PRESET_BUMPERS)
    assert hint_text("{up}", device_labels(bumpers, "pad:1")) == "LB"
    assert hint_text("{nonsense}: x", labels) == "{nonsense}: x", "a bad template is shown as is"
    assert hint_text("plain", labels) == "plain"
