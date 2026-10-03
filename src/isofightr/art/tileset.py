"""Writes a rendered tileset: one indexed PNG per tile plus ``tileset.json`` (decision D-044).

Plan note "10 - Animation and Asset Pipeline" ("Stage tiles"). Tiles are rendered by the same
Blender scripts as fighters, facing one way, on a small canvas whose pivot is a cell's far top
corner; each image keeps the top diamond and ``depth_px`` rows of side.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from PIL import Image

from isofightr.art.packer import palette_bytes
from isofightr.art.palettes import TRANSPARENT_INDEX, CharacterPalettes
from isofightr.config import TILE_H, TILE_W

TILE_CANVAS: Final[tuple[int, int]] = (64, 128)
TILE_PIVOT: Final[tuple[int, int]] = (TILE_W, TILE_H)
"""A cell's far top corner (world ``(0, 0, top)``) lands on this pixel corner."""
TILE_FACING: Final[str] = "SE"
"""Tiles do not turn; SE is the unrotated model."""
TILE_DEPTH_PX: Final[int] = 48
"""Rows of side kept below the top diamond (3 units, as modelled)."""


def cut_tile(composed: Image.Image) -> Image.Image:
    """Cut one block out of a composed tile render (mode ``"L"``)."""
    left = TILE_PIVOT[0] - TILE_W // 2
    top = TILE_PIVOT[1]
    return composed.crop((left, top, left + TILE_W, top + TILE_H + TILE_DEPTH_PX))


def write_tileset(
    out_dir: Path,
    tileset_id: str,
    tiles: Mapping[str, Image.Image],
    palettes: CharacterPalettes,
    blender_version: str,
) -> None:
    """Save each cut tile as an indexed PNG and describe them in ``tileset.json``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, image in tiles.items():
        indexed = image.convert("P")
        indexed.putpalette(palette_bytes(palettes.costumes[0]))
        indexed.save(out_dir / f"{name}.png", transparency=TRANSPARENT_INDEX, optimize=True)
    data = {
        "format": 1,
        "tileset": tileset_id,
        "blender": blender_version,
        "depth_px": TILE_DEPTH_PX,
        "tiles": sorted(tiles),
        "costumes": [
            {
                "name": costume.name,
                "colors": [f"{r:02x}{g:02x}{b:02x}" for r, g, b in costume.colors()],
            }
            for costume in palettes.costumes
        ],
    }
    (out_dir / "tileset.json").write_text(
        json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
