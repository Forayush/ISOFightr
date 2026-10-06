"""Renders a character's animations in every direction (runs inside Blender).

``blender -b --factory-startup --python tools/blender/render_character.py -- JOB.json``

The job (written by ``isofightr.art.blender``) names the rig, the material order, the
animations to render, the eight directions (already in Blender space), the canvas and the
output folder. Each pose and direction becomes
``<out>/<anim>/<pose:02d>_<direction>_id.png`` and ``..._light.png``.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import isoscene
from rig import Rig, load_library, merged_poses


def main(job_path: Path) -> None:
    job = json.loads(job_path.read_text(encoding="utf-8"))
    scene = isoscene.reset_scene()
    elevation = job.get("elevation", isoscene.ELEVATION_DEGREES)
    isoscene.setup_camera(
        scene, *job["canvas"], tuple(job["pivot"]), job.get("scale", 1.0), elevation
    )
    isoscene.setup_sun(scene, elevation)
    if job.get("z_squash") is not None:
        # Hero art is not laid over the game's tiles, so it can keep true proportions.
        isoscene.root().scale = (1.0, 1.0, job["z_squash"])
    rig = Rig(Path(job["rig"]), job["materials"], isoscene.root())
    library = load_library(Path(job["library"]))
    out = Path(job["out"])
    for anim in job["anims"]:
        data = tomllib.loads(Path(anim["path"]).read_text(encoding="utf-8"))
        smears = rig.add_smears(data.get("smears", [])) + rig.add_parts(data.get("parts", []))
        for pose_index, pose in enumerate(merged_poses(data, library)):
            rig.pose(pose)
            for direction in job["directions"]:
                rig.face(tuple(direction["blender"]))
                stem = out / anim["name"] / f"{pose_index:02d}_{direction['name']}"
                isoscene.render_passes(
                    scene,
                    stem.with_name(stem.name + "_id.png"),
                    stem.with_name(stem.name + "_light.png"),
                )
        rig.remove(smears)
    print("RENDER_DONE")


if __name__ == "__main__":
    main(Path(sys.argv[sys.argv.index("--") + 1]))
