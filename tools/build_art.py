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
import json
import time
from dataclasses import replace
from pathlib import Path

from PIL import Image

from isofightr.art.anims import anims_dir, list_anims, list_anims_in, load_timing
from isofightr.art.blender import (
    BUILD_DIR,
    PIVOT,
    TURNED_VIEW,
    RenderJob,
    blender_version,
    render,
    require_blender,
)
from isofightr.art.hero import (
    HERO_CANVAS,
    HERO_FILE,
    HERO_PIVOT,
    HERO_SCALE,
    INDEX_FILE,
    MARGIN,
    TILE_SCALE,
    TILE_SIZE,
    HeroCamera,
    character_dir,
    has_hero,
    load_camera,
    source_hash,
    win_pose_file,
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
UI_DIR_NAME = "ui"
"""Where a character's hero art goes, next to its ``sprites`` folder."""


def main() -> None:
    """Parse arguments, render, pack and report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("character")
    parser.add_argument("--anim", action="append", help="render only these (repeatable)")
    parser.add_argument("--force", action="store_true", help="ignore cached renders")
    parser.add_argument(
        "--hero",
        action="store_true",
        help="render and pack only the hero art (hero.toml), not the sprite sheets",
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
        build_hero(blender, character, palettes, args.force)
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
    build_hero(blender, character, palettes, args.force)


def _hero_job(
    character: str, palettes: CharacterPalettes, name: str, pose_file: Path, camera: HeroCamera
) -> RenderJob:
    source = character_dir(character)
    return RenderJob(
        character,
        source / "rig.toml",
        source / "poses.toml",
        tuple(material.name for material in palettes.materials),
        {name: pose_file},
        BUILD_DIR / character / "_hero",
        scale=float(HERO_SCALE),
        canvas=HERO_CANVAS,
        pivot=HERO_PIVOT,
        elevation=camera.elevation,
        z_squash=1.0,
        turn=camera.turn,
    )


def _save_indexed(image: Image.Image, palettes: CharacterPalettes, path: Path) -> None:
    indexed = image.convert("P")
    indexed.putpalette(palette_bytes(palettes.costumes[0]))
    indexed.save(path, transparency=TRANSPARENT_INDEX, optimize=True)


def build_hero(blender: Path, character: str, palettes: CharacterPalettes, force: bool) -> None:
    """Render a character's hero art (``hero.toml``), its win picture (the first pose of the
    ``victory`` animation from the same camera) and its roster tile (the portrait pose), and
    save them indexed in ``assets/characters/<id>/ui/`` with ``ui.json``."""
    if not has_hero(character):
        print(f"{character}: no {HERO_FILE}")
        return
    source = character_dir(character)
    camera = load_camera(character)
    folder = CHARACTERS_DIR / character / UI_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, pose_file in (
        ("hero", source / HERO_FILE),
        ("hero_win", win_pose_file(character)),
    ):
        job = _hero_job(character, palettes, name, pose_file, camera)
        render(blender, job, force=force)
        stem = job.out / name / f"00_{TURNED_VIEW}"
        composed = compose(Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes)
        box = composed.point(lambda value: 255 if value else 0).getbbox()
        assert box is not None, f"{character}: the {name} render is empty"
        left, top, right, bottom = box
        trimmed = Image.new(
            "L", (right - left + 2 * MARGIN, bottom - top + 2 * MARGIN), TRANSPARENT_INDEX
        )
        trimmed.paste(composed.crop(box), (MARGIN, MARGIN))
        _save_indexed(trimmed, palettes, folder / f"{name}.png")
        sizes[name] = list(trimmed.size)

    portrait = RenderJob(
        character,
        source / "rig.toml",
        source / "poses.toml",
        tuple(material.name for material in palettes.materials),
        {"portrait": source / "portrait.toml"},
        BUILD_DIR / character / "_tile",
        scale=TILE_SCALE,
        directions=(PORTRAIT_FACING,),
    )
    render(blender, portrait, force=force)
    stem = portrait.out / "portrait" / f"00_{PORTRAIT_FACING}"
    composed = compose(Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes)
    _save_indexed(crop_top(composed, TILE_SIZE), palettes, folder / "tile.png")
    sizes["tile"] = [TILE_SIZE, TILE_SIZE]

    index = {
        "character": character,
        "source": source_hash(character),
        "blender": blender_version(blender),
        "scale": HERO_SCALE,
        "camera": {"turn": camera.turn, "elevation": camera.elevation},
        "sizes": sizes,
    }
    (folder / INDEX_FILE).write_text(
        json.dumps(index, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"hero art: {', '.join(f'{name} {w}x{h}' for name, (w, h) in sizes.items())}")


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
