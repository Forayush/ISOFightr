"""Stage block images from a rendered tileset, clipped to the game's exact block shape.

Plan note "03 - Isometric World and Rendering" ("Rendering 3D source art") and decision D-044:
a rendered block is cut to the same pixels as the procedural block (``placeholder_art``), so
tiles still tessellate and the depth sorter's geometry (D-019) does not change. A tile the
tileset does not have, or one taller than its render, falls back to the procedural block.

Decision D-063 adds, all inside that same shape: **variants** (a cell shows one of its tile's
images, chosen by :func:`~isofightr.data.tileset_art.variant_index`), a **rim** (the top's
edge is one light band brighter where it borders the void or lower ground, and one darker at
the foot of higher ground) and the **under** blocks that hang below an island, whose bottom
edge is cut ragged. Shading moves a pixel along its material's own ramp, so every colour
stays in the tileset's palette.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from typing import Final

from PIL import Image

from isofightr.config import TILE_H, TILE_W
from isofightr.data.tileset_art import TilesetArt, variant_index
from isofightr.render import placeholder_art as art
from isofightr.sim.stage import Stage

LIGHT_COSTUME: Final[int] = 0
DARK_COSTUME: Final[int] = 1
DECK_TILE: Final[str] = "deck"
GAP_SEARCH: Final[int] = 3
"""How far (in pixels) to look for a rendered colour to fill an edge gap with."""
RAMP_LENGTH: Final[int] = 5
"""Palette indices per material: four light bands, brightest first, then the outline."""
LIGHT_BANDS: Final[int] = 4
EDGE_NONE: Final[int] = 0
EDGE_RIM: Final[int] = 1
"""The edge borders the void or lower ground: a bright rim."""
EDGE_FOOT: Final[int] = 2
"""The edge is at the foot of higher ground: a contact shadow."""
Edges = tuple[int, int, int, int]
"""The state of a cell top's four edges: toward -x, +x, -y, +y."""
NO_EDGES: Final[Edges] = (EDGE_NONE, EDGE_NONE, EDGE_NONE, EDGE_NONE)
RIM_WIDTH: Final[float] = 0.13
"""How far in from the edge the rim reaches, in units (two pixels)."""
STEP_HEIGHT: Final[float] = 0.25
"""Ground this much lower (or higher) than a cell counts as a drop (or a wall) beside it."""
TEETH_WIDTH: Final[int] = 4
TEETH_DEPTHS: Final[tuple[int, ...]] = (0, 3, 1, 5, 2, 0, 4, 1)
"""How many pixels each tooth of an under block's ragged bottom is cut back."""


def cell_edges(stage: Stage, cx: int, cy: int) -> Edges:
    """Return the state of each edge of a cell's top, from what lies beside it."""
    cell = stage.cell(cx, cy)
    if cell is None:
        return NO_EDGES
    states = []
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        near = stage.cell(cx + dx, cy + dy)
        if near is None or near.top <= cell.top - STEP_HEIGHT:
            states.append(EDGE_RIM)
        elif near.top >= cell.top + STEP_HEIGHT:
            states.append(EDGE_FOOT)
        else:
            states.append(EDGE_NONE)
    return (states[0], states[1], states[2], states[3])


def tile_variant(tileset: TilesetArt, tile: str, cx: int, cy: int) -> int:
    """Return which variant of a tile the cell ``(cx, cy)`` shows."""
    return variant_index(cx, cy, len(tileset.variants(tile)))


class StageArt:
    """Block images for one tileset, made on demand and cached."""

    def __init__(self, tileset: TilesetArt) -> None:
        """Remember the tileset; images are opened when first needed."""
        self.tileset = tileset
        self._indexed: dict[str, Image.Image] = {}
        self._images: dict[tuple[str, bool, int, int, Edges], Image.Image | None] = {}
        self._under: dict[tuple[str, int, int], Image.Image | None] = {}

    def tile(
        self, tile: str, light: bool, side_px: int, variant: int = 0, edges: Edges = NO_EDGES
    ) -> Image.Image | None:
        """Return a block ``side_px`` tall below its top diamond, or ``None`` to fall back.

        ``variant`` picks among the tile's images (it wraps); ``edges`` says which edges of
        the top get a rim or a contact shadow.
        """
        key = (tile, light, side_px, variant, edges)
        if key not in self._images:
            self._images[key] = self._build(tile, light, side_px, variant, edges)
        return self._images[key]

    def deck(self, light: bool, variant: int = 0) -> Image.Image | None:
        """Return one cell of a soft platform deck."""
        return self.tile(DECK_TILE, light, art.DECK_SIDE_PX, variant)

    def under(self, tile: str, side_px: int, variant: int = 0) -> Image.Image | None:
        """Return a block that hangs under the island: the tile's image with its bottom edge
        cut into uneven teeth (never outside the block's shape)."""
        key = (tile, side_px, variant)
        if key not in self._under:
            block = self.tile(tile, True, side_px, variant)
            self._under[key] = None if block is None else _ragged(block, variant)
        return self._under[key]

    def prop(self, name: str, frame: int) -> Image.Image:
        """Return one frame of a prop, in the tileset's light colours."""
        entry = self.tileset.prop(name)
        if entry is None:
            raise KeyError(f"tileset {self.tileset.tileset_id} has no prop {name!r}")
        strip = self._indexed.get(f"prop:{name}")
        if strip is None:
            strip = Image.open(self.tileset.prop_path(name)).convert("P")
            self._indexed[f"prop:{name}"] = strip
        left = (frame % entry.frames) * entry.width
        cut = strip.crop((left, 0, left + entry.width, entry.height))
        cut.putpalette(self._palette(LIGHT_COSTUME), rawmode="RGBA")
        return cut.convert("RGBA")

    def _palette(self, costume_index: int) -> list[int]:
        flat = [0, 0, 0, 0]
        for red, green, blue in self.tileset.costumes[costume_index][1:]:
            flat += [red, green, blue, 255]
        return flat + [0] * (256 * 4 - len(flat))

    def _build(
        self, tile: str, light: bool, side_px: int, variant: int, edges: Edges
    ) -> Image.Image | None:
        names = self.tileset.variants(tile)
        if not names or side_px > self.tileset.depth_px:
            return None
        name = names[variant % len(names)]
        path = self.tileset.tile_path(name)
        assert path is not None
        indexed = self._indexed.get(name)
        if indexed is None:
            indexed = Image.open(path).convert("P")
            self._indexed[name] = indexed
        coloured = indexed.copy()
        if edges != NO_EDGES:
            _shade_edges(coloured, edges)
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


def _shade_edges(indexed: Image.Image, edges: Edges) -> None:
    """Move the pixels along the top diamond's marked edges one light band along their own
    material's ramp: brighter for a rim, darker at the foot of higher ground."""
    pixels = indexed.load()
    assert pixels is not None
    west, east, north, south = edges
    for py in range(TILE_H):
        for px in range(TILE_W):
            index = pixels[px, py]
            if not index:
                continue
            # The pixel's place on the cell's top: u along +x, v along +y, each 0..1.
            across = (px + 0.5 - TILE_W / 2) / (TILE_W / 2)
            down = (py + 0.5) / (TILE_H / 2)
            u, v = (down + across) / 2, (down - across) / 2
            if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
                continue
            near = [
                state
                for state, distance in ((west, u), (east, 1 - u), (north, v), (south, 1 - v))
                if state and distance < RIM_WIDTH
            ]
            if not near:
                continue
            material, band = divmod(index - 1, RAMP_LENGTH)
            if band >= LIGHT_BANDS:
                continue  # an outline pixel keeps its colour
            band = min(band + 1, LIGHT_BANDS - 1) if EDGE_FOOT in near else max(band - 1, 0)
            pixels[px, py] = 1 + material * RAMP_LENGTH + band


def _ragged(block: Image.Image, variant: int) -> Image.Image:
    """Return a copy of a block with its bottom edge cut back in teeth."""
    image = block.copy()
    pixels = image.load()
    assert pixels is not None
    width, height = image.size
    for x in range(width):
        cut = TEETH_DEPTHS[(x // TEETH_WIDTH + variant * 3) % len(TEETH_DEPTHS)]
        y = height - 1
        while y >= 0 and not pixels[x, y][3]:
            y -= 1
        for row in range(y, max(y - cut, TILE_H), -1):
            pixels[x, row] = (0, 0, 0, 0)
    return image
