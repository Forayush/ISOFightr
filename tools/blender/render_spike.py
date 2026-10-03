"""Projection check (runs inside Blender): render shapes the game also draws procedurally.

``blender -b --factory-startup --python tools/blender/render_spike.py -- OUT_DIR``

- ``block``: a unit cube whose top is at z = 0 and whose sides hang 1 unit, as a stage cell.
- ``capsule``: an upright cylinder the size of Rook's body (radius 0.30, height 2.5).

Both are rendered on the fighter canvas (128 x 128, world origin at pixel corner (64, 96)).
``tests/test_art_blender.py`` compares them with ``placeholder_art``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import isoscene
import shapes

CANVAS = (128, 128)
PIVOT = (64, 96)


def main(out_dir: Path) -> None:
    for name, build in (
        ("block", lambda root: shapes.box("block", (0, 0, -1), (1, 1, 0), 1, root)),
        ("capsule", lambda root: shapes.cylinder("body", 0.30, 0.0, 2.5, 2, root)),
    ):
        scene = isoscene.reset_scene()
        isoscene.setup_camera(scene, *CANVAS, PIVOT)
        isoscene.setup_sun(scene)
        build(isoscene.root())
        isoscene.render_passes(scene, out_dir / f"{name}_id.png", out_dir / f"{name}_light.png")
    print("RENDER_DONE")


if __name__ == "__main__":
    main(Path(sys.argv[sys.argv.index("--") + 1]))
