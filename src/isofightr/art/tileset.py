"""Writes a rendered tileset: one indexed PNG per tile plus ``tileset.json`` (decision D-044).

Plan note "10 - Animation and Asset Pipeline" ("Stage tiles"). Tiles are rendered by the same
Blender scripts as fighters, facing one way, on a small canvas whose pivot is a cell's far top
corner; each image keeps the top diamond and ``depth_px`` rows of side.

Decision D-063 adds **props**: ``props/<name>.toml`` in the tileset's source is one decoration,
modelled around the origin (standing on ``z = 0`` or hanging below it); each of its poses is a
frame. A prop is saved as ``prop_<name>.png``, its frames side by side, cut to the pixels any
frame draws. ``tileset.json`` also holds a hash of the sources, so a test can tell when the
committed images are stale without running Blender.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from PIL import Image

from isofightr.art.packer import palette_bytes
from isofightr.art.palettes import TRANSPARENT_INDEX, CharacterPalettes
from isofightr.config import TILE_H, TILE_W
from isofightr.data.tileset_art import PROP_FILE_PREFIX

TILE_CANVAS: Final[tuple[int, int]] = (64, 128)
TILE_PIVOT: Final[tuple[int, int]] = (TILE_W, TILE_H)
"""A cell's far top corner (world ``(0, 0, top)``) lands on this pixel corner."""
TILE_FACING: Final[str] = "SE"
"""Tiles do not turn; SE is the unrotated model."""
TILE_DEPTH_PX: Final[int] = 48
"""Rows of side kept below the top diamond (3 units, as modelled)."""
PROPS_DIR_NAME: Final[str] = "props"
PROP_CANVAS: Final[tuple[int, int]] = (128, 224)
PROP_PIVOT: Final[tuple[int, int]] = (64, 144)
"""A prop's world position (the model's origin) lands on this pixel corner: room for 9 units
above it and 5 hanging below."""


def source_hash(folder: Path) -> str:
    """Return a hash of everything a tileset is built from (every file of its source folder
    and the build's own settings). Line endings do not count."""
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(folder).as_posix().encode())
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    settings = (TILE_CANVAS, TILE_PIVOT, TILE_DEPTH_PX, PROP_CANVAS, PROP_PIVOT)
    digest.update(repr(settings).encode())
    return digest.hexdigest()


def pack_prop(frames: Sequence[Image.Image]) -> tuple[Image.Image, dict[str, object]]:
    """Cut a prop's composed frames (mode ``"L"``) to the box of everything any of them draws
    and lay them side by side. Returns the strip and the prop's ``tileset.json`` entry."""
    boxes = [box for frame in frames if (box := frame.getbbox()) is not None]
    if not boxes:
        raise ValueError("a prop draws nothing")
    left, top = min(box[0] for box in boxes), min(box[1] for box in boxes)
    right, bottom = max(box[2] for box in boxes), max(box[3] for box in boxes)
    width, height = right - left, bottom - top
    strip = Image.new("L", (width * len(frames), height), TRANSPARENT_INDEX)
    for index, frame in enumerate(frames):
        strip.paste(frame.crop((left, top, right, bottom)), (index * width, 0))
    entry: dict[str, object] = {
        "frames": len(frames),
        "size": [width, height],
        "pivot": [PROP_PIVOT[0] - left, PROP_PIVOT[1] - top],
    }
    return strip, entry


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
    props: Mapping[str, Sequence[Image.Image]] | None = None,
    source: str = "",
) -> None:
    """Save each cut tile and each prop as an indexed PNG and describe them in
    ``tileset.json``. Images of tiles and props that no longer exist are removed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    images: dict[str, Image.Image] = dict(tiles)
    prop_entries: dict[str, dict[str, object]] = {}
    for name, frames in sorted((props or {}).items()):
        images[f"{PROP_FILE_PREFIX}{name}"], prop_entries[name] = pack_prop(frames)
    for old in out_dir.glob("*.png"):
        if old.stem not in images:
            old.unlink()
    for name, image in images.items():
        indexed = image.convert("P")
        indexed.putpalette(palette_bytes(palettes.costumes[0]))
        indexed.save(out_dir / f"{name}.png", transparency=TRANSPARENT_INDEX, optimize=True)
    data = {
        "format": 1,
        "tileset": tileset_id,
        "blender": blender_version,
        "depth_px": TILE_DEPTH_PX,
        "source": source,
        "tiles": sorted(tiles),
        "props": prop_entries,
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
