"""Tests for device polling with stand-in controllers (``pytest -m gl``).

``isofightr.input.devices`` imports arcade for key codes and pyglet for controllers, so these
need a window even though no real gamepad is involved. The stand-in mimics the parts of
pyglet's ``Controller`` that the reader uses.
"""

from collections.abc import Callable
from typing import Any

import pytest

from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8

pytestmark = pytest.mark.gl


class FakeController:
    """Looks like a ``pyglet.input.Controller``: pollable buttons, stick events."""

    def __init__(self, name: str = "Fake Pad") -> None:
        self.name = name
        self.a = self.b = self.x = self.y = False
        self.leftshoulder = self.rightshoulder = False
        self.lefttrigger = self.righttrigger = 0.0
        self.opened = False
        self.handlers: dict[str, Callable[..., None]] = {}

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def push_handlers(self, **handlers: Callable[..., None]) -> None:
        self.handlers.update(handlers)

    def remove_handlers(self, **handlers: Callable[..., None]) -> None:
        for name in handlers:
            self.handlers.pop(name, None)

    def move_stick(self, stick: str, x: float, y: float) -> None:
        from pyglet.math import Vec2

        self.handlers["on_stick_motion"](self, stick, Vec2(x, y))


def test_pad_reader_tracks_sticks_buttons_and_triggers(window: Any) -> None:
    from isofightr.input.devices import PadReader

    pad = FakeController()
    reader = PadReader(pad)  # type: ignore[arg-type]
    assert pad.opened and "on_stick_motion" in pad.handlers
    pad.move_stick("leftstick", 0.5, -1.0)
    pad.move_stick("rightstick", 0.0, 1.0)
    pad.a, pad.rightshoulder, pad.lefttrigger = True, True, 0.75
    state = reader.state()
    assert (state.left_x, state.left_y, state.right_y) == (0.5, -1.0, 1.0)
    assert (state.a, state.b, state.right_shoulder, state.left_trigger) == (True, False, True, 0.75)
    reader.close()
    assert not pad.opened and pad.handlers == {}


def test_controllers_are_given_to_players_in_order_and_can_be_unplugged(window: Any) -> None:
    from isofightr.input.devices import InputSource

    source = InputSource(player_count=2)
    for pad in source.pads:  # ignore any real controller plugged into this machine
        if pad is not None:
            source._disconnect(pad.controller)
    first, second, third = FakeController("One"), FakeController("Two"), FakeController("Three")
    source._connect(first)  # type: ignore[arg-type]
    source._connect(second)  # type: ignore[arg-type]
    source._connect(third)  # type: ignore[arg-type]
    assert [pad.controller for pad in source.pads if pad] == [first, second]
    assert not third.opened, "a third controller has no player to drive in a two-player match"
    assert source.describe() == [
        "Keyboard (one player) + One",
        "Keyboard (arrows and numpad) + Two",
    ]

    source._disconnect(first)  # type: ignore[arg-type]
    assert source.pads[0] is None and not first.opened
    source._connect(third)  # type: ignore[arg-type]
    assert source.pads[0] is not None and source.pads[0].controller is third
    source.close()
    assert source.pads == [None, None] and not second.opened


def test_keyboard_and_controller_both_drive_the_same_player(window: Any) -> None:
    import arcade

    from isofightr.input.devices import InputSource

    source = InputSource(player_count=2)
    for pad in source.pads:
        if pad is not None:
            source._disconnect(pad.controller)
    assert source.poll(set()) == [NEUTRAL_INPUT, NEUTRAL_INPUT]

    keys = {arcade.key.D, arcade.key.SPACE, arcade.key.UP, arcade.key.NUM_0}
    first, second = source.poll(keys)
    assert first.move.dot(Dir8.E.world) == pytest.approx(1.0) and first.held == Button.JUMP
    assert second.move.dot(Dir8.N.world) == pytest.approx(1.0) and second.held == Button.JUMP

    pad = FakeController()
    source._connect(pad)  # type: ignore[arg-type]
    pad.move_stick("leftstick", -1.0, 0.0)
    pad.a = True
    first, second = source.poll({arcade.key.SPACE})
    assert first.move.dot(Dir8.W.world) == pytest.approx(1.0)
    assert first.held == Button.JUMP | Button.ATTACK
    assert second == NEUTRAL_INPUT
    source.close()


def test_four_players_only_the_first_two_have_keyboards(window: Any) -> None:
    from isofightr.input.devices import InputSource

    source = InputSource(player_count=4)
    described = source.describe()
    assert described[0].startswith("Keyboard (one player)")
    assert described[1].startswith("Keyboard (arrows and numpad)")
    assert len(described) == 4
    source.close()
