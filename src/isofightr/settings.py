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
from isofightr.sim.constants import DEFAULT_STOCKS, DEFAULT_TIME_MINUTES

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
ZOOM_STATIC: Final[str] = "static"
ZOOM_STEPPED: Final[str] = "stepped"
CAMERA_ZOOMS: Final[tuple[str, ...]] = (ZOOM_STATIC, ZOOM_STEPPED)

MIN_COUNT: Final[int] = 1
MAX_COUNT: Final[int] = 99
"""Stocks and minutes both go from 1 to 99."""
LAUNCH_RATES: Final[tuple[float, ...]] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
START_DAMAGE_MAX: Final[int] = 300
START_DAMAGE_STEP: Final[int] = 10

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
class SavedRules:
    """The versus rules as the Rules screen leaves them (decision D-061). The defaults are
    the rules the game had before they could be saved, and what DEFAULT restores."""

    stock_on: bool = True
    stocks: int = DEFAULT_STOCKS
    time_on: bool = False
    minutes: int = DEFAULT_TIME_MINUTES
    launch_rate: float = 1.0
    start_damage: int = 0
    """Percent every fighter starts and respawns with."""
    team_play: bool = False
    friendly_fire: bool = False
    parry: bool = False
    short_hop_macro: bool = True
    air_dodge_helpless: bool = False
    hud_display: bool = True
    score_display: bool = False
    player_tags: bool = False
    pausing: bool = True
    random_pool: tuple[str, ...] = ()
    """Stage ids "Random" may pick; empty means every stage."""


RULE_FLAGS: Final[tuple[str, ...]] = (
    "team_play",
    "friendly_fire",
    "parry",
    "short_hop_macro",
    "air_dodge_helpless",
    "hud_display",
    "score_display",
    "player_tags",
    "pausing",
)
"""The on/off rules, as named in :class:`SavedRules` and in ``[rules]``."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the settings screen can change."""

    scale: int = DEFAULT_WINDOW_SCALE
    """Integer window scale of the 640x360 picture."""
    fullscreen: bool = False
    screen_shake: int = 100
    """Screen shake intensity in percent."""
    camera_zoom: str = ZOOM_STATIC
    """``"static"`` or ``"stepped"`` (2x when the fighters are close; decision D-048)."""
    reduce_flashing: bool = False
    """Accessibility: no white hit flash or charge blink, and intangible fighters are dimmed
    instead of blinking."""
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
    rules: SavedRules = field(default_factory=SavedRules)
    """The versus rules (the Rules screen), kept from one session to the next."""

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


def _count(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value if MIN_COUNT <= value <= MAX_COUNT else default


def rules_from_data(data: object) -> SavedRules:
    """Build the saved rules from a parsed ``[rules]`` table. Each value that is missing, of
    the wrong type or out of range falls back to its own default; nothing raises."""
    defaults = SavedRules()
    if not isinstance(data, dict):
        return defaults
    flags = {
        name: data[name] if isinstance(data.get(name), bool) else getattr(defaults, name)
        for name in ("stock_on", "time_on", *RULE_FLAGS)
    }
    if not flags["stock_on"] and not flags["time_on"]:
        # A match needs a way to end: an impossible pair goes back to the defaults.
        flags["stock_on"], flags["time_on"] = defaults.stock_on, defaults.time_on
    rate = data.get("launch_rate")
    rate = float(rate) if isinstance(rate, int) and not isinstance(rate, bool) else rate
    damage = data.get("start_damage")
    damage_ok = (
        isinstance(damage, int)
        and not isinstance(damage, bool)
        and 0 <= damage <= START_DAMAGE_MAX
        and damage % START_DAMAGE_STEP == 0
    )
    pool = data.get("random_pool")
    stages = (
        tuple(stage for stage in pool if isinstance(stage, str) and stage)
        if isinstance(pool, list)
        else ()
    )
    return SavedRules(
        stocks=_count(data.get("stocks"), defaults.stocks),
        minutes=_count(data.get("minutes"), defaults.minutes),
        launch_rate=_pick(rate, LAUNCH_RATES, defaults.launch_rate),
        start_damage=damage if damage_ok else defaults.start_damage,  # type: ignore[arg-type]
        random_pool=tuple(dict.fromkeys(stages)),
        **flags,
    )


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
    reduce_flashing = video.get("reduce_flashing")
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
        camera_zoom=_pick(video.get("camera_zoom"), CAMERA_ZOOMS, defaults.camera_zoom),
        reduce_flashing=(
            reduce_flashing if isinstance(reduce_flashing, bool) else defaults.reduce_flashing
        ),
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
        rules=rules_from_data(data.get("rules")),
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
        f"camera_zoom = {text(settings.camera_zoom)}",
        f"reduce_flashing = {'true' if settings.reduce_flashing else 'false'}",
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
    rules = settings.rules
    lines += [
        "",
        "[rules]",
        f"stock_on = {'true' if rules.stock_on else 'false'}",
        f"stocks = {rules.stocks}",
        f"time_on = {'true' if rules.time_on else 'false'}",
        f"minutes = {rules.minutes}",
        f"launch_rate = {rules.launch_rate:g}" + ("" if rules.launch_rate % 1 else ".0"),
        f"start_damage = {rules.start_damage}",
    ]
    lines += [f"{name} = {'true' if getattr(rules, name) else 'false'}" for name in RULE_FLAGS]
    lines.append("random_pool = [" + ", ".join(text(stage) for stage in rules.random_pool) + "]")
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
