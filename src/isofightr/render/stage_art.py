"""Stage block images from a rendered tileset, clipped to the game's exact block shape.

Plan note "03 - Isometric World and Rendering" ("Rendering 3D source art") and decision D-044:
a rendered block is cut to the same pixels as the procedural block (``placeholder_art``), so
tiles still tessellate and the depth sorter's geometry (D-019) does not change. A tile the
tileset does not have, or one taller than its render, falls back to the procedural block.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image

from isofightr.config import TILE_H, TILE_W
from isofightr.data.tileset_art import TilesetArt
from isofightr.render import placeholder_art as art

LIGHT_COSTUME: Final[int] = 0
DARK_COSTUME: Final[int] = 1
DECK_TILE: Final[str] = "deck"
GAP_SEARCH: Final[int] = 3
"""How far (in pixels) to look for a rendered colour to fill an edge gap with."""


class StageArt:
    """Block images for one tileset, made on demand and cached."""

    def __init__(self, tileset: TilesetArt) -> None:
        """Remember the tileset; images are opened when first needed."""
        self.tileset = tileset
        self._indexed: dict[str, Image.Image] = {}
        self._images: dict[tuple[str, bool, int], Image.Image | None] = {}

    def tile(self, tile: str, light: bool, side_px: int) -> Image.Image | None:
        """Return a block ``side_px`` tall below its top diamond, or ``None`` to fall back."""
        key = (tile, light, side_px)
        if key not in self._images:
            self._images[key] = self._build(tile, light, side_px)
        return self._images[key]

    def deck(self, light: bool) -> Image.Image | None:
        """Return one cell of a soft platform deck."""
        return self.tile(DECK_TILE, light, art.DECK_SIDE_PX)

    def _build(self, tile: str, light: bool, side_px: int) -> Image.Image | None:
        path = self.tileset.tile_path(tile)
        if path is None or side_px > self.tileset.depth_px:
            return None
        indexed = self._indexed.get(tile)
        if indexed is None:
            indexed = Image.open(path).convert("P")
            self._indexed[tile] = indexed
        coloured = indexed.copy()
        costume = self.tileset.costumes[LIGHT_COSTUME if light else DARK_COSTUME]
        flat = [0, 0, 0, 0]
        for red, green, blue in costume[1:]:
            flat += [red, green, blue, 255]
        coloured.putpalette(flat + [0] * (256 * 4 - len(flat)), rawmode="RGBA")
        image = coloured.convert("RGBA").crop((0, 0, TILE_W, TILE_H + side_px))
        shape = art.build_block(art.tile_palette(tile), light, side_px).getchannel("A")
        clipped = Image.new("RGBA", image.size)
        clipped.paste(image, (0, 0), shape)
        _fill_edge_gaps(clipped, shape)
        return clipped


def _fill_edge_gaps(image: Image.Image, shape: Image.Image) -> None:
    """Fill pixels inside the block shape that the render left empty (the stair-step pixels
    of the slanted edges) with the nearest rendered neighbour's colour."""
    pixels = image.load()
    mask = shape.load()
    assert pixels is not None and mask is not None
    width, height = image.size
    gaps = [
        (x, y) for y in range(height) for x in range(width) if mask[x, y] and not pixels[x, y][3]
    ]
    for x, y in gaps:
        for radius in range(1, GAP_SEARCH + 1):
            near = [
                pixels[x + dx, y + dy]
                for dx, dy in ((0, radius), (0, -radius), (radius, 0), (-radius, 0))
                if 0 <= x + dx < width and 0 <= y + dy < height and pixels[x + dx, y + dy][3]
            ]
            if near:
                pixels[x, y] = near[0]
                break
