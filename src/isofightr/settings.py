"""User settings and their ``settings.toml`` file.

Plan note "13 - Game Modes UI and Flow" ("Settings": video, audio, controls; saved to
``settings.toml`` in the user config dir). Keys are stored by name (``"W"``, ``"NUM_4"``), so
this module needs no key codes; :mod:`isofightr.input.devices` turns names into codes.

A missing or broken file never stops the game: unreadable values fall back to the defaults.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from isofightr.config import DEFAULT_WINDOW_SCALE, MAX_PLAYERS, STICK_DEADZONE

LOG = logging.getLogger(__name__)

SETTINGS_FILE_NAME: Final[str] = "settings.toml"
CONFIG_DIR_ENV: Final[str] = "ISOFIGHTR_CONFIG_DIR"
"""Environment variable that overrides where ``settings.toml`` lives."""
APP_DIR_NAME: Final[str] = "ISOFightr"

SCALES: Final[tuple[int, ...]] = (1, 2, 3, 4)
VOLUME_MAX: Final[int] = 10
SHAKE_STEPS: Final[tuple[int, ...]] = (0, 25, 50, 75, 100)
"""Screen shake intensities, in percent."""
DEADZONES: Final[tuple[float, ...]] = (0.10, 0.15, 0.20, 0.25, 0.30, 0.35)
PRESET_RIGHT_STICK: Final[str] = "right_stick_modifiers"
PRESET_BUMPERS: Final[str] = "modifier_bumpers"
GAMEPAD_PRESETS: Final[tuple[str, ...]] = (PRESET_RIGHT_STICK, PRESET_BUMPERS)

KEYBOARD_SOLO: Final[str] = "solo"
KEYBOARD_ARROWS: Final[str] = "arrows"
KEYBOARD_ACTIONS: Final[tuple[str, ...]] = (
    "move_up",
    "move_down",
    "move_left",
    "move_right",
    "up",
    "down",
    "attack",
    "special",
    "strong",
    "grab",
    "jump",
    "shield",
    "walk",
    "taunt",
)
"""Everything a keyboard layout can bind, in the order the rebinding screen lists it."""
DEFAULT_KEYS: Final[Mapping[str, Mapping[str, str]]] = {
    KEYBOARD_SOLO: {
        "move_up": "W",
        "move_down": "S",
        "move_left": "A",
        "move_right": "D",
        "up": "I",
        "down": "COMMA",
        "attack": "J",
        "special": "K",
        "strong": "U",
        "grab": "L",
        "jump": "SPACE",
        "shield": "LSHIFT",
        "walk": "LCTRL",
        "taunt": "T",
    },
    KEYBOARD_ARROWS: {
        "move_up": "UP",
        "move_down": "DOWN",
        "move_left": "LEFT",
        "move_right": "RIGHT",
        "up": "NUM_8",
        "down": "NUM_2",
        "attack": "NUM_4",
        "special": "NUM_5",
        "strong": "NUM_7",
        "grab": "NUM_6",
        "jump": "NUM_0",
        "shield": "NUM_1",
        "walk": "",
        "taunt": "NUM_9",
    },
}
"""Default key name per action for each keyboard layout ("" = not bound)."""


def _default_keys() -> dict[str, dict[str, str]]:
    return {layout: dict(keys) for layout, keys in DEFAULT_KEYS.items()}


def _default_slots() -> tuple[str, ...]:
    """Player 1 starts on the WASD keyboard; everyone else joins on character select."""
    return ("keyboard:" + KEYBOARD_SOLO, *[""] * (MAX_PLAYERS - 1))


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the settings screen can change."""

    scale: int = DEFAULT_WINDOW_SCALE
    """Integer window scale of the 640x360 picture."""
    fullscreen: bool = False
    screen_shake: int = 100
    """Screen shake intensity in percent."""
    master_volume: int = VOLUME_MAX
    music_volume: int = 8
    sfx_volume: int = VOLUME_MAX
    gamepad_preset: str = PRESET_RIGHT_STICK
    """Which gamepad layout to use. It also decides what the right stick does: up and down
    modifiers, or a smash stick in every direction."""
    deadzone: float = STICK_DEADZONE
    keys: dict[str, dict[str, str]] = field(default_factory=_default_keys)
    """Key name per action, per keyboard layout."""
    slot_devices: tuple[str, ...] = field(default_factory=_default_slots)
    """The device each player slot last used ("" = none): rejoined automatically."""

    def with_key(self, layout: str, action: str, key_name: str) -> Settings:
        """Return the settings with one action rebound. The key is taken away from any other
        action of the same layout, so one key never does two things."""
        keys = {name: dict(bound) for name, bound in self.keys.items()}
        for other, bound in keys[layout].items():
            if bound == key_name and other != action:
                keys[layout][other] = ""
        keys[layout][action] = key_name
        return replace(self, keys=keys)

    def with_default_keys(self, layout: str) -> Settings:
        """Return the settings with one keyboard layout back on its default keys."""
        keys = {name: dict(bound) for name, bound in self.keys.items()}
        keys[layout] = dict(DEFAULT_KEYS[layout])
        return replace(self, keys=keys)


def config_dir() -> Path:
    """Return the directory ``settings.toml`` lives in: ``ISOFIGHTR_CONFIG_DIR`` if set, else
    the per-user application data directory."""
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME.lower()


def settings_path() -> Path:
    """Return the default ``settings.toml`` path."""
    return config_dir() / SETTINGS_FILE_NAME


def _pick[T](value: object, allowed: tuple[T, ...], default: T) -> T:
    for option in allowed:
        if value == option and type(value) is type(option):
            return option
    return default


def _volume(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return min(max(value, 0), VOLUME_MAX)


def from_data(data: Mapping[str, Any]) -> Settings:
    """Build settings from a parsed ``settings.toml``. Anything missing or out of range falls
    back to its default, so an old or hand-edited file still loads."""
    defaults = Settings()
    video = data.get("video", {}) if isinstance(data.get("video"), dict) else {}
    audio = data.get("audio", {}) if isinstance(data.get("audio"), dict) else {}
    gamepad = data.get("gamepad", {}) if isinstance(data.get("gamepad"), dict) else {}
    keyboard = data.get("keyboard", {}) if isinstance(data.get("keyboard"), dict) else {}
    players = data.get("players", {}) if isinstance(data.get("players"), dict) else {}

    keys = _default_keys()
    for layout, bound in keys.items():
        saved = keyboard.get(layout)
        if not isinstance(saved, dict):
            continue
        for action in KEYBOARD_ACTIONS:
            name = saved.get(action)
            if isinstance(name, str):
                bound[action] = name
    fullscreen = video.get("fullscreen")
    devices = players.get("devices")
    slots = list(defaults.slot_devices)
    if isinstance(devices, list):
        for index, device in enumerate(devices[:MAX_PLAYERS]):
            slots[index] = device if isinstance(device, str) else ""
    deadzone = gamepad.get("deadzone")
    return Settings(
        scale=_pick(video.get("scale"), SCALES, defaults.scale),
        fullscreen=fullscreen if isinstance(fullscreen, bool) else defaults.fullscreen,
        screen_shake=_pick(video.get("screen_shake"), SHAKE_STEPS, defaults.screen_shake),
        master_volume=_volume(audio.get("master"), defaults.master_volume),
        music_volume=_volume(audio.get("music"), defaults.music_volume),
        sfx_volume=_volume(audio.get("sfx"), defaults.sfx_volume),
        gamepad_preset=_pick(gamepad.get("preset"), GAMEPAD_PRESETS, defaults.gamepad_preset),
        deadzone=_pick(
            round(deadzone, 2) if isinstance(deadzone, float) else deadzone,
            DEADZONES,
            defaults.deadzone,
        ),
        keys=keys,
        slot_devices=tuple(slots),
    )


def to_toml(settings: Settings) -> str:
    """Return the settings as the text of a ``settings.toml``."""

    def text(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [
        "# ISOFightr settings. Written by the game; safe to edit or delete.",
        "",
        "[video]",
        f"scale = {settings.scale}",
        f"fullscreen = {'true' if settings.fullscreen else 'false'}",
        f"screen_shake = {settings.screen_shake}",
        "",
        "[audio]",
        f"master = {settings.master_volume}",
        f"music = {settings.music_volume}",
        f"sfx = {settings.sfx_volume}",
        "",
        "[gamepad]",
        f"preset = {text(settings.gamepad_preset)}",
        f"deadzone = {settings.deadzone:.2f}",
        "",
        "[players]",
        "devices = [" + ", ".join(text(device) for device in settings.slot_devices) + "]",
    ]
    for layout in DEFAULT_KEYS:
        lines += ["", f"[keyboard.{layout}]"]
        lines += [
            f"{action} = {text(settings.keys[layout].get(action, ''))}"
            for action in KEYBOARD_ACTIONS
        ]
    return "\n".join(lines) + "\n"


def load_settings(path: Path) -> Settings:
    """Read ``settings.toml``. A missing or unreadable file gives the defaults."""
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except FileNotFoundError:
        return Settings()
    except (OSError, tomllib.TOMLDecodeError) as error:
        LOG.warning("ignoring %s: %s", path, error)
        return Settings()
    return from_data(data)


def save_settings(path: Path, settings: Settings) -> None:
    """Write ``settings.toml``, creating its directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_toml(settings), encoding="utf-8", newline="\n")
