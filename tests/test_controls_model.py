"""Bindings: two controls per action, per-button gamepad tables, and the Controls screen's
model (plan note 08, decision D-061, M13 group 2).

Pure: no window. The screen itself is driven in ``tests/test_flow_gl.py``.
"""

import itertools
import math
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from isofightr.config import MODIFIER_THRESHOLD, TRIGGER_THRESHOLD
from isofightr.input.gamepad import (
    CONTROL_FIELDS,
    LAYOUT_BUMPERS,
    LAYOUT_CUSTOM,
    LAYOUT_RIGHT_STICK,
    MODIFIER_BUMPERS,
    PAD_ACTIONS,
    PAD_CONTROLS,
    PAD_LAYOUTS,
    RIGHT_STICK_MODIFIERS,
    STICK_SMASH,
    PadBindings,
    PadState,
    gamepad_frame,
    held_controls,
    process_stick,
)
from isofightr.input.keyboard import KeyboardBindings, keyboard_frame
from isofightr.scenes import controls_model as model
from isofightr.settings import (
    DEFAULT_KEYS,
    KEYBOARD_ACTIONS,
    KEYBOARD_ARROWS,
    Settings,
    from_data,
    keys_from_data,
    load_settings,
    pad_from_data,
    save_settings,
    to_toml,
)
from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    VERTICAL_NONE,
    VERTICAL_UP,
    Button,
    Dir8,
    InputFrame,
    stick_to_world,
)
from isofightr.ui import pad_art, theme
from isofightr.ui.hints import battle_help, device_labels
from isofightr.ui.menu import MenuAction, MenuInput, pad_actions
from isofightr.ui.move_list import gamepad_labels

SOLO, ARROWS, PAD0, PAD2 = model.DEVICES[0], model.DEVICES[1], "pad:0", "pad:2"


# --- the old presets, kept here exactly as they were before the binding table --------------


@dataclass(frozen=True)
class OldPreset:
    """The preset record ``input/gamepad.py`` had before decision D-061."""

    attack: tuple[str, ...]
    special: tuple[str, ...]
    jump: tuple[str, ...]
    grab: tuple[str, ...]
    shield: tuple[str, ...]
    strong: tuple[str, ...]
    up: tuple[str, ...]
    down: tuple[str, ...]
    right_stick_modifiers: bool


OLD_RIGHT_STICK = OldPreset(
    attack=("a",),
    special=("b",),
    jump=("x", "y"),
    grab=("right_shoulder",),
    shield=("left_trigger", "right_trigger"),
    strong=("left_shoulder",),
    up=(),
    down=(),
    right_stick_modifiers=True,
)
OLD_BUMPERS = OldPreset(
    attack=("a",),
    special=("b",),
    jump=("x", "y"),
    grab=("right_shoulder",),
    shield=("right_trigger",),
    strong=(),
    up=("left_shoulder",),
    down=("left_trigger",),
    right_stick_modifiers=False,
)
OLD_BUTTONS = (
    ("attack", Button.ATTACK),
    ("special", Button.SPECIAL),
    ("jump", Button.JUMP),
    ("grab", Button.GRAB),
    ("shield", Button.SHIELD),
    ("strong", Button.STRONG),
)


def old_is_held(state: PadState, controls: tuple[str, ...]) -> bool:
    for name in controls:
        value = getattr(state, name)
        if value is True or (not isinstance(value, bool) and value >= TRIGGER_THRESHOLD):
            return True
    return False


def old_gamepad_frame(state: PadState, preset: OldPreset) -> InputFrame:
    """``gamepad_frame`` as it was written before the binding table."""
    stick_u, stick_v = process_stick(state.left_x, state.left_y)
    move = stick_to_world(stick_u, stick_v)
    up, down = old_is_held(state, preset.up), old_is_held(state, preset.down)
    if preset.right_stick_modifiers and abs(state.right_y) > abs(state.right_x):
        up = up or state.right_y >= MODIFIER_THRESHOLD
        down = down or state.right_y <= -MODIFIER_THRESHOLD
    vertical = VERTICAL_NONE if up == down else (VERTICAL_UP if up else VERTICAL_DOWN)
    held = 0
    for field_name, button in OLD_BUTTONS:
        if old_is_held(state, getattr(preset, field_name)):
            held |= button
    x, y = state.right_x, state.right_y
    cstick = None
    if math.hypot(x, y) >= MODIFIER_THRESHOLD and not (
        preset.right_stick_modifiers and abs(y) > abs(x)
    ):
        cstick = stick_to_world(x, y).normalized()
    return InputFrame(move=move, vertical=vertical, held=held, cstick=cstick)


OLD_BUTTON_FIELDS = ("a", "b", "x", "y", "left_shoulder", "right_shoulder")
STICK_STEPS = (-1.0, -0.6, 0.0, 0.3, 0.6, 1.0)
TRIGGER_STEPS = (0.0, TRIGGER_THRESHOLD - 0.01, TRIGGER_THRESHOLD, 1.0)


@pytest.mark.parametrize(
    ("old", "new"),
    [(OLD_RIGHT_STICK, RIGHT_STICK_MODIFIERS), (OLD_BUMPERS, MODIFIER_BUMPERS)],
    ids=["right_stick_modifiers", "modifier_bumpers"],
)
def test_the_stock_layouts_reproduce_the_old_presets_exactly(
    old: OldPreset, new: PadBindings
) -> None:
    """Every action, for every combination of the buttons, triggers and sticks the old
    presets read, gives the same ``InputFrame`` from the binding table."""
    checked = 0
    for pressed in itertools.product((False, True), repeat=len(OLD_BUTTON_FIELDS)):
        buttons = dict(zip(OLD_BUTTON_FIELDS, pressed, strict=True))
        for left_trigger, right_trigger in itertools.product(TRIGGER_STEPS, repeat=2):
            state = PadState(left_trigger=left_trigger, right_trigger=right_trigger, **buttons)
            assert gamepad_frame(state, new) == old_gamepad_frame(state, old), state
            checked += 1
    for right_x, right_y in itertools.product(STICK_STEPS, repeat=2):
        for left_x, left_y in ((0.0, 0.0), (0.7, -0.2), (-1.0, 1.0)):
            for extra in ({}, {"left_shoulder": True}, {"left_trigger": 1.0, "a": True}):
                state = PadState(left_x, left_y, right_x, right_y, **extra)  # type: ignore[arg-type]
                assert gamepad_frame(state, new) == old_gamepad_frame(state, old), state
                checked += 1
    assert checked > 1000
    for action in ("attack", "special", "jump", "grab", "shield", "strong", "up", "down"):
        fields = tuple(CONTROL_FIELDS[control] for control in new.controls(action))
        assert fields == getattr(old, action), action
    assert new.right_stick_modifiers is old.right_stick_modifiers
    assert new.walk == new.taunt == (), "the presets never had these on a gamepad"


def test_the_default_bindings_are_the_default_layout() -> None:
    assert PadBindings() == RIGHT_STICK_MODIFIERS == PAD_LAYOUTS[LAYOUT_RIGHT_STICK]
    assert RIGHT_STICK_MODIFIERS.layout == LAYOUT_RIGHT_STICK
    assert MODIFIER_BUMPERS.layout == LAYOUT_BUMPERS and MODIFIER_BUMPERS.right_stick == STICK_SMASH
    assert RIGHT_STICK_MODIFIERS.name != MODIFIER_BUMPERS.name
    assert [pad.layout for pad in Settings().pads] == [LAYOUT_RIGHT_STICK] * 4


# --- the gamepad binding table -------------------------------------------------------------


def test_binding_a_pad_control_takes_it_from_whatever_had_it() -> None:
    pad = PadBindings().with_control("taunt", "dpup")
    assert pad.taunt == ("dpup",) and pad.layout == LAYOUT_CUSTOM and pad.name == "Custom"
    stolen = pad.with_control("special", "a")
    assert stolen.special == ("a",) and stolen.attack == (), "attack is left with nothing"
    assert stolen.action_of("a") == "special" and stolen.action_of("b") is None
    second = PadBindings().with_control("attack", "dpdown", slot=1)
    assert second.attack == ("a", "dpdown")
    replaced = second.with_control("attack", "dpleft", slot=1)
    assert replaced.attack == ("a", "dpleft"), "at most two controls"
    assert second.with_control("attack", "dpdown", slot=0).attack == ("dpdown",)
    jump = PadBindings().with_control("shield", "y")
    assert jump.jump == ("x",) and jump.shield == ("y", "righttrigger")
    first_empty = PadBindings().with_control("walk", "leftstick", slot=1)
    assert first_empty.walk == ("leftstick",), "a secondary on an empty action is its primary"
    assert PadBindings().with_control("attack", "start") == PadBindings(), "Start is fixed"
    assert PadBindings().with_control("move_up", "a") == PadBindings()


def test_removing_a_pad_control_promotes_the_other() -> None:
    pad = PadBindings()
    assert pad.without("jump", 0).jump == ("y",)
    assert pad.without("jump", 1).jump == ("x",)
    assert pad.without("attack", 0).attack == () and pad.without("attack", 5) == pad
    assert pad.without("nonsense") == pad


def test_new_controls_reach_the_game() -> None:
    pad = (
        PadBindings()
        .with_control("taunt", "dpup")
        .with_control("walk", "leftstick")
        .with_control("up", "dpleft")
        .with_control("down", "rightstick")
    )
    assert gamepad_frame(PadState(dpad_up=True), pad).held == Button.TAUNT
    assert gamepad_frame(PadState(left_stick_click=True), pad).held == Button.WALK
    assert gamepad_frame(PadState(dpad_left=True), pad).vertical == VERTICAL_UP
    assert gamepad_frame(PadState(right_stick_click=True), pad).vertical == VERTICAL_DOWN
    assert gamepad_frame(PadState(dpad_up=True)).held == 0, "nothing by default"
    assert gamepad_frame(PadState(start=True), pad) == InputFrame(), "Start never acts"
    swapped = PadBindings().with_control("attack", "b").with_control("special", "a")
    assert gamepad_frame(PadState(a=True), swapped).held == Button.SPECIAL
    assert gamepad_frame(PadState(b=True), swapped).held == Button.ATTACK


def test_held_controls_names_everything_bindable() -> None:
    assert held_controls(PadState()) == frozenset()
    state = PadState(a=True, left_trigger=1.0, dpad_right=True, start=True, right_trigger=0.1)
    assert held_controls(state) == {"a", "lefttrigger", "dpright"}
    everything = PadState(
        a=True, b=True, x=True, y=True, left_shoulder=True, right_shoulder=True,
        left_trigger=1.0, right_trigger=1.0, left_stick_click=True, right_stick_click=True,
        dpad_up=True, dpad_down=True, dpad_left=True, dpad_right=True,
    )  # fmt: skip
    assert held_controls(everything) == set(PAD_CONTROLS)


# --- two keys per action -------------------------------------------------------------------


def test_a_second_key_is_added_without_losing_the_first() -> None:
    settings = Settings().with_key("solo", "jump", "W", slot=1)
    assert settings.bound_keys("solo", "jump") == ("SPACE", "W")
    assert settings.bound_keys("solo", "move_up") == (), "W was taken from move up"
    assert settings.keys["solo"]["jump"] == "SPACE" and settings.alt_keys["solo"]["jump"] == "W"
    assert Settings().bound_keys("solo", "jump") == ("SPACE",), "the original is unchanged"
    assert settings.bound_keys("arrows", "jump") == ("NUM_0",), "other layouts untouched"
    third = settings.with_key("solo", "jump", "X", slot=1)
    assert third.bound_keys("solo", "jump") == ("SPACE", "X"), "never more than two"
    primary = settings.with_key("solo", "jump", "Z", slot=0)
    assert primary.bound_keys("solo", "jump") == ("Z", "W")
    same = settings.with_key("solo", "jump", "W", slot=0)
    assert same.bound_keys("solo", "jump") == ("W",), "one key is never both"
    empty = Settings().with_key("arrows", "walk", "RCTRL", slot=1)
    assert empty.bound_keys("arrows", "walk") == ("RCTRL",)
    assert empty.keys["arrows"]["walk"] == "RCTRL", "a lone key is the primary"


def test_a_key_taken_from_another_action_leaves_it_unbound() -> None:
    settings = Settings().with_key("solo", "special", "J")
    assert settings.keys["solo"]["special"] == "J" and settings.keys["solo"]["attack"] == ""
    both = Settings().with_key("solo", "attack", "F", slot=1).with_key("solo", "grab", "J")
    assert both.bound_keys("solo", "attack") == ("F",), "the other key moves up"
    assert both.bound_keys("solo", "grab") == ("J",)


@pytest.mark.parametrize("key", ["ENTER", "ESCAPE", "RETURN"])
def test_enter_and_escape_cannot_be_bound(key: str) -> None:
    assert Settings().with_key("solo", "attack", key) == Settings()
    assert Settings().with_key("solo", "attack", key, slot=1) == Settings()
    assert not model.can_bind(SOLO, key)
    assert model.bind(Settings(), SOLO, "attack", 0, key) == Settings()
    loaded = from_data({"keyboard": {"solo": {"attack": key, "jump": ["SPACE", key]}}})
    assert loaded.bound_keys("solo", "attack") == ()
    assert loaded.bound_keys("solo", "jump") == ("SPACE",)


def test_clearing_and_defaults() -> None:
    settings = Settings().with_key("solo", "jump", "W", slot=1)
    assert settings.without_key("solo", "jump", 0).bound_keys("solo", "jump") == ("W",)
    assert settings.without_key("solo", "jump", 1).bound_keys("solo", "jump") == ("SPACE",)
    assert settings.with_key("solo", "jump", "", slot=1) == settings.without_key("solo", "jump", 1)
    assert settings.without_key("solo", "attack").bound_keys("solo", "attack") == ()
    restored = settings.with_default_keys("solo")
    assert restored.keys["solo"] == dict(DEFAULT_KEYS["solo"])
    assert restored == Settings()
    assert settings.with_key("mouse", "jump", "Q") == settings
    assert settings.with_key("solo", "fly", "Q") == settings


def test_both_keys_of_an_action_work_in_the_game() -> None:
    bindings = KeyboardBindings(
        name="test",
        move_up=1,
        move_down=2,
        move_left=3,
        move_right=4,
        up=5,
        down=6,
        buttons=((7, Button.ATTACK), (8, Button.ATTACK), (9, Button.JUMP)),
        alternates=((11, "move_up"), (12, "down"), (13, "move_left")),
    )
    assert keyboard_frame(bindings, {8}).held == Button.ATTACK
    assert keyboard_frame(bindings, {7, 8}).held == Button.ATTACK
    assert keyboard_frame(bindings, {11}) == keyboard_frame(bindings, {1})
    assert keyboard_frame(bindings, {1, 11}) == keyboard_frame(bindings, {1}), "not twice as fast"
    assert keyboard_frame(bindings, {12}).vertical == VERTICAL_DOWN
    assert keyboard_frame(bindings, {5, 12}).vertical == VERTICAL_NONE, "up and down cancel"
    assert keyboard_frame(bindings, {13, 4}).move.length() == 0.0, "left and right cancel"
    west = keyboard_frame(bindings, {13}).move
    assert (west.x, west.y) == pytest.approx((Dir8.W.world.x, Dir8.W.world.y))
    assert set(bindings.keys()) >= {11, 12, 13}
    plain = replace(bindings, alternates=())
    assert keyboard_frame(plain, {11}) == InputFrame()


# --- the settings file ---------------------------------------------------------------------


def test_bindings_round_trip_through_the_settings_file(tmp_path: Path) -> None:
    settings = (
        Settings()
        .with_key("solo", "jump", "W", slot=1)
        .with_key("arrows", "walk", "RCTRL")
        .with_key("arrows", "attack", "RSHIFT", slot=1)
    )
    custom = PadBindings().with_control("taunt", "dpup").with_control("attack", "x", slot=1)
    settings = settings.with_pad(1, custom).with_pad(3, MODIFIER_BUMPERS)
    path = tmp_path / "settings.toml"
    save_settings(path, settings)
    assert load_settings(path) == settings
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["keyboard"]["solo"]["jump"] == ["SPACE", "W"], "two keys are a list"
    assert parsed["keyboard"]["solo"]["attack"] == "J", "one key is still a plain string"
    assert parsed["keyboard"]["solo"]["move_up"] == ""
    assert parsed["pad"]["1"]["attack"] == ["a", "x"] and parsed["pad"]["1"]["taunt"] == ["dpup"]
    assert parsed["pad"]["3"]["right_stick"] == "smash" and parsed["pad"]["3"]["strong"] == []
    assert set(parsed["pad"]) == {"0", "1", "2", "3"}
    assert "preset" not in parsed["gamepad"]
    assert from_data(tomllib.loads(to_toml(Settings()))) == Settings()


def test_keys_load_as_a_string_or_a_list_and_bad_ones_are_skipped() -> None:
    defaults = DEFAULT_KEYS["solo"]
    bound = keys_from_data(
        {
            "attack": ["F", "G", "H"],
            "special": "F",
            "jump": ["SPACE", 4, "", "ESCAPE", "Q"],
            "grab": 12,
            "shield": [],
            "taunt": "W",
            "nonsense": "Z",
        },
        defaults,
    )
    assert bound["attack"] == ("F", "G"), "a third key is dropped"
    assert bound["special"] == (), "F already belongs to attack"
    assert bound["jump"] == ("SPACE", "Q"), "numbers, blanks and Escape are skipped"
    assert bound["grab"] == ("L",), "not a key name at all: the default stays"
    assert bound["shield"] == (), "an empty list means not bound"
    assert bound["taunt"] == ("W",) and bound["move_up"] == (), "a default never doubles up"
    assert bound["strong"] == ("U",)
    assert set(bound) == set(KEYBOARD_ACTIONS)
    assert keys_from_data(None, defaults) == {a: (defaults[a],) for a in KEYBOARD_ACTIONS}
    assert keys_from_data("x", DEFAULT_KEYS["arrows"])["walk"] == ()


def test_a_pad_table_loads_tolerantly() -> None:
    pad = pad_from_data(
        {
            "attack": ["b", "nonsense", "a", "x"],
            "special": "b",
            "jump": 3,
            "taunt": "dpup",
            "shield": ["start"],
            "right_stick": "sideways",
            "extra": True,
        },
        PadBindings(),
    )
    assert pad.attack == ("b", "a"), "unknown names skipped, and never a third"
    assert pad.special == (), "b already belongs to attack"
    assert pad.jump == ("x", "y"), "malformed: the layout's controls stay"
    assert pad.taunt == ("dpup",) and pad.shield == (), "Start cannot be bound"
    assert pad.right_stick == "modifiers"
    assert pad.grab == ("rightshoulder",) and pad.strong == ("leftshoulder",)
    assert pad_from_data(None, MODIFIER_BUMPERS) == MODIFIER_BUMPERS
    assert pad_from_data([1], MODIFIER_BUMPERS) == MODIFIER_BUMPERS
    partial = pad_from_data({"attack": ["x"]}, PadBindings())
    assert partial.attack == ("x",) and partial.jump == ("y",), "x is not bound twice"
    assert pad_from_data({"right_stick": "smash"}, PadBindings()).right_stick == "smash"


def test_an_old_file_with_a_preset_fills_every_pad_from_it() -> None:
    old = from_data({"gamepad": {"preset": "modifier_bumpers", "deadzone": 0.25}})
    assert [pad.layout for pad in old.pads] == [LAYOUT_BUMPERS] * 4 and old.deadzone == 0.25
    mixed = from_data(
        {"gamepad": {"preset": "modifier_bumpers"}, "pad": {"1": {"attack": ["y"]}, "9": {}}}
    )
    assert mixed.pad(0) == MODIFIER_BUMPERS
    assert mixed.pad(1).attack == ("y",) and mixed.pad(1).jump == ("x",)
    assert mixed.pad(1).up == ("leftshoulder",), "the rest of its table comes from the preset"
    assert from_data({"gamepad": {"preset": "sideways"}}).pad(0) == PadBindings()
    assert from_data({"pad": 3}).pads == Settings().pads
    assert from_data({"pad": {"0": "x"}}).pads == Settings().pads


def test_a_corrupt_controls_file_never_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        "[keyboard.solo]\nattack = [1, 2]\njump = 7\n[pad.0]\nattack = 5\n[pad.x]\n",
        "utf-8",
    )
    loaded = load_settings(path)
    assert loaded.bound_keys("solo", "attack") == ()
    assert loaded.bound_keys("solo", "jump") == ("SPACE",)
    assert loaded.pad(0) == PadBindings()
    assert (
        Settings().with_pad(9, MODIFIER_BUMPERS) == Settings()
        and Settings().pad(9) == PadBindings()
    )


# --- the screen's model --------------------------------------------------------------------


@pytest.mark.parametrize("device", [SOLO, PAD0])
def test_every_action_of_a_device_has_exactly_one_tile(device: str) -> None:
    tiles = [tile for group in model.groups(device) for tile in group.tiles]
    bindable = [tile.action for tile in tiles if not tile.fixed]
    assert sorted(bindable) == sorted(model.actions(device))
    spots = [(group.column, group.band, tile.column, tile.row)
             for group in model.groups(device) for tile in group.tiles]  # fmt: skip
    assert len(set(spots)) == len(spots), "no two tiles in one place"
    assert {group.column for group in model.groups(device)} == {0, 1, 2}
    assert [tile.action for tile in tiles if tile.fixed][-1] == model.FIXED_PAUSE
    assert all(tile.label == tile.label.upper() for tile in tiles)


def test_devices_and_tabs() -> None:
    assert model.DEVICES == (SOLO, ARROWS, "pad:0", "pad:1", "pad:2", "pad:3")
    settings = Settings()
    assert [model.tab_device(settings, tab) for tab in range(4)] == [SOLO, ARROWS, "pad:0", "pad:1"]
    remembered = replace(settings, slot_devices=("pad:3", "", "keyboard:arrows", "bogus"))
    assert [model.tab_device(remembered, tab) for tab in range(4)] == [
        "pad:3", ARROWS, ARROWS, "pad:1",
    ]  # fmt: skip
    stepped = model.with_tab_device(settings, 0, 1)
    assert stepped.slot_devices[0] == ARROWS and model.tab_device(stepped, 0) == ARROWS
    assert model.with_tab_device(settings, 0, -1).slot_devices[0] == "pad:3", "it wraps"
    assert model.with_tab_device(settings, 2, 1).slot_devices == ("keyboard:solo", "", "pad:1", "")
    assert model.is_pad(PAD2) and model.pad_slot(PAD2) == 2 and not model.is_pad(SOLO)
    assert model.layout_of(ARROWS) == KEYBOARD_ARROWS
    assert set(model.DEVICE_NAMES) == set(model.DEVICES)


def test_tile_labels() -> None:
    settings = Settings()
    assert model.tile_label(settings, SOLO, "attack", 0) == "J"
    assert model.tile_label(settings, SOLO, "attack", 1) == "", "an empty secondary"
    assert model.tile_label(settings, SOLO, "down", 0) == ","
    assert model.tile_label(settings, SOLO, "shield", 0) == "L-SHIFT"
    assert model.tile_label(settings, ARROWS, "attack", 0) == "NUM 4"
    assert model.tile_label(settings, ARROWS, "walk", 0) == "n/a"
    assert model.tile_label(settings, SOLO, model.FIXED_PAUSE, 0) == "ESC"
    assert model.tile_label(settings, PAD0, model.FIXED_PAUSE, 0) == "START"
    assert model.tile_label(settings, PAD0, model.FIXED_STICK, 0) == "L-STICK"
    assert model.tile_label(settings, PAD0, "jump", 0) == "X"
    assert model.tile_label(settings, PAD0, "jump", 1) == "Y"
    assert model.tile_label(settings, PAD0, "shield", 1) == "RT"
    assert model.tile_label(settings, PAD0, "taunt", 0) == "n/a"
    assert model.tile_label(settings, PAD0, "up", 0) == "R-STICK", "the right stick does it"
    bumpers = settings.with_pad(0, MODIFIER_BUMPERS)
    assert model.tile_label(bumpers, PAD0, "up", 0) == "LB"
    assert model.tile_label(bumpers, PAD0, "strong", 0) == "R-STICK", "the smash stick"
    no_modifiers = settings.with_pad(0, replace(PadBindings(), right_stick=STICK_SMASH))
    assert model.tile_label(no_modifiers, PAD0, "up", 0) == "n/a"
    assert (
        model.control_label("", False) == "n/a" and model.control_label("dpleft", True) == "D-LEFT"
    )


def test_binding_through_the_model_on_each_kind_of_device() -> None:
    settings = Settings()
    keyboard = model.bind(settings, SOLO, "attack", 0, "F")
    assert model.bound(keyboard, SOLO, "attack") == ("F",)
    assert model.owner(keyboard, SOLO, "F") == "attack" and model.owner(keyboard, SOLO, "J") is None
    taken = model.bind(keyboard, SOLO, "special", 1, "F")
    assert model.bound(taken, SOLO, "special") == ("K", "F")
    assert model.bound(taken, SOLO, "attack") == () and model.is_missing(taken, SOLO, "attack")
    pad = model.bind(settings, PAD2, "taunt", 0, "dpup")
    assert model.bound(pad, PAD2, "taunt") == ("dpup",) and pad.pad(0) == PadBindings()
    assert model.bind(settings, PAD2, "attack", 0, "start") == settings
    assert model.bind(settings, PAD2, "attack", 0, "J") == settings, "a key is not a button"
    assert model.bind(settings, PAD2, "move_up", 0, "a") == settings, "the stick is fixed"
    assert model.bind(settings, SOLO, "attack", 0, "") == settings
    assert model.unbind(pad, PAD2, "taunt", 0) == settings
    assert model.bound(model.unbind(settings, SOLO, "jump", 0), SOLO, "jump") == ()
    assert model.unbind(settings, SOLO, "nonsense", 0) == settings


def test_default_resets_one_device_only() -> None:
    settings = model.bind(Settings(), SOLO, "attack", 0, "F")
    settings = model.bind(settings, ARROWS, "attack", 0, "RSHIFT")
    settings = model.bind(settings, PAD0, "taunt", 0, "dpup")
    settings = model.bind(settings, PAD2, "taunt", 0, "dpdown")
    solo = model.with_defaults(settings, SOLO)
    assert model.bound(solo, SOLO, "attack") == ("J",)
    assert model.bound(solo, ARROWS, "attack") == ("RSHIFT",), "the other keyboard is kept"
    assert solo.pads == settings.pads
    pad = model.with_defaults(settings, PAD0)
    assert pad.pad(0) == PadBindings() and pad.pad(2) == settings.pad(2)
    assert pad.keys == settings.keys


def test_warnings_name_what_a_player_cannot_do() -> None:
    assert model.warnings(Settings(), SOLO) == [] and model.warnings(Settings(), PAD0) == []
    no_attack = model.unbind(Settings(), SOLO, "attack", 0)
    assert model.warnings(no_attack, SOLO) == ["NOT BOUND: ATTACK"]
    worse = model.unbind(model.unbind(no_attack, SOLO, "move_left", 0), SOLO, "jump", 0)
    assert model.warnings(worse, SOLO) == ["NOT BOUND: LEFT, ATTACK, JUMP"]
    assert model.warnings(model.unbind(Settings(), SOLO, "taunt", 0), SOLO) == [], "optional"
    assert "modifier" in model.warnings(model.unbind(Settings(), SOLO, "up", 0), SOLO)[0]
    assert model.warnings(Settings(), ARROWS) == [], "walk is optional"
    pad = model.unbind(Settings(), PAD0, "shield", 0)
    assert model.warnings(pad, PAD0) == [], "the other trigger still shields"
    assert model.warnings(model.unbind(pad, PAD0, "shield", 0), PAD0) == ["NOT BOUND: SHIELD"]
    smash = model.step_right_stick(Settings(), PAD0, 1)
    assert smash.pad(0).right_stick == STICK_SMASH
    assert "MODIFIER" in model.warnings(smash, PAD0)[0], "nothing gives up and down any more"
    assert model.warnings(Settings().with_pad(0, MODIFIER_BUMPERS), PAD0) == []
    assert model.is_missing(Settings(), SOLO, "attack") is False
    assert model.is_missing(Settings(), PAD0, "taunt") is False, "never for an optional action"


def test_the_live_test_lights_the_caps_of_held_controls() -> None:
    settings = Settings().with_key("solo", "jump", "W", slot=1)
    assert model.lit(settings, SOLO, []) == set()
    assert model.lit(settings, SOLO, ["J", "W"]) == {("attack", 0), ("jump", 1)}
    assert model.lit(settings, SOLO, ["SPACE", "Q", ""]) == {("jump", 0)}
    assert model.lit(settings, SOLO, ["ESCAPE"]) == {(model.FIXED_PAUSE, 0)}
    assert model.lit(settings, PAD0, ["x", "y", "lefttrigger"]) == {
        ("jump", 0), ("jump", 1), ("shield", 0),
    }  # fmt: skip
    assert model.lit(settings, PAD0, ["start", "dpup"]) == {(model.FIXED_PAUSE, 0)}
    assert model.lit(settings, PAD0, ["J"]) == set()


def test_layouts_are_shortcuts_and_editing_makes_custom() -> None:
    settings = Settings()
    assert model.layout_name(settings.pad(0)) == "Right-stick modifiers"
    bumpers = model.step_layout(settings, PAD0, 1)
    assert bumpers.pad(0) == MODIFIER_BUMPERS and bumpers.pad(1) == PadBindings()
    assert model.step_layout(bumpers, PAD0, 1).pad(0) == RIGHT_STICK_MODIFIERS, "it wraps"
    assert model.step_layout(settings, PAD0, -1).pad(0) == MODIFIER_BUMPERS
    custom = model.bind(bumpers, PAD0, "taunt", 0, "dpup")
    assert model.layout_name(custom.pad(0)) == "Custom"
    assert model.step_layout(custom, PAD0, 1).pad(0) == RIGHT_STICK_MODIFIERS
    assert model.step_layout(custom, PAD0, -1).pad(0) == MODIFIER_BUMPERS
    assert model.layout_name(model.step_right_stick(settings, PAD0, 1).pad(0)) == "Custom"
    assert model.step_right_stick(model.step_right_stick(settings, PAD0, 1), PAD0, 1) == settings
    assert set(model.STICK_MODE_NAMES) == {"modifiers", "smash"}


def test_the_deadzone_steps_and_stops_at_the_ends() -> None:
    settings = Settings()
    assert model.step_deadzone(settings, 1).deadzone == 0.25
    assert model.step_deadzone(settings, -1).deadzone == 0.15
    low = settings
    for _ in range(10):
        low = model.step_deadzone(low, -1)
    assert (
        low.deadzone == 0.10
        and model.step_deadzone(replace(settings, deadzone=0.35), 1).deadzone == 0.35
    )


# --- menus on a gamepad ----------------------------------------------------------------------


def test_a_pads_own_buttons_always_run_the_menus() -> None:
    assert pad_actions(PadState()) == frozenset()
    assert pad_actions(PadState(a=True)) == {MenuAction.CONFIRM}
    assert pad_actions(PadState(b=True)) == {MenuAction.BACK}
    assert pad_actions(PadState(dpad_up=True, dpad_right=True)) == {MenuAction.UP, MenuAction.RIGHT}
    assert pad_actions(PadState(dpad_down=True, dpad_left=True)) == {
        MenuAction.DOWN,
        MenuAction.LEFT,
    }
    assert pad_actions(PadState(start=True)) == {MenuAction.CONFIRM}
    assert pad_actions(PadState(start=True), start_confirms=False) == frozenset()
    assert pad_actions(PadState(x=True, y=True, left_shoulder=True)) == frozenset()


def test_menu_input_fires_extras_once_per_press_even_with_nothing_bound() -> None:
    unbound = PadBindings(attack=(), special=())
    menu = MenuInput()
    neutral = gamepad_frame(PadState(), unbound)
    menu.update([neutral], [frozenset()])
    held = gamepad_frame(PadState(a=True), unbound)
    assert held.held == 0, "A does nothing in the game on this pad"
    assert menu.update([held], [pad_actions(PadState(a=True))]) == [{MenuAction.CONFIRM}]
    assert menu.update([held], [pad_actions(PadState(a=True))]) == [frozenset()], "once"
    assert menu.update([neutral], [frozenset()]) == [frozenset()]
    assert menu.update([neutral], [pad_actions(PadState(b=True))]) == [{MenuAction.BACK}]
    menu.update([neutral], [frozenset()])
    swapped = PadBindings(attack=("b",), special=("a",))
    b_held = gamepad_frame(PadState(b=True), swapped)
    assert b_held.held == Button.ATTACK, "B attacks on this pad"
    assert menu.update([b_held], [pad_actions(PadState(b=True))]) == [{MenuAction.BACK}], (
        "but in a menu B only goes back: its binding is not also a confirm"
    )
    menu.update([neutral], [frozenset()])
    grab = gamepad_frame(PadState(right_shoulder=True), swapped)
    assert menu.update([grab], [frozenset()]) == [{MenuAction.EXTRA}], "other actions still bind"
    keyboard = MenuInput()
    keyboard.update([neutral], [None])
    assert keyboard.update([b_held], [None]) == [{MenuAction.CONFIRM}], "a keyboard uses bindings"
    fresh = MenuInput()
    assert fresh.update([neutral], [pad_actions(PadState(a=True))]) == [frozenset()]
    assert fresh.update([neutral], [pad_actions(PadState(a=True))]) == [frozenset()], (
        "what is held when a menu opens is ignored until released"
    )
    assert MenuInput().update([neutral]) == [frozenset()], "extras are optional"


# --- consumers -----------------------------------------------------------------------------


def test_the_battle_help_follows_the_bindings() -> None:
    lines = battle_help(device_labels(Settings(), SOLO))
    assert lines == [
        "WASD move  SPACE jump  I/, up/down  J attack  K special  U smash  L grab  LSHIFT shield",
        "AIR  J + direction  I up  , down  SPACE+J = short hop aerial",
    ], "with the default keys it reads as it always did"
    rebound = Settings().with_key("solo", "attack", "F").with_key("solo", "jump", "V")
    changed = battle_help(device_labels(rebound, SOLO))
    assert "F attack" in changed[0] and "V jump" in changed[0] and "V+F" in changed[1]
    pad = battle_help(device_labels(Settings(), PAD0))
    assert pad[0].startswith("LS move  X/Y jump  RS up/RS down up/down  A attack")


def test_labels_follow_custom_gamepad_bindings() -> None:
    custom = PadBindings().with_control("taunt", "dpup").with_control("attack", "y")
    labels = gamepad_labels(custom)
    assert labels["taunt"] == "D-UP" and labels["attack"] == "Y" and labels["jump"] == "X"
    with_button = gamepad_labels(PadBindings().with_control("up", "dpleft"))
    assert with_button["up"] == "RS up/D-LEFT" and with_button["down"] == "RS down"
    assert device_labels(Settings().with_pad(2, custom), PAD2)["taunt"] == "D-UP"
    assert device_labels(Settings().with_pad(2, custom), PAD0)["attack"] == "A"
    assert device_labels(Settings(), "pad:nonsense")["attack"] == "attack"


# --- the controller diagram ----------------------------------------------------------------


def test_the_diagram_draws_every_bindable_control_in_its_own_place() -> None:
    assert set(pad_art.CONTROLS) == set(PAD_CONTROLS) | {"start"}
    boxes = {control: pad_art.control_box(control) for control in pad_art.CONTROLS}
    width, height = pad_art.PAD_ART_SIZE
    for control, (left, top, right, bottom) in boxes.items():
        assert 0 <= left < right < width and 0 <= top < bottom < height, control
    for (first, a), (second, b) in itertools.combinations(boxes.items(), 2):
        apart = a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]
        assert apart, f"{first} and {second} overlap"
    with pytest.raises(KeyError):
        pad_art.control_box("nonsense")


def test_the_diagram_lights_held_controls_and_marks_bound_ones() -> None:
    palette = set(theme.PALETTE)
    idle = pad_art.build_pad()
    assert idle.size == pad_art.PAD_ART_SIZE
    assert {pixel[:3] for pixel in idle.getdata() if pixel[3]} <= palette

    def middle(image: object, control: str) -> tuple[int, int, int]:
        left, top, right, bottom = pad_art.control_box(control)
        return image.getpixel(((left + right) // 2 + 1, (top + bottom) // 2 + 1))[:3]  # type: ignore[attr-defined]

    for control in ("a", "lefttrigger", "dpup", "rightshoulder", "start"):
        assert middle(idle, control) == pad_art.IDLE
        lit = pad_art.build_pad(frozenset({control}))
        assert middle(lit, control) == pad_art.LIT, control
        marked = pad_art.build_pad(frozenset(), frozenset({control}))
        assert middle(marked, control) == pad_art.MARKED, control
        both = pad_art.build_pad(frozenset({control}), frozenset({control}))
        assert middle(both, control) == pad_art.LIT, "held wins over marked"
        assert middle(lit, "b" if control != "b" else "x") == pad_art.IDLE
    assert pad_art.control_color("x", frozenset(), frozenset()) == pad_art.IDLE
    assert set(PAD_ACTIONS) >= {"attack", "taunt", "walk"}
