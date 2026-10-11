"""Reads a rendered tileset: ``assets/tilesets/<id>/tileset.json`` and one PNG per tile.

Plan note "10 - Animation and Asset Pipeline" ("Stage tiles") and decision D-044. A tile image
is an indexed render of one block: the top diamond at the top, then ``depth_px`` rows of side.
Costume 0 colours the light cells of the board's checker pattern, costume 1 the dark ones.

Decision D-063: a tile may have **variants** (``grass``, ``grass_b``, ``grass_c``...: which one
a cell shows is :func:`variant_index` of its coordinates), and a tileset may have **props**
(``prop_<name>.png``: the frames of one decoration side by side, with the pixel that stands on
its world position).
Pure Python (no ``arcade``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from isofightr.data.paths import ASSETS_DIR

TILESETS_DIR: Final[Path] = ASSETS_DIR / "tilesets"
TILESET_FILE_NAME: Final[str] = "tileset.json"
SUPPORTED_FORMAT: Final[int] = 1
VARIANT_SUFFIXES: Final[str] = "bcdefgh"
"""A tile's variants are named ``<tile>_b``, ``<tile>_c``..."""
PROP_FILE_PREFIX: Final[str] = "prop_"

Rgb = tuple[int, int, int]


class TilesetArtError(ValueError):
    """``tileset.json`` is malformed."""


@dataclass(frozen=True, slots=True)
class PropArt:
    """One decoration of a tileset."""

    name: str
    frames: int
    width: int
    """Width of one frame; the image holds ``frames`` of them side by side."""
    height: int
    pivot_x: int
    """The pixel edge, from a frame's left, that stands on the prop's world position."""
    pivot_y: int
    """The same from the frame's top: rows above it rise over the position, rows below hang."""


def variant_index(cx: int, cy: int, count: int) -> int:
    """Return which of a tile's ``count`` variants the cell ``(cx, cy)`` shows: a fixed
    scramble of the coordinates, so a floor never reads as a pattern and a stage looks the
    same every match (decision D-063)."""
    if count <= 1:
        return 0
    mixed = (cx * 73856093) ^ (cy * 19349663) ^ ((cx + cy) * 83492791)
    mixed = (mixed ^ (mixed >> 13)) * 1274126177 & 0xFFFFFFFF
    return (mixed ^ (mixed >> 16)) % count


@dataclass(frozen=True, slots=True)
class TilesetArt:
    """A rendered tileset."""

    tileset_id: str
    folder: Path
    depth_px: int
    """How many pixels of side the tile images hold below the top diamond."""
    costumes: tuple[tuple[Rgb, ...], ...]
    """Colour per palette index: light cells, then dark cells."""
    tiles: tuple[str, ...]
    props: tuple[PropArt, ...] = ()
    source: str = ""
    """A hash of the art sources the tileset was built from (empty for old builds)."""

    def tile_path(self, tile: str) -> Path | None:
        """Return a tile's image, or ``None`` if this tileset has no such tile."""
        return self.folder / f"{tile}.png" if tile in self.tiles else None

    def variants(self, tile: str) -> tuple[str, ...]:
        """Return the images a tile name may show: itself, then ``<tile>_b``, ``<tile>_c``...
        (empty if the tileset has no such tile)."""
        if tile not in self.tiles:
            return ()
        extra = [f"{tile}_{suffix}" for suffix in VARIANT_SUFFIXES]
        return (tile, *(name for name in extra if name in self.tiles))

    @property
    def prop_names(self) -> tuple[str, ...]:
        """The names of the tileset's props."""
        return tuple(prop.name for prop in self.props)

    def prop(self, name: str) -> PropArt | None:
        """Return a prop's description, or ``None`` if the tileset has no such prop."""
        return next((prop for prop in self.props if prop.name == name), None)

    def prop_path(self, name: str) -> Path:
        """Return the image holding a prop's frames."""
        return self.folder / f"{PROP_FILE_PREFIX}{name}.png"


def load_tileset_art(tileset_id: str, tilesets_dir: Path = TILESETS_DIR) -> TilesetArt | None:
    """Load a tileset's art, or return ``None`` if it has none (placeholder blocks)."""
    folder = tilesets_dir / tileset_id
    path = folder / TILESET_FILE_NAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != SUPPORTED_FORMAT:
        raise TilesetArtError(f"{path}: unsupported format {data.get('format')!r}")
    try:
        costumes = tuple(
            tuple((int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)) for c in costume["colors"])
            for costume in data["costumes"]
        )
        props = tuple(
            PropArt(
                name,
                int(entry["frames"]),
                int(entry["size"][0]),
                int(entry["size"][1]),
                int(entry["pivot"][0]),
                int(entry["pivot"][1]),
            )
            for name, entry in sorted(data.get("props", {}).items())
        )
        return TilesetArt(
            tileset_id,
            folder,
            int(data["depth_px"]),
            costumes,
            tuple(data["tiles"]),
            props,
            str(data.get("source", "")),
        )
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
        raise TilesetArtError(f"{path}: {error}") from error
