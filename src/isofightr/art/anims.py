"""Animation timing from ``art_src/characters/<id>/anims/<anim>.toml`` (decision D-047).

The Blender scripts read the same files for the joint rotations; this module only needs to know
how the poses are timed:

- a **loop** (``loop = true``) plays its poses at ``fps``;
- anything else is a **timed** animation: every pose has a ``start``, the 1-indexed move (or
  state) frame it appears on. The first pose starts on frame 1 and starts only increase. The
  last pose is held for good, unless the animation sets ``repeat_from`` (a pose number, from 1)
  and ``length`` (its last frame): after ``length`` it carries on from that pose's start again,
  so a victory can play its flourish once and then repeat a celebration.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from isofightr.art.palettes import ART_SRC

POSE_KEYS: Final[frozenset[str]] = frozenset({"offset", "show", "start", "use"})
"""Keys a pose may hold besides joint rotations."""
ANIM_KEYS: Final[frozenset[str]] = frozenset(
    {"loop", "fps", "base", "poses", "smears", "parts", "repeat_from", "length"}
)


class AnimError(ValueError):
    """An animation file is malformed."""


@dataclass(frozen=True, slots=True)
class AnimTiming:
    """How an animation's poses are timed."""

    name: str
    poses: int
    loop: bool
    fps: int = 0
    """Poses per second (loops only)."""
    starts: tuple[int, ...] = ()
    """The frame each pose starts on (timed animations only)."""
    repeat_from: int = 0
    """The pose (from 1) a timed animation repeats from after ``length``; 0 holds its last."""
    length: int = 0
    """The last frame before a repeating animation goes back to ``repeat_from``."""


def anims_dir(character_id: str, root: Path = ART_SRC) -> Path:
    """Return the folder holding a character's animation files."""
    return root / "characters" / character_id / "anims"


def list_anims(character_id: str, root: Path = ART_SRC) -> list[str]:
    """Return a character's animation names, sorted."""
    return sorted(path.stem for path in anims_dir(character_id, root).glob("*.toml"))


def list_anims_in(folder: Path) -> list[str]:
    """Return the animation (or tile) names in an art source folder's ``anims``, sorted."""
    return sorted(path.stem for path in (folder / "anims").glob("*.toml"))


def load_timing(character_id: str, name: str, root: Path = ART_SRC) -> AnimTiming:
    """Load one animation's timing."""
    path = anims_dir(character_id, root) / f"{name}.toml"
    return parse_timing(name, tomllib.loads(path.read_text(encoding="utf-8")))


def parse_timing(name: str, data: dict[str, Any]) -> AnimTiming:
    """Validate an animation's top level and timing; joint names are checked in Blender."""
    unknown = set(data) - ANIM_KEYS
    if unknown:
        raise AnimError(f"{name}: unknown keys {sorted(unknown)}")
    poses = data.get("poses", [])
    if not poses:
        raise AnimError(f"{name}: no poses")
    loop = bool(data.get("loop", False))
    if loop:
        fps = data.get("fps")
        if not isinstance(fps, int) or fps <= 0:
            raise AnimError(f"{name}: a loop needs a positive integer fps")
        if any("start" in pose for pose in poses):
            raise AnimError(f"{name}: a loop's poses have no start frames")
        if "repeat_from" in data or "length" in data:
            raise AnimError(f"{name}: a loop repeats by itself (no repeat_from or length)")
        return AnimTiming(name, len(poses), True, fps=fps)
    if "fps" in data:
        raise AnimError(f"{name}: only loops have an fps")
    starts = []
    for index, pose in enumerate(poses):
        start = pose.get("start")
        if not isinstance(start, int):
            raise AnimError(f"{name}: pose {index + 1} needs a start frame")
        starts.append(start)
    if starts[0] != 1 or any(later <= earlier for earlier, later in pairwise(starts)):
        raise AnimError(f"{name}: starts must begin at 1 and increase: {starts}")
    repeat_from, length = _repeat(name, data, starts)
    return AnimTiming(
        name, len(poses), False, starts=tuple(starts), repeat_from=repeat_from, length=length
    )


def _repeat(name: str, data: dict[str, Any], starts: list[int]) -> tuple[int, int]:
    """Return a timed animation's ``(repeat_from, length)``, or ``(0, 0)`` if it holds."""
    if "repeat_from" not in data and "length" not in data:
        return 0, 0
    repeat_from, length = data.get("repeat_from"), data.get("length")
    if not isinstance(repeat_from, int) or not 1 <= repeat_from <= len(starts):
        raise AnimError(f"{name}: repeat_from must be a pose number from 1 to {len(starts)}")
    if not isinstance(length, int) or length < starts[-1]:
        raise AnimError(f"{name}: length must be a frame at or after the last start")
    return repeat_from, length
