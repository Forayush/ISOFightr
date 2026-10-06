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
    """Key code and the button it holds, for every bound button (a button with two keys is
    listed twice)."""
    alternates: tuple[tuple[int, str], ...] = ()
    """Second keys for the directions and modifiers: a key code and the field it also holds
    (``"move_up"``, ``"down"``...). Decision D-061: two keys per action."""

    def keys(self) -> list[int]:
        """Return every key code this binding uses."""
        movement = [self.move_up, self.move_down, self.move_left, self.move_right]
        extra = [key for key, _ in self.alternates]
        return [*movement, self.up, self.down, *(key for key, _ in self.buttons), *extra]

    def holds(self, name: str, held_keys: Set[int]) -> bool:
        """Return whether a direction or modifier (by field name) is held by either key."""
        if getattr(self, name) in held_keys:
            return True
        return any(key in held_keys for key, field_name in self.alternates if field_name == name)


def keyboard_frame(bindings: KeyboardBindings, held_keys: Set[int]) -> InputFrame:
    """Return the ``InputFrame`` for the keys currently held.

    Opposite directions cancel. Diagonals are normalized, so they are not faster.
    """
    held = bindings.holds
    stick_u = float(held("move_right", held_keys)) - float(held("move_left", held_keys))
    stick_v = float(held("move_up", held_keys)) - float(held("move_down", held_keys))
    move = stick_to_world(stick_u, stick_v).normalized()

    up, down = held("up", held_keys), held("down", held_keys)
    vertical = VERTICAL_NONE if up == down else (VERTICAL_UP if up else VERTICAL_DOWN)

    buttons = 0
    for key, button in bindings.buttons:
        if key in held_keys:
            buttons |= button
    return InputFrame(move=move, vertical=vertical, held=buttons)


class KeyLatch:
    """The keys to read this tick: those held now, plus any pressed since the last tick.

    The game polls the keyboard once per 60 Hz tick. A quick tap can go down and up between
    two polls; latching it makes it count as held for one tick, so the press is not lost
    (decision D-053).
    """

    def __init__(self) -> None:
        self.held: set[int] = set()
        self._tapped: set[int] = set()

    def press(self, key: int) -> None:
        """A key went down."""
        self.held.add(key)
        self._tapped.add(key)

    def release(self, key: int) -> None:
        """A key went up."""
        self.held.discard(key)

    def keys(self) -> frozenset[int]:
        """Return the keys this tick sees as held."""
        return frozenset(self.held | self._tapped)

    def end_tick(self) -> None:
        """Forget the taps once this tick has read them."""
        self._tapped.clear()
