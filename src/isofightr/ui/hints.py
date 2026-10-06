"""Control hints: what a device really calls each action, for footers and prompts.

Plan note "13 - Game Modes UI and Flow" (decision D-061): a footer says ``J: pick`` to a
player on the WASD keyboard and ``A: pick`` to one on a gamepad, following their own
bindings. A hint line is a template with action names in braces.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Mapping
from typing import Final

from isofightr.input.gamepad import MODIFIER_BUMPERS, RIGHT_STICK_MODIFIERS, GamepadPreset
from isofightr.settings import PRESET_BUMPERS, PRESET_RIGHT_STICK, Settings
from isofightr.ui.move_list import ACTIONS, UNBOUND, gamepad_labels, keyboard_labels

KEYBOARD_PREFIX: Final[str] = "keyboard:"
"""Device ids of keyboard layouts start with this (as in :mod:`isofightr.input.devices`)."""
PRESETS: Final[Mapping[str, GamepadPreset]] = {
    PRESET_RIGHT_STICK: RIGHT_STICK_MODIFIERS,
    PRESET_BUMPERS: MODIFIER_BUMPERS,
}
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
    elif device:
        return gamepad_labels(PRESETS[settings.gamepad_preset])
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
