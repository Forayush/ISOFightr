"""Render a character or a tileset in Blender and pack it for the game.

Usage::

    uv run python tools/build_art.py rook               # render what changed, then pack
    uv run python tools/build_art.py rook --force       # re-render everything
    uv run python tools/build_art.py rook --anim idle   # only some animations (still packs all)
    uv run python tools/build_art.py grass_stone        # a tileset (art_src/tilesets/<id>)
    uv run python tools/build_art.py rook --hero        # only the hero art (hero.toml)

Renders go to ``build/art/<id>/`` (git-ignored). A character's sheets, ``sprites.json`` and
portraits go to ``assets/characters/<id>/sprites/``; a tileset's tile images and
``tileset.json`` to ``assets/tilesets/<id>/``. Plan note "10 - Animation and Asset Pipeline".
"""

import argparse
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

from isofightr.art.anims import anims_dir, list_anims, list_anims_in, load_timing
from isofightr.art.blender import (
    BUILD_DIR,
    PIVOT,
    RenderJob,
    blender_version,
    render,
    require_blender,
)
from isofightr.art.packer import compose, palette_bytes, trim, write_sheets
from isofightr.art.palettes import (
    ART_SRC,
    TRANSPARENT_INDEX,
    CharacterPalettes,
    load_palettes,
    load_palettes_in,
)
from isofightr.art.portraits import (
    BUST_SIZE,
    ICON_SCALE,
    ICON_SIZE,
    PORTRAIT_FACING,
    crop_top,
)
from isofightr.art.tileset import (
    TILE_CANVAS,
    TILE_FACING,
    TILE_PIVOT,
    cut_tile,
    write_tileset,
)
from isofightr.data.paths import CHARACTERS_DIR
from isofightr.data.tileset_art import TILESETS_DIR
from isofightr.sim.input_frame import Dir8

SPRITES_DIR_NAME = "sprites"
HERO_FACING = "S"
"""Hero art faces the viewer."""
HERO_SCALE = 3
"""Model scale of the hero art, in game pixels per unit (decision D-061)."""
HERO_CANVAS = (112, 112)
"""Canvas of the hero render at scale 1; it grows with the scale."""
HERO_PIVOT = (56, 92)
"""Where the feet land on that canvas, from its top-left."""


def main() -> None:
    """Parse arguments, render, pack and report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("character")
    parser.add_argument("--anim", action="append", help="render only these (repeatable)")
    parser.add_argument("--force", action="store_true", help="ignore cached renders")
    parser.add_argument(
        "--hero",
        action="store_true",
        help="render only the hero art (hero.toml) and write its preview images",
    )
    parser.add_argument(
        "--hero-scales",
        default="",
        help="with --hero: model scales to render for comparison, e.g. 2,3",
    )
    args = parser.parse_args()

    character = args.character
    if (ART_SRC / "tilesets" / character).is_dir():
        build_tileset(character, args.force)
        return
    palettes = load_palettes(character)
    names = list_anims(character)
    timings = [load_timing(character, name) for name in names]
    blender = require_blender()
    out = BUILD_DIR / character
    if args.hero:
        scales = [int(value) for value in args.hero_scales.split(",") if value] or [HERO_SCALE]
        for scale in scales:
            image = render_hero(blender, character, palettes, scale, args.force)
            target = out / f"hero_{scale}x.png"
            image.save(target)
            box = image.getbbox()
            print(f"hero art at {scale}x: {target} (drawn {box[2] - box[0]}x{box[3] - box[1]} px)")
        return
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


def render_hero(
    blender: Path, character: str, palettes: CharacterPalettes, scale: int, force: bool = False
) -> Image.Image:
    """Render a character's ``hero.toml`` pose facing the viewer at ``scale`` times the game's
    pixels per unit, and return it composed like a sprite (cel bands, outlines, the default
    costume) on a transparent canvas. More model per pixel, the same pixel size."""
    source = ART_SRC / "characters" / character
    out = BUILD_DIR / character / f"_hero{scale}"
    job = RenderJob(
        character,
        source / "rig.toml",
        source / "poses.toml",
        tuple(material.name for material in palettes.materials),
        {"hero": source / "hero.toml"},
        out,
        scale=float(scale),
        directions=(HERO_FACING,),
        canvas=(HERO_CANVAS[0] * scale, HERO_CANVAS[1] * scale),
        pivot=(HERO_PIVOT[0] * scale, HERO_PIVOT[1] * scale),
    )
    render(blender, job, force=force)
    stem = out / "hero" / f"00_{HERO_FACING}"
    composed = compose(Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes)
    indexed = composed.convert("P")
    indexed.putpalette(palette_bytes(palettes.costumes[0]))
    indexed.info["transparency"] = TRANSPARENT_INDEX
    return indexed.convert("RGBA")


def build_tileset(tileset_id: str, force: bool) -> None:
    """Render every tile of a tileset from the fixed camera and cut the blocks out."""
    source = ART_SRC / "tilesets" / tileset_id
    palettes = load_palettes_in(source)
    names = list_anims_in(source)
    blender = require_blender()
    job = RenderJob(
        tileset_id,
        source / "rig.toml",
        source / "poses.toml",
        tuple(material.name for material in palettes.materials),
        {name: source / "anims" / f"{name}.toml" for name in names},
        BUILD_DIR / "tilesets" / tileset_id,
        directions=(TILE_FACING,),
        canvas=TILE_CANVAS,
        pivot=TILE_PIVOT,
    )
    rendered = render(blender, job, force=force)
    tiles = {}
    for name in names:
        stem = job.out / name / f"00_{TILE_FACING}"
        composed = compose(Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes)
        tiles[name] = cut_tile(composed)
    write_tileset(TILESETS_DIR / tileset_id, tileset_id, tiles, palettes, blender_version(blender))
    print(f"tileset {tileset_id}: rendered {len(rendered)}, wrote {len(tiles)} tiles")


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
