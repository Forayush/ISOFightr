"""Reads a rendered tileset: ``assets/tilesets/<id>/tileset.json`` and one PNG per tile.

Plan note "10 - Animation and Asset Pipeline" ("Stage tiles") and decision D-044. A tile image
is an indexed render of one block: the top diamond at the top, then ``depth_px`` rows of side.
Costume 0 colours the light cells of the board's checker pattern, costume 1 the dark ones.
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

Rgb = tuple[int, int, int]


class TilesetArtError(ValueError):
    """``tileset.json`` is malformed."""


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

    def tile_path(self, tile: str) -> Path | None:
        """Return a tile's image, or ``None`` if this tileset has no such tile."""
        return self.folder / f"{tile}.png" if tile in self.tiles else None


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
        return TilesetArt(tileset_id, folder, int(data["depth_px"]), costumes, tuple(data["tiles"]))
    except (KeyError, TypeError, ValueError) as error:
        raise TilesetArtError(f"{path}: {error}") from error
