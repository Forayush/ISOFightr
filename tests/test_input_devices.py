"""Unit tests for the pure device mappers: keyboard and gamepad to ``InputFrame``.

Plan note "08 - Controls and Input". Key codes here are arbitrary integers; the real key
presets are checked by a ``gl`` test because importing them imports arcade.
"""

import math

import pytest

from isofightr.config import (
    MODIFIER_THRESHOLD,
    STICK_DEADZONE,
    STICK_SATURATION,
    TRIGGER_THRESHOLD,
)
from isofightr.input.gamepad import (
    MODIFIER_BUMPERS,
    RIGHT_STICK_MODIFIERS,
    PadState,
    gamepad_frame,
    merge_frames,
    process_stick,
)
from isofightr.input.keyboard import KeyboardBindings, KeyLatch, keyboard_frame
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame

UP, DOWN, LEFT, RIGHT, MOD_UP, MOD_DOWN, JUMP, ATTACK, WALK = range(1, 10)
BINDINGS = KeyboardBindings(
    name="test",
    move_up=UP,
    move_down=DOWN,
    move_left=LEFT,
    move_right=RIGHT,
    up=MOD_UP,
    down=MOD_DOWN,
    buttons=((JUMP, Button.JUMP), (ATTACK, Button.ATTACK), (WALK, Button.WALK)),
)


def approx_vec(frame: InputFrame, direction: Dir8, magnitude: float = 1.0) -> None:
    expected = direction.world * magnitude
    assert (frame.move.x, frame.move.y) == pytest.approx((expected.x, expected.y), abs=1e-12)


# --- keyboard -----------------------------------------------------------------------------


def test_a_key_tapped_between_two_ticks_counts_as_held_for_one_tick() -> None:
    latch = KeyLatch()
    latch.press(ATTACK)
    latch.release(ATTACK)
    assert keyboard_frame(BINDINGS, latch.keys()).held == Button.ATTACK
    latch.end_tick()
    assert keyboard_frame(BINDINGS, latch.keys()).held == 0


def test_a_held_key_stays_held_across_ticks_until_released() -> None:
    latch = KeyLatch()
    latch.press(JUMP)
    for _ in range(3):
        assert latch.keys() == {JUMP}
        latch.end_tick()
    latch.release(JUMP)
    assert latch.keys() == set()


def test_no_keys_is_neutral() -> None:
    assert keyboard_frame(BINDINGS, set()) == NEUTRAL_INPUT


@pytest.mark.parametrize(
    ("keys", "direction"),
    [
        ({RIGHT}, Dir8.E),
        ({LEFT}, Dir8.W),
        ({UP}, Dir8.N),
        ({DOWN}, Dir8.S),
        ({UP, RIGHT}, Dir8.NE),
        ({UP, LEFT}, Dir8.NW),
        ({DOWN, LEFT}, Dir8.SW),
        ({DOWN, RIGHT}, Dir8.SE),
    ],
)
def test_keys_move_in_screen_directions_at_full_magnitude(keys: set[int], direction: Dir8) -> None:
    frame = keyboard_frame(BINDINGS, keys)
    approx_vec(frame, direction)
    assert frame.move.length() == pytest.approx(1.0)


def test_opposite_keys_cancel() -> None:
    assert keyboard_frame(BINDINGS, {LEFT, RIGHT}).move.length() == 0.0
    approx_vec(keyboard_frame(BINDINGS, {LEFT, RIGHT, UP}), Dir8.N)


def test_vertical_modifier_keys() -> None:
    assert keyboard_frame(BINDINGS, {MOD_UP}).vertical == 1
    assert keyboard_frame(BINDINGS, {MOD_DOWN}).vertical == -1
    assert keyboard_frame(BINDINGS, {MOD_UP, MOD_DOWN}).vertical == 0


def test_button_keys_set_held_bits() -> None:
    assert keyboard_frame(BINDINGS, {JUMP}).held == Button.JUMP
    assert keyboard_frame(BINDINGS, {JUMP, ATTACK, WALK}).held == (
        Button.JUMP | Button.ATTACK | Button.WALK
    )


def test_unbound_keys_are_ignored() -> None:
    assert keyboard_frame(BINDINGS, {999, 1000}) == NEUTRAL_INPUT


def test_bindings_list_their_keys() -> None:
    assert sorted(BINDINGS.keys()) == list(range(1, 10))


# --- analog stick processing --------------------------------------------------------------


def test_stick_inside_the_deadzone_reads_zero() -> None:
    assert process_stick(0.0, 0.0) == (0.0, 0.0)
    assert process_stick(STICK_DEADZONE, 0.0) == (0.0, 0.0)
    assert process_stick(0.1, 0.1) == (0.0, 0.0)


def test_deadzone_is_radial_not_per_axis() -> None:
    # 0.18 on each axis is under the per-axis threshold but over it as a magnitude (0.25).
    x, y = process_stick(0.18, 0.18)
    assert x == pytest.approx(y) and x > 0.0


def test_stick_rescales_from_deadzone_to_saturation() -> None:
    middle = (STICK_DEADZONE + STICK_SATURATION) / 2
    assert process_stick(middle, 0.0)[0] == pytest.approx(0.5)
    assert process_stick(STICK_SATURATION, 0.0) == (1.0, 0.0)
    assert process_stick(1.0, 0.0) == (1.0, 0.0)
    assert process_stick(0.0, -1.0) == (0.0, -1.0)


def test_stick_keeps_its_direction() -> None:
    x, y = process_stick(0.3, 0.4)
    assert math.atan2(y, x) == pytest.approx(math.atan2(0.4, 0.3))
    assert math.hypot(x, y) == pytest.approx((0.5 - STICK_DEADZONE) / 0.75)


def test_a_fully_pushed_diagonal_never_exceeds_magnitude_one() -> None:
    x, y = process_stick(1.0, 1.0)
    assert math.hypot(x, y) == pytest.approx(1.0)
    gamepad_frame(PadState(left_x=1.0, left_y=1.0))  # InputFrame would reject magnitude > 1


# --- gamepad ------------------------------------------------------------------------------


def test_idle_pad_is_neutral() -> None:
    assert gamepad_frame(PadState()) == NEUTRAL_INPUT


def test_left_stick_moves_screen_relative() -> None:
    approx_vec(gamepad_frame(PadState(left_x=1.0)), Dir8.E)
    approx_vec(gamepad_frame(PadState(left_y=1.0)), Dir8.N)
    approx_vec(gamepad_frame(PadState(left_x=-1.0, left_y=-1.0)), Dir8.SW)


def test_partial_tilt_gives_partial_magnitude() -> None:
    middle = (STICK_DEADZONE + STICK_SATURATION) / 2
    approx_vec(gamepad_frame(PadState(left_x=middle)), Dir8.E, 0.5)


def test_default_preset_buttons() -> None:
    cases = {
        "a": Button.ATTACK,
        "b": Button.SPECIAL,
        "x": Button.JUMP,
        "y": Button.JUMP,
        "right_shoulder": Button.GRAB,
        "left_shoulder": Button.STRONG,
    }
    for field, button in cases.items():
        assert gamepad_frame(PadState(**{field: True})).held == button
    assert gamepad_frame(PadState(a=True, x=True)).held == Button.ATTACK | Button.JUMP


def test_triggers_shield_past_their_threshold() -> None:
    assert gamepad_frame(PadState(left_trigger=TRIGGER_THRESHOLD - 0.01)).held == 0
    assert gamepad_frame(PadState(left_trigger=TRIGGER_THRESHOLD)).held == Button.SHIELD
    assert gamepad_frame(PadState(right_trigger=1.0)).held == Button.SHIELD


def test_right_stick_up_and_down_are_the_vertical_modifiers() -> None:
    assert gamepad_frame(PadState(right_y=1.0)).vertical == 1
    assert gamepad_frame(PadState(right_y=-1.0)).vertical == -1
    assert gamepad_frame(PadState(right_y=MODIFIER_THRESHOLD - 0.01)).vertical == 0
    assert gamepad_frame(PadState(right_y=MODIFIER_THRESHOLD)).vertical == 1


def test_right_stick_vertical_must_dominate() -> None:
    assert gamepad_frame(PadState(right_x=0.9, right_y=0.6)).vertical == 0
    assert gamepad_frame(PadState(right_x=0.5, right_y=0.8)).vertical == 1
    assert gamepad_frame(PadState(right_x=1.0)).vertical == 0


def test_right_stick_does_not_move_the_fighter() -> None:
    assert gamepad_frame(PadState(right_x=1.0, right_y=1.0)).move.length() == 0.0


def test_modifier_bumpers_preset() -> None:
    preset = MODIFIER_BUMPERS
    assert gamepad_frame(PadState(left_shoulder=True), preset).vertical == 1
    assert gamepad_frame(PadState(left_trigger=1.0), preset).vertical == -1
    assert gamepad_frame(PadState(left_shoulder=True, left_trigger=1.0), preset).vertical == 0
    assert gamepad_frame(PadState(right_trigger=1.0), preset).held == Button.SHIELD
    assert gamepad_frame(PadState(left_trigger=1.0), preset).held == 0, "LT is no longer shield"
    assert gamepad_frame(PadState(right_y=1.0), preset).vertical == 0, "the right stick is free"
    assert gamepad_frame(PadState(a=True, x=True), preset).held == Button.ATTACK | Button.JUMP


def test_presets_have_names_for_the_settings_screen() -> None:
    assert RIGHT_STICK_MODIFIERS.name != MODIFIER_BUMPERS.name


# --- merging devices ----------------------------------------------------------------------


def test_merge_takes_the_stick_pushed_further_and_all_buttons() -> None:
    keyboard = InputFrame(move=Dir8.E.world, held=Button.JUMP)
    pad = InputFrame(move=Dir8.N.world * 0.4, held=Button.ATTACK, vertical=1)
    merged = merge_frames(keyboard, pad)
    assert merged.move == Dir8.E.world
    assert merged.held == Button.JUMP | Button.ATTACK
    assert merged.vertical == 1
    assert merge_frames(pad, keyboard) == merged


def test_merge_with_neutral_changes_nothing() -> None:
    frame = InputFrame(move=Dir8.SW.world, held=Button.SHIELD, vertical=-1)
    assert merge_frames(frame, NEUTRAL_INPUT) == frame
    assert merge_frames(NEUTRAL_INPUT, frame) == frame


def test_merge_cancels_opposite_vertical_intents() -> None:
    assert merge_frames(InputFrame(vertical=1), InputFrame(vertical=-1)).vertical == 0
    assert merge_frames(InputFrame(vertical=-1), InputFrame(vertical=-1)).vertical == -1
