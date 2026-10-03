"""Render a character in Blender and pack it into sprite sheets.

Usage::

    uv run python tools/build_art.py rook               # render what changed, then pack
    uv run python tools/build_art.py rook --force       # re-render everything
    uv run python tools/build_art.py rook --anim idle   # only some animations (still packs all)

Renders go to ``build/art/<id>/`` (git-ignored); sheets and ``sprites.json`` to
``assets/characters/<id>/sprites/``. Plan note "10 - Animation and Asset Pipeline".
"""

import argparse
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

from isofightr.art.anims import anims_dir, list_anims, load_timing
from isofightr.art.blender import (
    BUILD_DIR,
    PIVOT,
    RenderJob,
    blender_version,
    render,
    require_blender,
)
from isofightr.art.packer import compose, palette_bytes, trim, write_sheets
from isofightr.art.palettes import ART_SRC, TRANSPARENT_INDEX, CharacterPalettes, load_palettes
from isofightr.art.portraits import (
    BUST_SIZE,
    ICON_SCALE,
    ICON_SIZE,
    PORTRAIT_FACING,
    crop_top,
)
from isofightr.data.paths import CHARACTERS_DIR
from isofightr.sim.input_frame import Dir8

SPRITES_DIR_NAME = "sprites"


def main() -> None:
    """Parse arguments, render, pack and report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("character")
    parser.add_argument("--anim", action="append", help="render only these (repeatable)")
    parser.add_argument("--force", action="store_true", help="ignore cached renders")
    args = parser.parse_args()

    character = args.character
    palettes = load_palettes(character)
    names = list_anims(character)
    timings = [load_timing(character, name) for name in names]
    blender = require_blender()
    out = BUILD_DIR / character
    job = RenderJob(
        character,
        ART_SRC / "characters" / character / "rig.toml",
        ART_SRC / "characters" / character / "poses.toml",
        tuple(material.name for material in palettes.materials),
        {name: anims_dir(character) / f"{name}.toml" for name in (args.anim or names)},
        out,
    )
    started = time.perf_counter()
    rendered = render(blender, job, force=args.force)
    print(f"rendered {len(rendered)} animations in {time.perf_counter() - started:.1f} s")

    started = time.perf_counter()
    frames = []
    for timing in timings:
        for pose in range(timing.poses):
            for facing in Dir8:
                stem = out / timing.name / f"{pose:02d}_{facing.name}"
                composed = compose(
                    Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes
                )
                frames.append(trim(f"{timing.name}/{pose}/{facing.name}", composed, PIVOT))
    data = write_sheets(
        CHARACTERS_DIR / character / SPRITES_DIR_NAME,
        character,
        frames,
        timings,
        palettes,
        blender_version(blender),
    )
    print(
        f"packed {len(frames)} frames into {len(data['sheets'])} sheets "
        f"in {time.perf_counter() - started:.1f} s"
    )
    build_portraits(blender, job, palettes)


def build_portraits(blender: Path, job: RenderJob, palettes: CharacterPalettes) -> None:
    """Render ``portrait.toml`` facing the viewer at full and half scale; cut the bust and
    the stock icon; save them indexed next to the sheets."""
    source = ART_SRC / "characters" / job.character_id / "portrait.toml"
    if not source.is_file():
        return
    folder = CHARACTERS_DIR / job.character_id / SPRITES_DIR_NAME
    for name, scale, size in (("bust", 1.0, BUST_SIZE), ("icon", ICON_SCALE, ICON_SIZE)):
        out = job.out / f"_{name}"
        render(
            blender,
            replace(
                job, anims={"portrait": source}, out=out, scale=scale, directions=(PORTRAIT_FACING,)
            ),
        )
        stem = out / "portrait" / f"00_{PORTRAIT_FACING}"
        composed = compose(Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes)
        image = crop_top(composed, size).convert("P")
        image.putpalette(palette_bytes(palettes.costumes[0]))
        image.save(folder / f"{name}.png", transparency=TRANSPARENT_INDEX, optimize=True)
    print("portraits: bust.png, icon.png")


if __name__ == "__main__":
    main()
