"""Hero art: the large key pose of each character, for menus (build side).

Plan note "10 - Animation and Asset Pipeline" and decision D-061. ``hero.toml`` in a
character's ``art_src`` folder holds one pose and a ``[camera]``: hero art is not laid over
the game's tiles, so each character gets the view that suits its pose (how far it is turned
from the viewer, how high the camera is) and keeps its true proportions. It is rendered at
twice the game's pixels per unit and shown one art pixel per screen pixel, so its pixels are
the size of everything else's. The win picture is ``hero_win.toml`` if the character has
one, else the first pose of its ``victory`` animation, from the same camera; the roster tile
is cut from the portrait pose.

Pure Python (no ``arcade``, no Blender), so it is unit tested without either.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from isofightr.art.palettes import ART_SRC

HERO_FILE: Final[str] = "hero.toml"
WIN_FILE: Final[str] = "hero_win.toml"
"""Optional: a pose for the win picture. Without it the first pose of the ``victory``
animation is used."""
HERO_SCALE: Final[int] = 2
"""Hero art is rendered at this many times the game's pixels per unit (the user's choice
between 2 and 3: at 2 it reads as the same art as the sprites and fits a player panel)."""
HERO_CANVAS: Final[tuple[int, int]] = (224, 224)
"""The render canvas in pixels; the picture is trimmed afterwards."""
HERO_PIVOT: Final[tuple[int, int]] = (112, 184)
"""Where the character's feet land on the canvas, from its top-left."""
TILE_SIZE: Final[int] = 40
"""The roster tile: head and shoulders, square, in native pixels."""
TILE_SCALE: Final[float] = TILE_SIZE / 30
"""The tile is the bust's pose rendered this much larger (the bust is 30 px)."""
MARGIN: Final[int] = 1
"""Transparent pixels kept around a trimmed hero picture."""
DEFAULT_ELEVATION: Final[float] = 14.0
ELEVATION_RANGE: Final[tuple[float, float]] = (0.0, 45.0)
TURN_RANGE: Final[tuple[float, float]] = (-80.0, 80.0)
SOURCES: Final[tuple[str, ...]] = (
    "rig.toml",
    "poses.toml",
    HERO_FILE,
    WIN_FILE,
    "portrait.toml",
    "palettes.toml",
    "anims/victory.toml",
)
"""The files a character's hero pictures are made from, relative to its art folder."""
OUTPUTS: Final[tuple[str, ...]] = ("hero.png", "hero_win.png", "tile.png")
INDEX_FILE: Final[str] = "ui.json"


class HeroError(ValueError):
    """A ``hero.toml`` is malformed."""


@dataclass(frozen=True, slots=True)
class HeroCamera:
    """The view a character's hero art is rendered from."""

    turn: float = 0.0
    """Degrees the character is turned from facing the viewer; positive is toward the
    screen's right."""
    elevation: float = DEFAULT_ELEVATION
    """Degrees the camera looks down: 0 is level with the character, 30 is the game's."""


def character_dir(character_id: str, art_src: Path = ART_SRC) -> Path:
    """Return a character's art source folder."""
    return art_src / "characters" / character_id


def has_hero(character_id: str, art_src: Path = ART_SRC) -> bool:
    """Return whether a character has a ``hero.toml``."""
    return (character_dir(character_id, art_src) / HERO_FILE).is_file()


def parse_camera(data: dict[str, Any], source: str = HERO_FILE) -> HeroCamera:
    """Read the ``[camera]`` of a parsed ``hero.toml`` (every key optional).

    Raises:
        HeroError: an unknown key, a value that is not a number, or one out of range.
    """
    table = data.get("camera", {})
    if not isinstance(table, dict):
        raise HeroError(f"{source}: [camera] must be a table")
    unknown = sorted(set(table) - {"turn", "elevation"})
    if unknown:
        raise HeroError(f"{source}: unknown [camera] key {unknown[0]!r}")
    values = {"turn": 0.0, "elevation": DEFAULT_ELEVATION}
    ranges = {"turn": TURN_RANGE, "elevation": ELEVATION_RANGE}
    for key in values:
        if key not in table:
            continue
        value = table[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise HeroError(f"{source}: camera.{key} must be a number")
        low, high = ranges[key]
        if not low <= value <= high:
            raise HeroError(f"{source}: camera.{key} must be {low:g} to {high:g}, got {value}")
        values[key] = float(value)
    return HeroCamera(values["turn"], values["elevation"])


def load_camera(character_id: str, art_src: Path = ART_SRC) -> HeroCamera:
    """Load the camera of a character's ``hero.toml``."""
    path = character_dir(character_id, art_src) / HERO_FILE
    with path.open("rb") as file:
        data = tomllib.load(file)
    if not data.get("poses"):
        raise HeroError(f"{path}: needs one [[poses]] entry")
    return parse_camera(data, str(path))


def win_pose_file(character_id: str, art_src: Path = ART_SRC) -> Path:
    """Return the file the win picture's pose comes from."""
    folder = character_dir(character_id, art_src)
    own = folder / WIN_FILE
    return own if own.is_file() else folder / "anims" / "victory.toml"


def source_hash(character_id: str, art_src: Path = ART_SRC) -> str:
    """Return a hash of everything a character's hero pictures are rendered from, and of
    the build's own settings, so a test can tell when the committed pictures are stale
    without running Blender. Line endings do not count."""
    digest = hashlib.sha256()
    folder = character_dir(character_id, art_src)
    for name in SOURCES:
        path = folder / name
        digest.update(name.encode())
        content = path.read_bytes() if path.is_file() else b"-"
        digest.update(content.replace(b"\r\n", b"\n"))
    settings = (HERO_SCALE, HERO_CANVAS, HERO_PIVOT, TILE_SIZE, MARGIN)
    digest.update(repr(settings).encode())
    return digest.hexdigest()
