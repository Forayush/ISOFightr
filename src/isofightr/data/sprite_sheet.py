"""Reads a character's packed sprites: ``assets/characters/<id>/sprites/sprites.json``.

Plan note "10 - Animation and Asset Pipeline" ("Runtime loading"), decisions D-045 to D-047.
The sheets are indexed PNGs; the JSON says where each frame is, where its feet pivot is, how
each animation is timed, and the colours of every costume. Pure Python (no ``arcade``); the
textures are made by ``render/sprite_bank.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from isofightr.config import TICK_RATE
from isofightr.data.paths import CHARACTERS_DIR

SPRITES_DIR_NAME: Final[str] = "sprites"
SPRITES_FILE_NAME: Final[str] = "sprites.json"
SUPPORTED_FORMAT: Final[int] = 1

Rgb = tuple[int, int, int]


class SpriteSheetError(ValueError):
    """``sprites.json`` is malformed."""


@dataclass(frozen=True, slots=True)
class FrameRect:
    """Where one frame sits in a sheet, and where its feet pivot is."""

    sheet: int
    x: int
    y: int
    width: int
    height: int
    pivot_x: int
    """From the frame's left edge, in pixel edges."""
    pivot_y: int
    """From the frame's top edge (image rows grow downward)."""


@dataclass(frozen=True, slots=True)
class AnimInfo:
    """How an animation's poses are timed (decision D-047)."""

    poses: int
    loop: bool
    fps: int = 0
    starts: tuple[int, ...] = ()

    def pose_at(self, frame: int) -> int:
        """Return the pose shown on a 1-indexed frame of the animation."""
        if self.loop:
            return ((max(frame, 1) - 1) * self.fps // TICK_RATE) % self.poses
        pose = 0
        for index, start in enumerate(self.starts):
            if start <= frame:
                pose = index
        return pose


@dataclass(frozen=True, slots=True)
class SpriteSet:
    """Everything ``sprites.json`` says about one character's sprites."""

    character_id: str
    folder: Path
    sheets: tuple[str, ...]
    costumes: tuple[tuple[str, tuple[Rgb, ...]], ...]
    """``(name, colour per palette index)``; index 0 is transparent."""
    anims: dict[str, AnimInfo]
    frames: dict[str, FrameRect]
    """By ``"<anim>/<pose>/<direction>"``."""

    def frame(self, anim: str, pose: int, direction: str) -> FrameRect:
        """Return one frame's rect."""
        return self.frames[f"{anim}/{pose}/{direction}"]

    def portrait_path(self, name: str) -> Path | None:
        """Return ``bust.png`` or ``icon.png`` if the character has it."""
        path = self.folder / f"{name}.png"
        return path if path.is_file() else None


def sprites_folder(character_id: str, characters_dir: Path = CHARACTERS_DIR) -> Path:
    """Return where a character's sheets live."""
    return characters_dir / character_id / SPRITES_DIR_NAME


def load_sprite_set(character_id: str, characters_dir: Path = CHARACTERS_DIR) -> SpriteSet | None:
    """Load a character's sprites, or return ``None`` if it has none (placeholder art)."""
    folder = sprites_folder(character_id, characters_dir)
    path = folder / SPRITES_FILE_NAME
    if not path.is_file():
        return None
    return parse_sprite_set(json.loads(path.read_text(encoding="utf-8")), folder)


def parse_sprite_set(data: dict[str, object], folder: Path) -> SpriteSet:
    """Validate parsed ``sprites.json`` data."""
    if data.get("format") != SUPPORTED_FORMAT:
        raise SpriteSheetError(f"unsupported sprites.json format {data.get('format')!r}")
    try:
        anims = {
            name: AnimInfo(
                poses=int(info["poses"]),
                loop=bool(info["loop"]),
                fps=int(info.get("fps", 0)),
                starts=tuple(int(start) for start in info.get("starts", ())),
            )
            for name, info in data["anims"].items()  # type: ignore[attr-defined]
        }
        frames = {
            key: FrameRect(*(int(value) for value in rect))
            for key, rect in data["frames"].items()  # type: ignore[attr-defined]
        }
        costumes = tuple(
            (
                str(costume["name"]),
                tuple(
                    (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
                    for color in costume["colors"]
                ),
            )
            for costume in data["costumes"]  # type: ignore[attr-defined]
        )
        sheets = tuple(str(name) for name in data["sheets"])  # type: ignore[attr-defined]
    except (KeyError, TypeError, ValueError) as error:
        raise SpriteSheetError(f"malformed sprites.json: {error}") from error
    for key, rect in frames.items():
        if not 0 <= rect.sheet < len(sheets):
            raise SpriteSheetError(f"{key}: no sheet {rect.sheet}")
    if not costumes:
        raise SpriteSheetError("no costumes")
    return SpriteSet(str(data["character"]), folder, sheets, costumes, anims, frames)
