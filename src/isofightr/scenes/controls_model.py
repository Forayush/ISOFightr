"""The Controls screen's model: devices, the tiles of each, and what binding does.

Plan note "08 - Controls and Input" (decision D-061): one screen for keyboards and
gamepads. A tab per player edits the device that player uses; the device's actions are
shown as tiles grouped by purpose, each with a primary and a secondary control. Everything
the screen changes goes through the functions here, which return new
:class:`~isofightr.settings.Settings`, so the rules of binding are tested without a window:
a control taken from another action leaves that action without it, Enter and Escape cannot
be bound, and a gamepad's sticks and Start are fixed.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Final

from isofightr.config import MAX_PLAYERS
from isofightr.input.gamepad import (
    LAYOUT_CUSTOM,
    LAYOUT_NAMES,
    PAD_ACTIONS,
    PAD_CONTROLS,
    PAD_LAYOUTS,
    RIGHT_STICK_MODES,
    STICK_MODIFIERS,
    PadBindings,
)
from isofightr.settings import (
    DEADZONES,
    KEYBOARD_ACTIONS,
    KEYBOARD_ARROWS,
    KEYBOARD_SOLO,
    RESERVED_KEYS,
    Settings,
)
from isofightr.ui.move_list import KEY_LABELS, PAD_LABELS

KEYBOARD_PREFIX: Final[str] = "keyboard:"
PAD_PREFIX: Final[str] = "pad:"
DEVICES: Final[tuple[str, ...]] = (
    KEYBOARD_PREFIX + KEYBOARD_SOLO,
    KEYBOARD_PREFIX + KEYBOARD_ARROWS,
    *(f"{PAD_PREFIX}{slot}" for slot in range(MAX_PLAYERS)),
)
"""Every device the screen can edit, in the order the device chooser steps through them."""
TAB_DEVICES: Final[tuple[str, ...]] = (DEVICES[0], DEVICES[1], DEVICES[2], DEVICES[3])
"""The device a player's tab shows when that player has not used one yet."""
DEVICE_NAMES: Final[dict[str, str]] = {
    DEVICES[0]: "Keyboard (WASD)",
    DEVICES[1]: "Keyboard (arrows)",
    **{f"{PAD_PREFIX}{slot}": f"Gamepad {slot + 1}" for slot in range(MAX_PLAYERS)},
}
UNBOUND: Final[str] = "n/a"
"""What a tile with no control shows."""
RIGHT_STICK_LABEL: Final[str] = "R-STICK"
"""What a gamepad tile shows when no button is bound but the right stick does the job."""
ESSENTIAL: Final[tuple[str, ...]] = ("attack", "special", "jump", "shield")
"""Actions a player cannot do without (besides moving)."""
MOVES: Final[tuple[str, ...]] = ("move_up", "move_down", "move_left", "move_right")
STICK_MODE_NAMES: Final[dict[str, str]] = {
    STICK_MODIFIERS: "Up / down modifiers",
    RIGHT_STICK_MODES[1]: "Smash stick",
}
ACTION_NAMES: Final[dict[str, str]] = {
    "move_up": "UP",
    "move_down": "DOWN",
    "move_left": "LEFT",
    "move_right": "RIGHT",
    "up": "UP MOD",
    "down": "DOWN MOD",
    "attack": "ATTACK",
    "special": "SPECIAL",
    "strong": "STRONG",
    "grab": "GRAB",
    "jump": "JUMP",
    "shield": "SHIELD",
    "walk": "WALK",
    "taunt": "TAUNT",
}
FIXED_STICK, FIXED_PAUSE = "stick", "pause"
"""Tiles that only show what a control does: they cannot be rebound."""
_SHORT_KEYS: Final[dict[str, str]] = {
    "LSHIFT": "L-SHIFT",
    "RSHIFT": "R-SHIFT",
    "LCTRL": "L-CTRL",
    "RCTRL": "R-CTRL",
    "LALT": "L-ALT",
    "RALT": "R-ALT",
    "BACKSPACE": "BKSP",
    "CAPSLOCK": "CAPS",
    "PAGEUP": "PG UP",
    "PAGEDOWN": "PG DN",
}


@dataclass(frozen=True, slots=True)
class Tile:
    """One action's place on the screen."""

    action: str
    """The action, or :data:`FIXED_STICK` / :data:`FIXED_PAUSE` for a tile that is fixed."""
    label: str
    column: int
    """Column inside its group, from the left."""
    row: int
    """Row inside its group, from the top."""

    @property
    def fixed(self) -> bool:
        """Whether the tile only informs."""
        return self.action in (FIXED_STICK, FIXED_PAUSE)


@dataclass(frozen=True, slots=True)
class Group:
    """Tiles that belong together, with a heading."""

    title: str
    column: int
    """Which of the screen's three columns the group is in."""
    band: int
    """0 for the upper band of groups, 1 for the lower."""
    tiles: tuple[Tile, ...]


def _tile(action: str, column: int, row: int = 0) -> Tile:
    return Tile(action, ACTION_NAMES[action], column, row)


_ATTACKS: Final[Group] = Group(
    "ATTACKS",
    1,
    0,
    (_tile("attack", 0), _tile("special", 1), _tile("strong", 0, 1), _tile("grab", 1, 1)),
)
_MOVEMENT: Final[Group] = Group(
    "MOVEMENT", 1, 1, (_tile("jump", 0), _tile("shield", 1), _tile("walk", 2))
)
_MODIFIERS: Final[Group] = Group("VERTICAL MODIFIERS", 0, 1, (_tile("up", 0), _tile("down", 1)))
KEYBOARD_GROUPS: Final[tuple[Group, ...]] = (
    Group(
        "MOVE (screen-relative)",
        0,
        0,
        (
            _tile("move_up", 1),
            _tile("move_left", 0, 1),
            _tile("move_down", 1, 1),
            _tile("move_right", 2, 1),
        ),
    ),
    _ATTACKS,
    Group("OTHER", 2, 0, (_tile("taunt", 0), Tile(FIXED_PAUSE, "PAUSE", 1, 0))),
    _MODIFIERS,
    _MOVEMENT,
)
PAD_GROUPS: Final[tuple[Group, ...]] = (
    Group("MOVE", 0, 0, (Tile(FIXED_STICK, "MOVE", 0, 0),)),
    _ATTACKS,
    Group("OTHER", 2, 0, (_tile("taunt", 0), Tile(FIXED_PAUSE, "PAUSE", 1, 0))),
    _MODIFIERS,
    _MOVEMENT,
)
FIXED_LABELS: Final[dict[tuple[bool, str], str]] = {
    (False, FIXED_PAUSE): "ESC",
    (True, FIXED_PAUSE): "START",
    (True, FIXED_STICK): "L-STICK",
}


def is_pad(device: str) -> bool:
    """Return whether a device id names a gamepad slot."""
    return device.startswith(PAD_PREFIX)


def pad_slot(device: str) -> int:
    """Return a gamepad device's slot number."""
    return int(device[len(PAD_PREFIX) :])


def layout_of(device: str) -> str:
    """Return a keyboard device's layout name."""
    return device[len(KEYBOARD_PREFIX) :]


def groups(device: str) -> tuple[Group, ...]:
    """Return the tile groups of a device."""
    return PAD_GROUPS if is_pad(device) else KEYBOARD_GROUPS


def actions(device: str) -> tuple[str, ...]:
    """Return the actions a device can bind."""
    return PAD_ACTIONS if is_pad(device) else KEYBOARD_ACTIONS


def tab_device(settings: Settings, tab: int) -> str:
    """Return the device a player's tab edits: the one that player last used, or a likely
    one for a player who has not joined yet."""
    remembered = settings.slot_devices[tab] if tab < len(settings.slot_devices) else ""
    return remembered if remembered in DEVICES else TAB_DEVICES[tab % len(TAB_DEVICES)]


def with_tab_device(settings: Settings, tab: int, step: int) -> Settings:
    """Return the settings with a player's device stepped along :data:`DEVICES`. It becomes
    the device that player joins with."""
    current = DEVICES.index(tab_device(settings, tab))
    slots = list(settings.slot_devices)
    slots += [""] * (tab + 1 - len(slots))
    slots[tab] = DEVICES[(current + step) % len(DEVICES)]
    return replace(settings, slot_devices=tuple(slots))


def bound(settings: Settings, device: str, action: str) -> tuple[str, ...]:
    """Return the names of the controls an action has on a device: none, one or two."""
    if is_pad(device):
        return settings.pad(pad_slot(device)).controls(action)
    return settings.bound_keys(layout_of(device), action)


def control_label(name: str, pad: bool) -> str:
    """Return a control's name as a key cap shows it."""
    if not name:
        return UNBOUND
    if pad:
        return PAD_LABELS.get(name, name.upper())
    return KEY_LABELS.get(name) or _SHORT_KEYS.get(name) or name.replace("_", " ")


def tile_label(settings: Settings, device: str, action: str, slot: int) -> str:
    """Return what a tile's cap shows for one of an action's two controls: the control, or
    ``n/a`` for a primary that is not bound, or nothing for an empty secondary."""
    fixed = FIXED_LABELS.get((is_pad(device), action))
    if fixed is not None:
        return fixed if slot == 0 else ""
    names = bound(settings, device, action)
    if slot < len(names):
        return control_label(names[slot], is_pad(device))
    if slot == 0 and stick_covers(settings, device, action):
        return RIGHT_STICK_LABEL
    return UNBOUND if slot == 0 else ""


def stick_covers(settings: Settings, device: str, action: str) -> bool:
    """Return whether an action needs no button because the gamepad's right stick does it:
    the up and down modifiers in "modifiers" mode, and smash attacks (strong) always."""
    if not is_pad(device):
        return False
    pad = settings.pad(pad_slot(device))
    return action == "strong" or (action in ("up", "down") and pad.right_stick_modifiers)


def is_missing(settings: Settings, device: str, action: str) -> bool:
    """Return whether an action a player cannot do without has no control at all."""
    needed = ESSENTIAL if is_pad(device) else (*MOVES, *ESSENTIAL)
    return action in needed and not bound(settings, device, action)


def can_bind(device: str, control: str) -> bool:
    """Return whether a control may be bound on a device. Enter and Escape run the menus,
    Backspace quits a match that cannot be paused;
    a gamepad's Start pauses."""
    if is_pad(device):
        return control in PAD_CONTROLS
    return bool(control) and control not in RESERVED_KEYS


def bind(settings: Settings, device: str, action: str, slot: int, control: str) -> Settings:
    """Return the settings with a control put on an action's primary (0) or secondary (1)
    slot. Whatever had the control loses it. A control that cannot be bound changes
    nothing."""
    if not can_bind(device, control) or action not in actions(device):
        return settings
    if is_pad(device):
        index = pad_slot(device)
        return settings.with_pad(index, settings.pad(index).with_control(action, control, slot))
    return settings.with_key(layout_of(device), action, control, slot)


def unbind(settings: Settings, device: str, action: str, slot: int) -> Settings:
    """Return the settings with one of an action's controls removed."""
    if action not in actions(device):
        return settings
    if is_pad(device):
        index = pad_slot(device)
        return settings.with_pad(index, settings.pad(index).without(action, slot))
    return settings.without_key(layout_of(device), action, slot)


def with_defaults(settings: Settings, device: str) -> Settings:
    """Return the settings with one device back on its default controls (only that one)."""
    if is_pad(device):
        return settings.with_pad(pad_slot(device), PadBindings())
    return settings.with_default_keys(layout_of(device))


def owner(settings: Settings, device: str, control: str) -> str | None:
    """Return the action a control is bound to on a device, or ``None``."""
    for action in actions(device):
        if control in bound(settings, device, action):
            return action
    return None


def warnings(settings: Settings, device: str) -> list[str]:
    """Return a line for each thing a player cannot do with a device's bindings: an
    essential action, or a direction, that has no control."""
    needed: Iterable[str] = ESSENTIAL if is_pad(device) else (*MOVES, *ESSENTIAL)
    missing = [ACTION_NAMES[action] for action in needed if not bound(settings, device, action)]
    lines = []
    if missing:
        lines.append("NOT BOUND: " + ", ".join(missing))
    if is_pad(device):
        pad = settings.pad(pad_slot(device))
        if not pad.right_stick_modifiers and not (pad.up and pad.down):
            lines.append("NO UP / DOWN MODIFIER: bind them, or use the right stick")
    elif not (bound(settings, device, "up") and bound(settings, device, "down")):
        lines.append("NOT BOUND: an up or down modifier (tilts, specials, fast fall)")
    return lines


def lit(settings: Settings, device: str, held: Iterable[str]) -> set[tuple[str, int]]:
    """Return the tiles to light up for the controls held right now (the live test), as
    ``(action, slot)`` pairs. A gamepad's Start lights its PAUSE tile."""
    held = set(held)
    tiles = set()
    for action in actions(device):
        for slot, name in enumerate(bound(settings, device, action)):
            if name in held:
                tiles.add((action, slot))
    if "start" in held or "ESCAPE" in held:
        tiles.add((FIXED_PAUSE, 0))
    return tiles


# --- gamepad options ---------------------------------------------------------------------

LAYOUT_ORDER: Final[tuple[str, ...]] = tuple(PAD_LAYOUTS)


def layout_name(pad: PadBindings) -> str:
    """Return the name of the stock layout a pad's bindings are, or "Custom"."""
    return LAYOUT_NAMES[pad.layout]


def step_layout(settings: Settings, device: str, step: int) -> Settings:
    """Return the settings with a gamepad filled from the next (or previous) stock layout.
    From custom bindings it goes to the first (or last) one: a layout is a shortcut that
    overwrites the whole table."""
    index = pad_slot(device)
    current = settings.pad(index).layout
    if current == LAYOUT_CUSTOM:
        chosen = LAYOUT_ORDER[0 if step > 0 else -1]
    else:
        chosen = LAYOUT_ORDER[(LAYOUT_ORDER.index(current) + step) % len(LAYOUT_ORDER)]
    return settings.with_pad(index, PAD_LAYOUTS[chosen])


def step_right_stick(settings: Settings, device: str, step: int) -> Settings:
    """Return the settings with a gamepad's right stick mode changed."""
    index = pad_slot(device)
    pad = settings.pad(index)
    modes = RIGHT_STICK_MODES
    mode = modes[(modes.index(pad.right_stick) + step) % len(modes)]
    return settings.with_pad(index, replace(pad, right_stick=mode))


def step_deadzone(settings: Settings, step: int) -> Settings:
    """Return the settings with the stick deadzone moved along its steps (it is shared by
    every gamepad)."""
    zones = DEADZONES
    index = zones.index(settings.deadzone) if settings.deadzone in zones else 2
    return replace(settings, deadzone=zones[min(max(index + step, 0), len(zones) - 1)])
