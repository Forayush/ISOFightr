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
from isofightr.art.packer import compose, trim, write_sheets
from isofightr.art.palettes import ART_SRC, load_palettes
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


if __name__ == "__main__":
    main()
