"""Control hints: what a device really calls each action, for footers and prompts.

Plan note "13 - Game Modes UI and Flow" (decision D-061): a footer says ``J: pick`` to a
player on the WASD keyboard and ``A: pick`` to one on a gamepad, following their own
bindings. A hint line is a template with action names in braces.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from isofightr.settings import Settings
from isofightr.ui import font
from isofightr.ui.move_list import ACTIONS, UNBOUND, gamepad_labels, keyboard_labels

KEYBOARD_PREFIX: Final[str] = "keyboard:"
"""Device ids of keyboard layouts start with this (as in :mod:`isofightr.input.devices`)."""
PAD_PREFIX: Final[str] = "pad:"
KEYBOARD_STICK: Final[str] = "arrows"
"""What the move keys are called when they are the arrow keys."""


def device_labels(settings: Settings, device: str) -> dict[str, str]:
    """Return what a device calls each action: its key names, or its gamepad buttons.

    An unknown device (or none) gets the action names themselves, so a hint still reads.
    """
    if device.startswith(KEYBOARD_PREFIX):
        keys = settings.keys.get(device[len(KEYBOARD_PREFIX) :])
        if keys is not None:
            return keyboard_labels(keys)
    elif device.startswith(PAD_PREFIX) and device[len(PAD_PREFIX) :].isdigit():
        return gamepad_labels(settings.pad(int(device[len(PAD_PREFIX) :])))
    return {action: action for action in ACTIONS}


def hint_text(template: str, labels: Mapping[str, str]) -> str:
    """Fill a hint template such as ``"{attack}: pick   {special}: back"`` with a device's
    labels. An action the device has not bound keeps its name, so the hint never shows a
    blank; text outside braces is kept as written."""
    shown = {
        action: (label if label and label != UNBOUND else action)
        for action, label in labels.items()
    }
    for action in ACTIONS:
        shown.setdefault(action, action)
    try:
        return template.format_map(shown)
    except (KeyError, IndexError, ValueError):
        return template


HINT_GAP: Final[str] = "   "
"""What separates the items of a hint line."""


def fit_hint(template: str, labels: Mapping[str, str], width: int, drop: Sequence[str] = ()) -> str:
    """Fill a hint template and make it fit ``width`` pixels (decision D-062): items (parts
    separated by three spaces) are dropped one at a time, in the order ``drop`` names them
    (by a placeholder such as ``strong``, or a word in the item), until the line fits; if it
    still does not, it is shortened with ".."."""
    items = template.split(HINT_GAP)
    for name in ("", *drop):
        if name:
            items = [item for item in items if f"{{{name}}}" not in item and name not in item]
        line = hint_text(HINT_GAP.join(items), labels)
        if font.text_width(line) <= width:
            return line
    return font.fit(line, width)


HELP_TEMPLATES: Final[tuple[str, ...]] = (
    "{stick} move  {jump} jump  {up}/{down} up/down  {attack} attack  {special} special  "
    "{strong} smash  {grab} grab  {shield} shield",
    "AIR  {attack} + direction  {up} up  {down} down  {jump}+{attack} = short hop aerial",
)
"""The in-battle help's control lines, filled in with the first player's own bindings."""


def battle_help(labels: Mapping[str, str]) -> list[str]:
    """Return the in-battle help's control lines for a device's labels, so the help follows
    a rebind (decision D-061)."""
    return [hint_text(template, labels) for template in HELP_TEMPLATES]
