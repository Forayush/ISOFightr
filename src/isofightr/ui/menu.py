"""Menu model and menu input: the pure half of the UI widget kit.

Plan note "13 - Game Modes UI and Flow" ("UI implementation notes": every menu is fully
navigable by every controller plus the keyboard). Menus are driven by the same per-player
``InputFrame``s as the game, turned into press-once menu actions here. Drawing is in
:mod:`isofightr.ui.widgets`.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from isofightr.input.gamepad import PadState
from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    VERTICAL_UP,
    Button,
    InputFrame,
    world_to_stick,
)

STICK_THRESHOLD: Final[float] = 0.5
"""How far the stick must be pushed to count as a menu direction."""
REPEAT_DELAY: Final[int] = 24
"""Ticks a direction must be held before it starts repeating."""
REPEAT_EVERY: Final[int] = 6
CONFIRM_BUTTONS: Final[int] = Button.ATTACK | Button.JUMP
BACK_BUTTONS: Final[int] = Button.SPECIAL | Button.SHIELD
EXTRA_BUTTONS: Final[int] = Button.GRAB
ALT_BUTTONS: Final[int] = Button.STRONG


class MenuAction(Enum):
    """What a player can do in a menu."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    CONFIRM = "confirm"
    BACK = "back"
    EXTRA = "extra"
    """The grab button: a scene's extra action (character select adds a CPU with it)."""
    ALT = "alt"
    """The strong button or the up modifier: a scene's second extra action (character
    select changes costume with it)."""
    ALT_BACK = "alt_back"
    """The down modifier: the same, the other way."""


MENU_SOUNDS: Final[dict[MenuAction, str]] = {
    MenuAction.UP: "ui_move",
    MenuAction.DOWN: "ui_move",
    MenuAction.LEFT: "ui_move",
    MenuAction.RIGHT: "ui_move",
    MenuAction.CONFIRM: "ui_select",
    MenuAction.BACK: "ui_back",
    MenuAction.EXTRA: "ui_pick",
    MenuAction.ALT: "",
    MenuAction.ALT_BACK: "",
}
"""The sound each menu action makes (plan note 14, "UI"); "" for the actions only some
scenes use, which make their own sound when they do something."""

DIRECTIONS: Final[tuple[MenuAction, ...]] = (
    MenuAction.UP,
    MenuAction.DOWN,
    MenuAction.LEFT,
    MenuAction.RIGHT,
)


def held_actions(frame: InputFrame) -> frozenset[MenuAction]:
    """Return the menu actions an input frame is holding (the stick is screen-relative)."""
    actions = set()
    stick_u, stick_v = world_to_stick(frame.move)
    if stick_v > STICK_THRESHOLD:
        actions.add(MenuAction.UP)
    elif stick_v < -STICK_THRESHOLD:
        actions.add(MenuAction.DOWN)
    if stick_u > STICK_THRESHOLD:
        actions.add(MenuAction.RIGHT)
    elif stick_u < -STICK_THRESHOLD:
        actions.add(MenuAction.LEFT)
    if frame.held & CONFIRM_BUTTONS:
        actions.add(MenuAction.CONFIRM)
    if frame.held & BACK_BUTTONS:
        actions.add(MenuAction.BACK)
    if frame.held & EXTRA_BUTTONS:
        actions.add(MenuAction.EXTRA)
    if frame.held & ALT_BUTTONS or frame.vertical == VERTICAL_UP:
        actions.add(MenuAction.ALT)
    elif frame.vertical == VERTICAL_DOWN:
        actions.add(MenuAction.ALT_BACK)
    return frozenset(actions)


def pad_actions(state: PadState, start_confirms: bool = True) -> frozenset[MenuAction]:
    """Return the menu actions a gamepad's own buttons hold, whatever is bound to them
    (decision D-061): A confirms and B goes back, as Enter and Escape do on a keyboard, and
    the d-pad moves. A player who unbinds attack can still use the menus. Start confirms
    too, except where the caller gives it another job (pausing a match)."""
    actions = set()
    if state.a or (start_confirms and state.start):
        actions.add(MenuAction.CONFIRM)
    if state.b:
        actions.add(MenuAction.BACK)
    if state.dpad_up:
        actions.add(MenuAction.UP)
    elif state.dpad_down:
        actions.add(MenuAction.DOWN)
    if state.dpad_left:
        actions.add(MenuAction.LEFT)
    elif state.dpad_right:
        actions.add(MenuAction.RIGHT)
    return frozenset(actions)


PAD_OWN_ACTIONS: Final[frozenset[MenuAction]] = frozenset({MenuAction.CONFIRM, MenuAction.BACK})
"""The actions a gamepad does only with its own A, B and Start, never through a binding."""
HELD_OVER: Final[int] = -1
"""Marks an action that was already held when the menu opened: ignored until released."""


def _no_counts() -> list[dict[MenuAction, int]]:
    return []


@dataclass(slots=True)
class MenuInput:
    """Turns each player's held input into menu actions that fire once per press.

    Directions repeat while held. Anything already held when the menu opens is ignored
    until it is released, so the button that opened a menu does not also act in it.
    """

    held_for: list[dict[MenuAction, int]] = field(default_factory=_no_counts)
    """Per player: how many ticks each held action has been held."""
    primed: bool = False

    def update(
        self,
        frames: Sequence[InputFrame],
        extras: Sequence[frozenset[MenuAction] | None] | None = None,
    ) -> list[frozenset[MenuAction]]:
        """Take this tick's frames (one per player) and return each player's new actions.

        ``extras`` are, for a gamepad, the actions its own buttons hold
        (:func:`pad_actions`), and ``None`` for a keyboard. A gamepad confirms and goes back
        with those buttons **only**: whatever its bindings make of A and B is ignored for
        the two, so a button bound to attack never confirms and goes back at once.
        """
        held = []
        for index, frame in enumerate(frames):
            own = extras[index] if extras is not None else None
            if own is None:
                held.append(held_actions(frame))
            else:
                held.append((held_actions(frame) - PAD_OWN_ACTIONS) | own)
        if not self.primed or len(self.held_for) != len(frames):
            self.primed = True
            self.held_for = [dict.fromkeys(each, HELD_OVER) for each in held]
            return [frozenset()] * len(frames)
        fired: list[frozenset[MenuAction]] = []
        for index in range(len(frames)):
            counts = self.held_for[index]
            now = held[index]
            new = set()
            for action in MenuAction:
                if action not in now:
                    counts.pop(action, None)
                    continue
                ticks = counts.get(action, 0)
                if ticks == HELD_OVER:
                    continue
                ticks += 1
                counts[action] = ticks
                repeats = action in DIRECTIONS and ticks > REPEAT_DELAY
                if ticks == 1 or (repeats and (ticks - REPEAT_DELAY) % REPEAT_EVERY == 1):
                    new.add(action)
            fired.append(frozenset(new))
        return fired

    def reset(self) -> None:
        """Forget everything: the next update ignores whatever is held."""
        self.primed = False


@dataclass(slots=True)
class MenuItem:
    """One row of a menu: an action to pick, or a setting with choices to cycle through."""

    key: str
    label: str
    choices: tuple[str, ...] = ()
    index: int = 0
    """Which choice is selected, for a setting."""

    @property
    def is_setting(self) -> bool:
        """Whether left and right change this row instead of confirm picking it."""
        return bool(self.choices)

    @property
    def value(self) -> str:
        """The selected choice of a setting ("" for an action)."""
        return self.choices[self.index] if self.choices else ""

    @property
    def text(self) -> str:
        """The row as shown."""
        return f"{self.label}: < {self.value} >" if self.choices else self.label


def _no_items() -> list[MenuItem]:
    return []


@dataclass(slots=True)
class Menu:
    """A vertical list of items with a cursor."""

    items: list[MenuItem] = field(default_factory=_no_items)
    cursor: int = 0

    @property
    def selected(self) -> MenuItem:
        """The item under the cursor."""
        return self.items[self.cursor]

    def item(self, key: str) -> MenuItem:
        """Return the item with this key."""
        return next(item for item in self.items if item.key == key)

    def move(self, step: int) -> None:
        """Move the cursor up (-1) or down (+1), wrapping around."""
        self.cursor = (self.cursor + step) % len(self.items)

    def change(self, step: int) -> bool:
        """Cycle the selected setting's choice. Returns whether anything changed."""
        item = self.selected
        if not item.choices:
            return False
        item.index = (item.index + step) % len(item.choices)
        return True

    def apply(self, action: MenuAction) -> str | None:
        """Handle a navigation action. Returns the key of an item that was confirmed.

        Up and down move the cursor; left and right change a setting; confirm picks an
        action item (on a setting it cycles forward).
        """
        if action is MenuAction.UP:
            self.move(-1)
        elif action is MenuAction.DOWN:
            self.move(1)
        elif action is MenuAction.LEFT:
            self.change(-1)
        elif action is MenuAction.RIGHT:
            self.change(1)
        elif action is MenuAction.CONFIRM:
            if self.selected.is_setting:
                self.change(1)
            else:
                return self.selected.key
        return None

    def lines(self) -> list[str]:
        """Return the rows as text, with ``>`` marking the cursor."""
        return [
            ("> " if index == self.cursor else "  ") + item.text
            for index, item in enumerate(self.items)
        ]
