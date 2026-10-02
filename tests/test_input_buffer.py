"""Unit tests for InputFrame and InputBuffer (plan notes 07 "Input buffer" and 08)."""

import copy

import pytest

from isofightr.sim.constants import BUFFER_FRAMES, FLICK_FRAMES
from isofightr.sim.input_frame import (
    NEUTRAL_INPUT,
    Button,
    Dir8,
    InputBuffer,
    InputFrame,
    Press,
)
from isofightr.sim.math3d import Vec2

RIGHT = Dir8.E.world
LEFT = Dir8.W.world


def feed(buffer: InputBuffer, *frames: InputFrame) -> None:
    for frame in frames:
        buffer.push(frame)


def stick(direction: Vec2, magnitude: float = 1.0) -> InputFrame:
    return InputFrame(move=direction * magnitude)


# --- InputFrame ---------------------------------------------------------------------------


def test_neutral_frame() -> None:
    assert InputFrame() == NEUTRAL_INPUT
    assert (NEUTRAL_INPUT.move, NEUTRAL_INPUT.vertical, NEUTRAL_INPUT.held) == (Vec2(), 0, 0)
    assert NEUTRAL_INPUT.cstick is None


def test_frames_are_immutable_hashable_values() -> None:
    frame = InputFrame(move=Vec2(1.0, 0.0), held=Button.JUMP)
    assert frame == InputFrame(move=Vec2(1.0, 0.0), held=Button.JUMP)
    assert len({frame, InputFrame(move=Vec2(1.0, 0.0), held=Button.JUMP)}) == 1
    with pytest.raises(AttributeError):
        frame.held = 0  # type: ignore[misc]


def test_invalid_frames_are_rejected() -> None:
    with pytest.raises(ValueError, match="move magnitude"):
        InputFrame(move=Vec2(1.0, 1.0))
    with pytest.raises(ValueError, match="vertical"):
        InputFrame(vertical=2)
    InputFrame(move=Dir8.N.world)  # a unit diagonal is fine despite float rounding


def test_buttons_are_distinct_bits() -> None:
    values = [button.value for button in Button]
    assert len(values) == 8
    assert sum(values) == (1 << 8) - 1


# --- edges and holding --------------------------------------------------------------------


def test_press_and_release_edges_last_one_frame() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.JUMP))
    assert buffer.pressed == Button.JUMP and buffer.released == 0
    assert buffer.holds(Button.JUMP)
    buffer.push(InputFrame(held=Button.JUMP))
    assert buffer.pressed == 0 and buffer.released == 0
    assert buffer.holds(Button.JUMP)
    buffer.push(NEUTRAL_INPUT)
    assert buffer.pressed == 0 and buffer.released == Button.JUMP
    assert not buffer.holds(Button.JUMP)


def test_several_buttons_at_once() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.JUMP | Button.ATTACK))
    assert buffer.pressed == Button.JUMP | Button.ATTACK
    buffer.push(InputFrame(held=Button.ATTACK | Button.SHIELD))
    assert buffer.pressed == Button.SHIELD
    assert buffer.released == Button.JUMP


# --- the press buffer ---------------------------------------------------------------------


def test_a_press_is_buffered_for_six_frames_counting_its_own() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.JUMP))
    for _ in range(BUFFER_FRAMES):
        assert buffer.has(Press.JUMP)
        buffer.push(NEUTRAL_INPUT)
    assert not buffer.has(Press.JUMP)


def test_consuming_a_press_uses_it_up() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.JUMP))
    assert buffer.consume(Press.JUMP)
    assert not buffer.has(Press.JUMP)
    assert not buffer.consume(Press.JUMP)


def test_holding_does_not_refill_the_buffer() -> None:
    buffer = InputBuffer()
    feed(buffer, *[InputFrame(held=Button.JUMP)] * (BUFFER_FRAMES + 2))
    assert buffer.holds(Button.JUMP)
    assert not buffer.has(Press.JUMP)


def test_a_new_press_restarts_the_window() -> None:
    buffer = InputBuffer()
    jump = InputFrame(held=Button.JUMP)
    feed(buffer, jump, NEUTRAL_INPUT, NEUTRAL_INPUT, NEUTRAL_INPUT, jump)
    for _ in range(BUFFER_FRAMES):
        assert buffer.has(Press.JUMP)
        buffer.push(NEUTRAL_INPUT)
    assert not buffer.has(Press.JUMP)


def test_presses_are_buffered_independently() -> None:
    buffer = InputBuffer()
    feed(buffer, InputFrame(held=Button.ATTACK), InputFrame(held=Button.JUMP))
    assert buffer.consume(Press.JUMP)
    assert buffer.has(Press.ATTACK)


def test_walk_is_a_hold_only_modifier() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.WALK))
    assert buffer.holds(Button.WALK)
    assert not any(buffer.has(press) for press in Press)


def test_vertical_taps_are_buffered_like_presses() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(vertical=-1))
    assert buffer.has(Press.DOWN) and not buffer.has(Press.UP)
    assert buffer.vertical == -1
    feed(buffer, *[InputFrame(vertical=-1)] * BUFFER_FRAMES)
    assert not buffer.has(Press.DOWN), "holding down is not a fresh tap"
    buffer.push(InputFrame(vertical=1))
    assert buffer.has(Press.UP)


def test_clear_forgets_buffered_presses() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.JUMP, vertical=-1, move=RIGHT))
    buffer.clear()
    assert not any(buffer.has(press) for press in Press)
    assert buffer.holds(Button.JUMP), "what is held is still held"


# --- flicks -------------------------------------------------------------------------------


def test_digital_direction_press_is_a_flick() -> None:
    buffer = InputBuffer()
    buffer.push(stick(RIGHT))
    assert buffer.has(Press.FLICK)
    assert buffer.stick_active


def test_holding_a_direction_flicks_only_once() -> None:
    buffer = InputBuffer()
    buffer.push(stick(RIGHT))
    assert buffer.consume(Press.FLICK)
    feed(buffer, *[stick(RIGHT)] * 10)
    assert not buffer.has(Press.FLICK)


def test_slow_analog_push_is_not_a_flick() -> None:
    buffer = InputBuffer()
    for magnitude in (0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0):
        buffer.push(stick(RIGHT, magnitude))
    assert not buffer.has(Press.FLICK)


def test_fast_analog_push_within_three_frames_is_a_flick() -> None:
    assert FLICK_FRAMES == 3
    buffer = InputBuffer()
    feed(buffer, stick(RIGHT, 0.1), stick(RIGHT, 0.5), stick(RIGHT, 0.7), stick(RIGHT, 0.95))
    assert buffer.has(Press.FLICK)
    slow = InputBuffer()
    feed(slow, stick(RIGHT, 0.1), *[stick(RIGHT, 0.5)] * 3, stick(RIGHT, 0.95))
    assert not slow.has(Press.FLICK)


def test_partial_tilt_never_flicks() -> None:
    buffer = InputBuffer()
    feed(buffer, NEUTRAL_INPUT, stick(RIGHT, 0.6))
    assert not buffer.has(Press.FLICK)


def test_reversing_direction_without_passing_neutral_is_a_flick() -> None:
    """Keyboard dash-dance: one key released and the opposite pressed on the same frame."""
    buffer = InputBuffer()
    feed(buffer, *[stick(RIGHT)] * 5)
    buffer.consume(Press.FLICK)
    buffer.push(stick(LEFT))
    assert buffer.has(Press.FLICK)


def test_rolling_the_stick_around_the_rim_is_not_a_flick() -> None:
    buffer = InputBuffer()
    buffer.push(stick(Dir8.E.world))
    buffer.consume(Press.FLICK)
    for direction in (Dir8.NE, Dir8.N, Dir8.NW, Dir8.W, Dir8.SW):
        feed(buffer, stick(direction.world), stick(direction.world))
    assert not buffer.has(Press.FLICK)


def test_stick_inside_the_neutral_zone_is_not_active() -> None:
    buffer = InputBuffer()
    buffer.push(stick(RIGHT, 0.15))
    assert not buffer.stick_active
    buffer.push(stick(RIGHT, 0.3))
    assert buffer.stick_active


# --- copying ------------------------------------------------------------------------------


def test_buffer_deep_copies_independently() -> None:
    buffer = InputBuffer()
    buffer.push(InputFrame(held=Button.JUMP, move=RIGHT))
    clone = copy.deepcopy(buffer)
    clone.push(NEUTRAL_INPUT)
    clone.consume(Press.JUMP)
    assert buffer.has(Press.JUMP) and buffer.holds(Button.JUMP)
    assert buffer.history != clone.history
