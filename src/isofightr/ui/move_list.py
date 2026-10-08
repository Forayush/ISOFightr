"""The pause menu's move list: every moveset slot of a character and the input that does it.

Plan note "13 - Game Modes UI and Flow" (pause menu, decision D-053). The builder is pure: it
takes the character's moveset and a label for every action (the player's real keys, or the
gamepad buttons of the chosen preset) and returns sections of rows. The battle scene picks
the labels for each player's device and draws the page in two columns.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Final

from isofightr.input.gamepad import PadBindings
from isofightr.settings import canonical_key
from isofightr.sim.character_def import MoveSet

ACTIONS: Final[tuple[str, ...]] = (
    "stick",
    "attack",
    "special",
    "strong",
    "grab",
    "jump",
    "shield",
    "up",
    "down",
    "taunt",
)
"""The actions a label map must name. ``stick`` is whatever moves the fighter."""
UNBOUND: Final[str] = "(unbound)"
KEY_LABELS: Final[Mapping[str, str]] = {
    "COMMA": ",",
    "PERIOD": ".",
    "SLASH": "/",
    "SEMICOLON": ";",
    "APOSTROPHE": "'",
    "BRACKETLEFT": "[",
    "BRACKETRIGHT": "]",
    "BACKSLASH": "\\",
    "MINUS": "-",
    "EQUAL": "=",
}
"""Key names shown as the character printed on the key."""
PAD_LABELS: Final[Mapping[str, str]] = {
    "a": "A",
    "b": "B",
    "x": "X",
    "y": "Y",
    "leftshoulder": "LB",
    "rightshoulder": "RB",
    "lefttrigger": "LT",
    "righttrigger": "RT",
    "leftstick": "L3",
    "rightstick": "R3",
    "dpup": "D-UP",
    "dpdown": "D-DOWN",
    "dpleft": "D-LEFT",
    "dpright": "D-RIGHT",
}
"""Gamepad control names (:data:`~isofightr.input.gamepad.PAD_CONTROLS`) as printed."""
NAME_WIDTH: Final[int] = 15
"""Width of the move-name column in a formatted row."""


@dataclass(frozen=True, slots=True)
class MoveRow:
    """One line of the move list."""

    slot: str
    """The ``[moveset]`` slot it shows, or "" for a row that is not a move (grab, the macro)."""
    name: str
    inputs: str


@dataclass(frozen=True, slots=True)
class MoveSection:
    """A titled group of rows (ground, air, specials, other)."""

    title: str
    rows: tuple[MoveRow, ...]


def key_label(name: str) -> str:
    """Return how a stored key name is shown (``COMMA`` is ``,``; unbound is marked)."""
    if not name:
        return UNBOUND
    return KEY_LABELS.get(name, name)


def keyboard_labels(keys: Mapping[str, str]) -> dict[str, str]:
    """Return the action labels for a keyboard layout, from its key names in the settings."""
    keys = {action: canonical_key(name) for action, name in keys.items()}
    labels = {action: key_label(keys.get(action, "")) for action in ACTIONS if action != "stick"}
    directions = [
        keys.get(name, "") for name in ("move_up", "move_left", "move_down", "move_right")
    ]
    if all(len(name) == 1 for name in directions):
        labels["stick"] = "".join(directions)
    elif directions == ["UP", "LEFT", "DOWN", "RIGHT"]:
        labels["stick"] = "arrows"
    else:
        labels["stick"] = "/".join(key_label(name) for name in directions)
    return labels


def gamepad_labels(preset: PadBindings) -> dict[str, str]:
    """Return the action labels for a gamepad's bindings."""

    def named(controls: Sequence[str], fallback: str = UNBOUND) -> str:
        return "/".join(PAD_LABELS.get(control, control) for control in controls) or fallback

    up, down = named(preset.up), named(preset.down)
    if preset.right_stick_modifiers:
        up = "RS up" if not preset.up else f"RS up/{up}"
        down = "RS down" if not preset.down else f"RS down/{down}"
    return {
        "stick": "LS",
        "attack": named(preset.attack),
        "special": named(preset.special),
        "strong": named(preset.strong, "RS"),
        "grab": named(preset.grab),
        "jump": named(preset.jump),
        "shield": named(preset.shield),
        "up": up,
        "down": down,
        "taunt": named(preset.taunt),
    }


def build_move_list(
    moveset: MoveSet, labels: Mapping[str, str], short_hop_macro: bool
) -> tuple[MoveSection, ...]:
    """Return the move list of a character for one player's labels.

    Every ``[moveset]`` slot appears exactly once. Aerials are their own section, with a line
    for the short-hop macro when that rule is on.
    """
    missing = [action for action in ACTIONS if action not in labels]
    if missing:
        raise ValueError(f"no label for {', '.join(missing)}")
    stick, attack, special = labels["stick"], labels["attack"], labels["special"]
    strong, up, down = labels["strong"], labels["up"], labels["down"]
    aside = f"{stick} + "
    jab = f"{attack} (again to combo)" if len(moveset.jab) > 1 else attack
    ground = (
        MoveRow("jab", "Jab", jab),
        MoveRow("ftilt", "Forward tilt", f"{aside}{attack}"),
        MoveRow("utilt", "Up tilt", f"{up} + {attack}"),
        MoveRow("dtilt", "Down tilt", f"{down} + {attack}"),
        MoveRow("dash_attack", "Dash attack", f"{attack} while running"),
        MoveRow("fsmash", "Forward smash", f"{strong}  ({aside}{strong} turns)"),
        MoveRow("usmash", "Up smash", f"{up} + {strong}"),
        MoveRow("dsmash", "Down smash", f"{down} + {strong}"),
    )
    air = [
        MoveRow("nair", "Neutral air", attack),
        MoveRow("fair", "Forward air", f"{attack} + {stick} toward facing"),
        MoveRow("bair", "Back air", f"{attack} + {stick} away"),
        MoveRow("uair", "Up air", f"{up} + {attack}"),
        MoveRow("dair", "Down air", f"{down} + {attack}"),
    ]
    if short_hop_macro:
        air.append(MoveRow("", "Short-hop air", f"{labels['jump']} + {attack} together"))
    specials = (
        MoveRow("nspecial", "Neutral special", special),
        MoveRow("sspecial", "Side special", f"{aside}{special}"),
        MoveRow("uspecial", "Up special", f"{up} + {special}"),
        MoveRow("dspecial", "Down special", f"{down} + {special}"),
    )
    other = (
        MoveRow("", "Grab", f"{labels['grab']}, throw: {stick}/{up}/{down}"),
        MoveRow("getup_attack", "Getup attack", f"{attack} while lying down"),
        MoveRow("ledge_attack", "Ledge attack", f"{attack} while hanging"),
        MoveRow("taunt", "Taunt", labels["taunt"]),
    )
    sections = (
        MoveSection("GROUND", ground),
        MoveSection("AIR", tuple(air)),
        MoveSection("SPECIALS", specials),
        MoveSection("OTHER", other),
    )
    listed = sorted(row.slot for section in sections for row in section.rows if row.slot)
    assert listed == sorted(field.name for field in fields(moveset)), "a moveset slot is missing"
    return sections


def format_row(row: MoveRow, width: int) -> str:
    """Return a row as ``name  inputs`` in two columns, clipped to ``width`` characters."""
    return f"{row.name:<{NAME_WIDTH}} {row.inputs}"[:width]


def page_columns(sections: Sequence[MoveSection], width: int) -> tuple[list[str], list[str]]:
    """Lay the sections out in two columns of text lines: ground and air on the left,
    specials and the rest on the right. Each section starts with its title."""

    def column(chosen: Sequence[MoveSection]) -> list[str]:
        lines: list[str] = []
        for section in chosen:
            if lines:
                lines.append("")
            lines.append(section.title)
            lines += [format_row(row, width) for row in section.rows]
        return lines

    half = len(sections) // 2
    return column(sections[:half]), column(sections[half:])
