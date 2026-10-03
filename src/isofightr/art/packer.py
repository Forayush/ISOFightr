"""Turns Blender render passes into indexed sprite sheets (decision D-045).

Plan note "10 - Animation and Asset Pipeline" ("Packing"):

1. Each pixel's light value picks a band, and its material (from the id pass) picks a ramp:
   the pixel becomes that ramp slot's palette index.
2. Interior lines: where a part passes in front of another, the pixel of the part behind takes
   its material's outline colour (from the id pass's part number and depth).
3. Outer outline ("selout"): every empty pixel next to the model takes the outline colour of
   the material it touches, so the silhouette grows by one pixel.
4. Each frame is trimmed to its drawn pixels and packed into sheets; the JSON records where
   every frame is and where its feet pivot is.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from PIL import Image

from isofightr.art.anims import AnimTiming
from isofightr.art.palettes import (
    OUTLINE_SLOT,
    TRANSPARENT_INDEX,
    CharacterPalettes,
    Costume,
    ramp_index,
)

ID_STEP: Final[int] = 8
"""Must match ``tools/blender/isoscene.py``."""
PART_STEP: Final[int] = 4
OPAQUE_ALPHA: Final[int] = 128
DEPTH_GAP: Final[int] = 4
"""Depth levels (1 level is about 0.05 world units) by which a neighbouring part must be nearer
for an interior line to be drawn: parts that merely touch at a joint get none."""
SHEET_SIZE: Final[int] = 1024
FRAME_GAP: Final[int] = 1
SHEET_FORMAT: Final[int] = 1
NEIGHBOURS: Final[tuple[tuple[int, int], ...]] = ((0, 1), (0, -1), (-1, 0), (1, 0))
"""Below, above, left, right: the order an empty pixel looks for a material to outline."""


@dataclass(frozen=True, slots=True)
class Frame:
    """One composed, trimmed frame."""

    key: str
    """``"<anim>/<pose>/<direction>"``."""
    image: Image.Image
    """Mode ``"L"``: one palette index per pixel."""
    pivot: tuple[int, int]
    """The feet pivot from the trimmed image's top-left, in pixel edges."""


def compose(
    id_pass: Image.Image, light_pass: Image.Image, palettes: CharacterPalettes
) -> Image.Image:
    """Return the indexed image (mode ``"L"``) for one rendered frame."""
    width, height = id_pass.size
    ids = list(id_pass.convert("RGBA").getdata())
    lights = list(light_pass.convert("RGBA").getdata())
    materials = palettes.materials
    count = len(materials)

    material_at = [0] * (width * height)
    part_at = [0] * (width * height)
    depth_at = [0] * (width * height)
    out = [TRANSPARENT_INDEX] * (width * height)
    for i, (red, green, blue, alpha) in enumerate(ids):
        if alpha < OPAQUE_ALPHA:
            continue
        material_id = round(red / ID_STEP)
        if not 1 <= material_id <= count:
            raise ValueError(f"pixel {i % width},{i // width}: unknown material id {material_id}")
        material_at[i] = material_id
        part_at[i] = round(green / PART_STEP)
        depth_at[i] = blue
        material = materials[material_id - 1]
        band = palettes.band_of(lights[i][0] / 255) if material.lit else 0
        out[i] = ramp_index(material_id, band)

    lined = list(out)
    for i, material_id in enumerate(material_at):
        x, y = i % width, i // width
        if material_id:
            if not materials[material_id - 1].outline:
                continue
            for dx, dy in NEIGHBOURS:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                j = ny * width + nx
                if (
                    material_at[j]
                    and part_at[j] != part_at[i]
                    and depth_at[i] > depth_at[j] + DEPTH_GAP
                ):
                    lined[i] = ramp_index(material_id, OUTLINE_SLOT)
                    break
            continue
        for dx, dy in NEIGHBOURS:
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            neighbour = material_at[ny * width + nx]
            if neighbour and materials[neighbour - 1].outline:
                lined[i] = ramp_index(neighbour, OUTLINE_SLOT)
                break
    image = Image.new("L", (width, height))
    image.putdata(lined)
    return image


def trim(key: str, image: Image.Image, pivot: tuple[int, int]) -> Frame:
    """Crop a composed frame to its drawn pixels, keeping track of the pivot."""
    box = image.point(lambda value: 255 if value else 0).getbbox()
    if box is None:
        box = (pivot[0], pivot[1], pivot[0] + 1, pivot[1] + 1)
    left, top = box[0], box[1]
    return Frame(key, image.crop(box), (pivot[0] - left, pivot[1] - top))


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a frame sits in which sheet."""

    sheet: int
    x: int
    y: int


def pack(frames: Sequence[Frame], size: int = SHEET_SIZE) -> list[Placement]:
    """Shelf-pack frames (tallest first) into as many ``size`` x ``size`` sheets as needed.

    Returns one placement per frame, in the order given.
    """
    order = sorted(range(len(frames)), key=lambda i: (-frames[i].image.height, frames[i].key))
    placements: list[Placement | None] = [None] * len(frames)
    sheet, x, y, shelf = 0, 0, 0, 0
    for i in order:
        w, h = frames[i].image.size
        if w > size or h > size:
            raise ValueError(f"{frames[i].key} is larger than a sheet")
        if x + w > size:
            x, y, shelf = 0, y + shelf + FRAME_GAP, 0
        if y + h > size:
            sheet, x, y, shelf = sheet + 1, 0, 0, 0
        placements[i] = Placement(sheet, x, y)
        x += w + FRAME_GAP
        shelf = max(shelf, h)
    return [placement for placement in placements if placement is not None]


def palette_bytes(costume: Costume) -> list[int]:
    """Return a costume as a flat 256-entry RGB palette for ``Image.putpalette``."""
    flat = [value for color in costume.colors() for value in color]
    return flat + [0] * (256 * 3 - len(flat))


def write_sheets(
    out_dir: Path,
    character_id: str,
    frames: Sequence[Frame],
    timings: Iterable[AnimTiming],
    palettes: CharacterPalettes,
    blender_version: str,
) -> dict[str, Any]:
    """Pack frames into ``sheet_<n>.png`` files plus ``sprites.json`` in ``out_dir``.

    Old sheets in ``out_dir`` are removed first. Returns the JSON data written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("sheet_*.png"):
        old.unlink()
    placements = pack(frames)
    sheet_count = 1 + max((placement.sheet for placement in placements), default=0)
    sheets = [
        Image.new("P", (SHEET_SIZE, SHEET_SIZE), TRANSPARENT_INDEX) for _ in range(sheet_count)
    ]
    for frame, placement in zip(frames, placements, strict=True):
        sheets[placement.sheet].paste(frame.image, (placement.x, placement.y))
    names = []
    for number, sheet in enumerate(sheets):
        bottom = max(
            (
                p.y + f.image.height
                for f, p in zip(frames, placements, strict=True)
                if p.sheet == number
            ),
            default=1,
        )
        sheet = sheet.crop((0, 0, SHEET_SIZE, bottom))
        sheet.putpalette(palette_bytes(palettes.costumes[0]))
        name = f"sheet_{number}.png"
        sheet.save(out_dir / name, transparency=TRANSPARENT_INDEX, optimize=True)
        names.append(name)

    data: dict[str, Any] = {
        "format": SHEET_FORMAT,
        "character": character_id,
        "blender": blender_version,
        "sheets": names,
        "costumes": [
            {
                "name": costume.name,
                "colors": [
                    f"{red:02x}{green:02x}{blue:02x}" for red, green, blue in costume.colors()
                ],
            }
            for costume in palettes.costumes
        ],
        "anims": {
            timing.name: (
                {"loop": True, "fps": timing.fps, "poses": timing.poses}
                if timing.loop
                else {"loop": False, "starts": list(timing.starts), "poses": timing.poses}
            )
            for timing in sorted(timings, key=lambda timing: timing.name)
        },
        "frames": {
            frame.key: [
                placement.sheet,
                placement.x,
                placement.y,
                frame.image.width,
                frame.image.height,
                frame.pivot[0],
                frame.pivot[1],
            ]
            for frame, placement in sorted(
                zip(frames, placements, strict=True), key=lambda pair: pair[0].key
            )
        },
    }
    (out_dir / "sprites.json").write_text(
        json.dumps(data, indent=1, sort_keys=False) + "\n", encoding="utf-8", newline="\n"
    )
    return data
