"""Textures for a character's packed sprites, in any costume (decisions D-013, D-045).

Plan note "10 - Animation and Asset Pipeline" ("Runtime loading"). The sheets are indexed
PNGs, so a costume is applied by giving a sheet a different palette: no per-pixel work. The hit
flash (all white) and the helpless dimming are palettes too. Textures are made the first time a
frame is drawn in a costume and kept for the rest of the match; :meth:`SpriteBank.warm` makes
a whole costume up front.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

import arcade
from PIL import Image

from isofightr.data.sprite_sheet import FrameRect, SpriteSet
from isofightr.render.placeholder_art import DIM_SHADE
from isofightr.sim.input_frame import Dir8

PALETTE_ENTRIES: Final[int] = 256
FLASH_COLOR: Final[tuple[int, int, int]] = (255, 255, 255)


class Tint(Enum):
    """How a costume is drawn."""

    NORMAL = "normal"
    FLASH = "flash"
    """Solid white: the hit flash and the smash charge blink."""
    DIM = "dim"
    """Darkened: helpless."""


class SpriteBank:
    """One character's sprite textures, made on demand."""

    def __init__(self, sprite_set: SpriteSet) -> None:
        """Open the sheets (they stay indexed until a costume is asked for)."""
        self.sprite_set = sprite_set
        self._sheets = [
            Image.open(sprite_set.folder / name).convert("P") for name in sprite_set.sheets
        ]
        self._coloured: dict[tuple[int, Tint], list[Image.Image]] = {}
        self._textures: dict[tuple[str, int, Dir8, int, Tint], arcade.Texture] = {}

    def frame(self, anim: str, pose: int, facing: Dir8) -> FrameRect:
        """Return a frame's rect and pivot."""
        return self.sprite_set.frame(anim, pose, facing.name)

    def texture(
        self, anim: str, pose: int, facing: Dir8, costume: int, tint: Tint = Tint.NORMAL
    ) -> arcade.Texture:
        """Return the texture of one frame in a costume."""
        key = (anim, pose, facing, costume, tint)
        texture = self._textures.get(key)
        if texture is None:
            rect = self.frame(anim, pose, facing)
            sheet = self._coloured_sheets(costume, tint)[rect.sheet]
            image = sheet.crop((rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))
            texture = arcade.Texture(
                image,
                hit_box_algorithm=arcade.hitbox.algo_bounding_box,
                hash=f"sprite:{self.sprite_set.character_id}:{anim}:{pose}:{facing.name}:"
                f"{costume}:{tint.value}",
            )
            self._textures[key] = texture
        return texture

    def warm(self, costume: int) -> None:
        """Make every normal texture of a costume now (at match start, not mid-fight)."""
        for key in self.sprite_set.frames:
            anim, pose, direction = key.split("/")
            self.texture(anim, int(pose), Dir8[direction], costume)

    def _coloured_sheets(self, costume: int, tint: Tint) -> list[Image.Image]:
        sheets = self._coloured.get((costume, tint))
        if sheets is None:
            palette = _palette(self.sprite_set.costumes[costume][1], tint)
            sheets = []
            for indexed in self._sheets:
                copy = indexed.copy()
                copy.putpalette(palette, rawmode="RGBA")
                sheets.append(copy.convert("RGBA"))
            self._coloured[(costume, tint)] = sheets
        return sheets


def _palette(colors: tuple[tuple[int, int, int], ...], tint: Tint) -> list[int]:
    """Return a flat RGBA palette; index 0 is transparent."""
    flat = [0, 0, 0, 0]
    for red, green, blue in colors[1:]:
        if tint is Tint.FLASH:
            red, green, blue = FLASH_COLOR
        elif tint is Tint.DIM:
            red, green, blue = (round(value * DIM_SHADE) for value in (red, green, blue))
        flat += [red, green, blue, 255]
    return flat + [0] * (PALETTE_ENTRIES * 4 - len(flat))
