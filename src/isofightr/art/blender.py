"""Finds Blender and runs the render scripts in ``tools/blender`` (decision D-044).

Blender is a tool dependency, not a runtime one: only ``tools/build_art.py`` and the
``blender`` test marker need it. Its own Python cannot import ``isofightr``, so everything the
scripts need from the game (direction vectors, the canvas) is written to a JSON job file.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from isofightr.data.paths import REPO_ROOT
from isofightr.sim.input_frame import Dir8

BLENDER_ENV: Final[str] = "ISOFIGHTR_BLENDER"
DEFAULT_BLENDER: Final[Path] = Path(r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe")
SCRIPTS_DIR: Final[Path] = REPO_ROOT / "tools" / "blender"
BUILD_DIR: Final[Path] = REPO_ROOT / "build" / "art"
CANVAS: Final[tuple[int, int]] = (128, 128)
"""Render canvas in pixels; frames are trimmed afterwards."""
PIVOT: Final[tuple[int, int]] = (64, 96)
"""The pixel corner, from the canvas's top-left, where the feet (world origin) land."""
GAME_ELEVATION: Final[float] = 30.0
"""Degrees the game's camera looks down (``tools/blender/isoscene.py``)."""
TURNED_VIEW: Final[str] = "VIEW"
"""The name of the single view a job with a ``turn`` renders."""
RENDER_TIMEOUT_SECONDS: Final[int] = 3600
VERSION_TIMEOUT_SECONDS: Final[int] = 60


class BlenderError(RuntimeError):
    """Blender is missing or a render failed."""


def find_blender() -> Path | None:
    """Return the Blender executable: ``ISOFIGHTR_BLENDER`` if set, else the default install."""
    override = os.environ.get(BLENDER_ENV)
    if override:
        path = Path(override)
        return path if path.is_file() else None
    return DEFAULT_BLENDER if DEFAULT_BLENDER.is_file() else None


def require_blender() -> Path:
    """Return the Blender executable or raise :class:`BlenderError` saying how to get it."""
    blender = find_blender()
    if blender is None:
        raise BlenderError(
            f"Blender 4.5 LTS not found. Install it (winget install BlenderFoundation.Blender "
            f"--version 4.5.5) or set {BLENDER_ENV} to blender.exe."
        )
    return blender


def blender_version(blender: Path) -> str:
    """Return Blender's version string, e.g. ``"4.5.5"``."""
    result = subprocess.run(
        [str(blender), "-b", "--factory-startup", "--version"],
        capture_output=True,
        text=True,
        check=True,
        timeout=VERSION_TIMEOUT_SECONDS,
    )
    match = re.search(r"Blender (\d+\.\d+\.\d+)", result.stdout)
    if match is None:
        raise BlenderError(f"cannot read Blender's version from: {result.stdout[:200]}")
    return match.group(1)


def blender_directions() -> list[dict[str, object]]:
    """Every facing as a Blender ground vector (game x and y swapped; see ``isoscene.py``)."""
    return [{"name": facing.name, "blender": [facing.world.y, facing.world.x]} for facing in Dir8]


def _directions(job: RenderJob) -> list[dict[str, object]]:
    if job.turn is not None:
        toward_viewer = Dir8.S.world
        angle = math.radians(job.turn)
        x = toward_viewer.x * math.cos(angle) - toward_viewer.y * math.sin(angle)
        y = toward_viewer.x * math.sin(angle) + toward_viewer.y * math.cos(angle)
        return [{"name": TURNED_VIEW, "blender": [y, x]}]
    every = blender_directions()
    if not job.directions:
        return every
    return [direction for direction in every if direction["name"] in job.directions]


def run_script(blender: Path, script: str, job: Path) -> None:
    """Run ``tools/blender/<script>`` headless with a job file."""
    result = subprocess.run(
        [
            str(blender),
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(SCRIPTS_DIR / script),
            "--",
            str(job),
        ],
        capture_output=True,
        text=True,
        timeout=RENDER_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or "RENDER_DONE" not in result.stdout:
        tail = (result.stdout + result.stderr)[-3000:]
        raise BlenderError(f"{script} failed:\n{tail}")


@dataclass(frozen=True, slots=True)
class RenderJob:
    """One character's animations to render."""

    character_id: str
    rig: Path
    library: Path
    """``poses.toml``: named poses animations can ``use`` (may not exist)."""
    materials: tuple[str, ...]
    anims: dict[str, Path]
    out: Path
    scale: float = 1.0
    """Pixels per unit relative to the game (portrait icons render smaller)."""
    directions: tuple[str, ...] = ()
    """Facings to render (by ``Dir8`` name); empty means all eight."""
    canvas: tuple[int, int] = CANVAS
    pivot: tuple[int, int] = PIVOT
    elevation: float = GAME_ELEVATION
    """Degrees the camera looks down. Only hero art changes it (decision D-061)."""
    z_squash: float | None = None
    """Vertical scale of the model, or ``None`` for the game's (which makes renders match
    the game's projection). Hero art uses 1.0: true proportions."""
    turn: float | None = None
    """Hero art only: render one view, the character turned this many degrees from facing
    the viewer (positive turns it toward the screen's right). Replaces ``directions``."""


def stamp_for(job: RenderJob, anim: str) -> str:
    """Return a hash of everything that decides an animation's renders."""
    digest = hashlib.sha256()
    for path in (job.rig, job.library, job.anims[anim], *sorted(SCRIPTS_DIR.glob("*.py"))):
        digest.update(path.read_bytes() if path.is_file() else b"-")
    settings = [job.materials, job.canvas, job.pivot, _directions(job), job.scale]
    if job.elevation != GAME_ELEVATION or job.z_squash is not None:
        settings += [job.elevation, job.z_squash]
    digest.update(json.dumps(settings).encode())
    return digest.hexdigest()


def render(blender: Path, job: RenderJob, force: bool = False) -> list[str]:
    """Render every animation whose inputs changed since its last render.

    Returns the names of the animations rendered.
    """
    stale = []
    for anim in sorted(job.anims):
        stamp_path = job.out / anim / "stamp.txt"
        stamp = stamp_for(job, anim)
        if force or not stamp_path.is_file() or stamp_path.read_text() != stamp:
            stale.append(anim)
    if not stale:
        return []
    job.out.mkdir(parents=True, exist_ok=True)
    job_path = job.out / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "rig": str(job.rig),
                "library": str(job.library),
                "materials": list(job.materials),
                "anims": [{"name": anim, "path": str(job.anims[anim])} for anim in stale],
                "directions": _directions(job),
                "scale": job.scale,
                "canvas": list(job.canvas),
                "pivot": list(job.pivot),
                "elevation": job.elevation,
                "z_squash": job.z_squash,
                "out": str(job.out),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    for anim in stale:
        for old in (job.out / anim).glob("*.png"):
            old.unlink()
    run_script(blender, "render_character.py", job_path)
    for anim in stale:
        (job.out / anim / "stamp.txt").write_text(stamp_for(job, anim))
    return stale
