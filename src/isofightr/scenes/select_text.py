"""What character select writes: prompts, the footer and messages, each in the keys of the
device it is about.

Plan note "13 - Game Modes UI and Flow" ("Character select screen", decision D-062). A
panel's text uses **that panel's own device** (a CPU's uses its owner's), so a player on the
arrows keyboard is never told to press the WASD keyboard's keys. An empty panel lists how to
join on every free device. The footer follows the device that acted last, is measured, and
drops its least important items before it would overflow. Messages are one line, written to
fit the bottom band.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from isofightr.config import NATIVE_W
from isofightr.settings import Settings, shared_keys
from isofightr.ui import font
from isofightr.ui.hints import KEYBOARD_PREFIX, PAD_PREFIX, device_labels, fit_hint, hint_text

PANEL_TEXT_WIDTH: Final[int] = 140
"""The widest a line of a player panel may be (the panel is 148 px)."""
FOOTER_WIDTH: Final[int] = NATIVE_W - 16
"""The widest the footer or a message may be."""
PROMPT_LINES: Final[int] = 8
"""Lines an empty panel has for the join list."""
DEVICE_NAMES: Final[dict[str, str]] = {
    f"{KEYBOARD_PREFIX}solo": "WASD KEYS",
    f"{KEYBOARD_PREFIX}arrows": "ARROW KEYS",
}
JOIN_HEADING: Final[str] = "PRESS TO JOIN"
READY_LINE: Final[str] = "{attack}: ready"
CANCEL_LINE: Final[str] = "{special}: cancel"
CPU_EDIT_LINE: Final[str] = "{attack}: done  {special}: remove"
"""What attack and special do while a player sets up a CPU (on the CPU's panel)."""
CPU_ADD_LINE: Final[str] = "{grab}: ADD A CPU"
PANEL_LINES: Final[tuple[str, ...]] = (READY_LINE, CANCEL_LINE, CPU_EDIT_LINE, CPU_ADD_LINE)
"""Every template a panel fills in with a device's keys."""
OWNER_WAITS: Final[str] = "SETTING UP A CPU"
"""What a player's own panel says while that player is setting up a CPU."""
CONTROLS_HINT: Final[str] = "↓ CONTROLS"

_DROP: Final[tuple[str, ...]] = ("strong", "controls", "team", "stick")
FOOTERS: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "unjoined": ("{attack}: join   {special}: back", ()),
    "roster": (
        "{attack}: ready   {stick}: pick   ↓: controls   {strong}: costume   "
        "{grab}: add CPU   {special}: back",
        _DROP,
    ),
    "team": ("{attack}: ready   ←→: team   ↑↓: fighter, controls   {special}: back", _DROP),
    "controls": (
        "←→: change controls   {attack}: ready   ↑: fighter   {special}: back",
        ("fighter",),
    ),
    "chip": ("{attack}: open the rules   ↓: fighters   {special}: back", ()),
    "ready": ("{special}: cancel   waiting for everyone", ("waiting",)),
    "cpu": (
        "{attack}: done   {special}: remove   {stick}: fighter, level   {strong}: costume",
        ("strong", "stick"),
    ),
}
"""The footer for each thing a player can be doing: its template, and which items to drop
first (named by a placeholder or a word in the item) when it would not fit."""


def device_name(device: str) -> str:
    """Return a device's short name for a panel's strip and the messages."""
    if device in DEVICE_NAMES:
        return DEVICE_NAMES[device]
    if device.startswith(PAD_PREFIX) and device[len(PAD_PREFIX) :].isdigit():
        return f"PAD {int(device[len(PAD_PREFIX) :]) + 1}"
    return device.upper()


def panel_line(
    template: str, settings: Settings, device: str, width: int = PANEL_TEXT_WIDTH
) -> str:
    """Return a panel's hint line in a device's own keys, shortened to fit the panel."""
    return font.fit(hint_text(template, device_labels(settings, device)), width)


def join_lines(
    settings: Settings,
    free_devices: Sequence[str],
    cpu_device: str,
    width: int = PANEL_TEXT_WIDTH,
) -> list[str]:
    """Return what the first empty panel says: a heading and one line per device that can
    still join (its own join control, then its name: ``J  WASD KEYS``), then how the first
    human adds a CPU (``cpu_device`` is that player's device; "" for none, or in training).
    Never more than :data:`PROMPT_LINES` lines, none wider than ``width``."""
    lines: list[str] = []
    if free_devices:
        lines.append(JOIN_HEADING)
        for device in free_devices:
            control = device_labels(settings, device)["attack"]
            lines.append(font.fit(f"{control}  {device_name(device)}", width))
    if cpu_device:
        if lines:
            lines.append("")
        lines.append(panel_line(CPU_ADD_LINE, settings, cpu_device, width))
    if len(lines) > PROMPT_LINES and "" in lines:
        lines.remove("")
    return lines[:PROMPT_LINES]


def footer_template(
    state: str, training: bool = False, device: str = ""
) -> tuple[str, tuple[str, ...]]:
    """Return the footer's template and its drop order for what the acting player is doing
    (a key of :data:`FOOTERS`). Training has no CPUs to add. With ``device`` the footer
    starts with that device's name: for when several people are in, so each can tell whose
    keys it shows."""
    template, drop = FOOTERS.get(state, FOOTERS["roster"])
    if training:
        template = "   ".join(item for item in template.split("   ") if "{grab}" not in item)
    if device:
        template = f"{device_name(device)}   {template}"
    return template, drop


def footer_line(
    state: str,
    settings: Settings,
    device: str,
    training: bool = False,
    width: int = FOOTER_WIDTH,
    named: bool = False,
) -> str:
    """Return the footer for what the acting player is doing, in that device's keys
    (starting with the device's name if ``named``), dropping its least important items
    until it fits ``width``."""
    template, drop = footer_template(state, training, device if named else "")
    return fit_hint(template, device_labels(settings, device), width, drop)


def start_problem(reason: str, settings: Settings, device: str) -> str:
    """Return why the match cannot start (``can_start``'s text) in a device's own keys."""
    if not reason:
        return ""
    return font.fit(hint_text(reason, device_labels(settings, device)), FOOTER_WIDTH)


def join_first(settings: Settings, device: str) -> str:
    """Return what a device that has not joined is told when it presses something else."""
    return hint_text("PRESS {attack} TO JOIN FIRST", device_labels(settings, device))


def joined(index: int, device: str) -> str:
    """Return the message for a player who has just joined."""
    return f"P{index + 1} JOINED ON {device_name(device)}"


def switched(index: int, device: str) -> str:
    """Return the message for a player who has just changed controls."""
    return f"P{index + 1} NOW USES {device_name(device)}"


def shared_message(settings: Settings, first: str, second: str) -> str:
    """Return the warning for two joined keyboard layouts that share keys ("" if they share
    none, or if either device is not a keyboard)."""
    if not (first.startswith(KEYBOARD_PREFIX) and second.startswith(KEYBOARD_PREFIX)):
        return ""
    keys = shared_keys(settings, first[len(KEYBOARD_PREFIX) :], second[len(KEYBOARD_PREFIX) :])
    if not keys:
        return ""
    names = f"{device_name(first)} AND {device_name(second)} SHARE "
    return font.fit(names + ", ".join(keys), FOOTER_WIDTH)
