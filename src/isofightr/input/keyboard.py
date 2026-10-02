"""Keyboard to ``InputFrame``: bindings as data, and the mapping as a pure function.

Plan note "08 - Controls and Input" ("Default bindings", "Screen-relative movement"). Digital
movement is always full magnitude, and a fresh direction press is a flick (so it dashes);
holding the ``walk`` key walks instead. Key codes are plain integers here; the presets with
real key symbols live in :mod:`isofightr.input.presets`.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Set
from dataclasses import dataclass

from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    VERTICAL_NONE,
    VERTICAL_UP,
    Button,
    InputFrame,
    stick_to_world,
)


@dataclass(frozen=True, slots=True)
class KeyboardBindings:
    """Which key does what for one player. All values are key codes."""

    name: str
    move_up: int
    move_down: int
    move_left: int
    move_right: int
    up: int
    """The "up" vertical modifier (up tilt, up special...)."""
    down: int
    """The "down" vertical modifier (fast fall, platform drop...)."""
    buttons: tuple[tuple[int, Button], ...]
    """Key code and the button it holds, for every bound button."""

    def keys(self) -> list[int]:
        """Return every key code this binding uses."""
        movement = [self.move_up, self.move_down, self.move_left, self.move_right]
        return [*movement, self.up, self.down, *(key for key, _ in self.buttons)]


def keyboard_frame(bindings: KeyboardBindings, held_keys: Set[int]) -> InputFrame:
    """Return the ``InputFrame`` for the keys currently held.

    Opposite directions cancel. Diagonals are normalized, so they are not faster.
    """
    stick_u = float(bindings.move_right in held_keys) - float(bindings.move_left in held_keys)
    stick_v = float(bindings.move_up in held_keys) - float(bindings.move_down in held_keys)
    move = stick_to_world(stick_u, stick_v).normalized()

    up, down = bindings.up in held_keys, bindings.down in held_keys
    vertical = VERTICAL_NONE if up == down else (VERTICAL_UP if up else VERTICAL_DOWN)

    held = 0
    for key, button in bindings.buttons:
        if key in held_keys:
            held |= button
    return InputFrame(move=move, vertical=vertical, held=held)
