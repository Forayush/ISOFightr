"""What is drawn between a stage and its backdrop so that the two never run together
(decision D-065).

Plan note "03 - Isometric World and Rendering" ("Separation from the backdrop"). Two
pictures, both made once from the stage when it loads and both anchored to the world, so they
move with the island and not with the backdrop's parallax:

- a **halo**: a thin rim round the island's outline, light where the island's own edge is
  dark (its sides, against a dark sky) and dark where that edge is light (its top, against a
  bright one). The two colours are the lightest and the darkest of the stage's own sky, so
  the rim belongs to the backdrop; it is solid for one pixel and dithered beyond.
- a **cast shadow** for stages that float over water: the island's footprint, dithered, on
  the surface below it.

Pure Python plus Pillow (no ``arcade``): the renderer only places the pictures.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from isofightr.config import TILE_H, TILE_W
from isofightr.data.backdrop_rules import colour_table, oklab
from isofightr.render.iso import project
from isofightr.render.underside import lowest_point
from isofightr.sim.stage import Stage

Rgb = tuple[int, int, int]
HALO_REACH: Final[int] = 3
"""How many pixels the halo reaches out from the island's outline."""
HALO_MIN_SHARE: Final[float] = 0.01
"""A sky colour must cover this much of the sky to be one of the halo's two."""
DARK_EDGE: Final[float] = 0.55
"""An edge of the island darker than this (OKLab lightness) gets the light rim."""
SURFACE_BELOW: Final[dict[str, float]] = {
    "lily_pads": 0.75,
    "storm_galleon": 0.75,
    "ember_forge": 1.0,
}
"""The stages that hang over a surface a shadow can fall on (a pond, the sea, a lake of
lava), and how far below the island's lowest point that surface lies, in units. Over open
sky a shadow would have nothing to lie on, and would slide against whatever cloud drifted
under it."""
POURS: Final[dict[str, str]] = {"ember_forge": "lavafall"}
"""Stages where something pours off the island, by the prop that pours: it is carried on
down to the surface below, so the island is joined to what lies under it."""
POUR_COLOURS: Final[tuple[Rgb, Rgb, Rgb]] = (
    (0xFB, 0xFF, 0x86),
    (0xF7, 0x96, 0x17),
    (0xEA, 0x4F, 0x36),
)
"""A pour of lava: its white-hot core, its flow, its cooling edge (the forge's own lava)."""
POUR_WIDTH: Final[int] = 5
SPLASH: Final[tuple[int, int]] = (26, 12)
"""The ring where a pour meets the surface: its width and height in pixels."""
WATER_STAGES: Final[frozenset[str]] = frozenset(SURFACE_BELOW)
"""The stages with a surface below them (the name is from when both were water)."""


def halo_colours(sky: Image.Image) -> tuple[Rgb, Rgb]:
    """Return the lightest and the darkest colour of a sky picture (light first), leaving out
    colours that cover almost none of it (a star, the sun's core)."""
    table = colour_table(sky)
    total = max(sum(table.values()), 1)
    common = [colour for colour, count in table.items() if count >= HALO_MIN_SHARE * total]
    ranked = sorted(common or list(table), key=lambda colour: oklab(colour)[0])
    return ranked[-1], ranked[0]


def build_halo(picture: Image.Image, light: Rgb, dark: Rgb, reach: int = HALO_REACH) -> Image.Image:
    """Return the halo for a picture of the stage alone (RGBA): ``reach`` pixels bigger on
    every side, empty where the stage is, and outside it a rim that is solid next to the
    outline and thins out beyond. Each rim pixel is ``light`` or ``dark``, whichever stands
    out from the part of the stage beside it."""
    size = (picture.width + 2 * reach, picture.height + 2 * reach)
    padded = Image.new("RGBA", size)
    padded.paste(picture.convert("RGBA"), (reach, reach))
    solid = padded.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    # How light the stage is near each pixel: the mean lightness of its solid pixels nearby.
    lightness = Image.new("L", size)
    lightness.putdata(
        [
            round(oklab((red, green, blue))[0] * 255) if alpha >= 128 else 0
            for red, green, blue, alpha in padded.getdata()
        ]
    )
    near_light = lightness.filter(ImageFilter.BoxBlur(reach + 1)).load()
    near_solid = solid.filter(ImageFilter.BoxBlur(reach + 1)).load()
    assert near_light is not None and near_solid is not None
    halo = Image.new("RGBA", size)
    out = halo.load()
    assert out is not None
    inner = solid
    for step in range(1, reach + 1):
        outer = inner.filter(ImageFilter.MaxFilter(3))
        ring = ImageChops.subtract(outer, inner).load()
        assert ring is not None
        for y in range(size[1]):
            for x in range(size[0]):
                if not ring[x, y]:
                    continue
                if step == 2 and (x + y) % 2:
                    continue
                if step >= 3 and ((x + y) % 2 or y % 2):
                    continue
                cover = near_solid[x, y]
                edge = near_light[x, y] / cover if cover else 0.0
                out[x, y] = (*(light if edge < DARK_EDGE else dark), 255)
        inner = outer
    return halo


def surface_level(stage: Stage) -> float:
    """Return the height of the surface below a stage (its pond, sea or lake)."""
    return lowest_point(stage) - SURFACE_BELOW.get(stage.id, 0.75)


def build_pour(length: int) -> Image.Image:
    """Return a pour carried on down to the surface: a thin fall ``length`` pixels long with
    a ring where it lands (the ring's middle is the picture's bottom middle, less half the
    ring's height)."""
    hot, flow, cool = POUR_COLOURS
    wide, tall = SPLASH
    image = Image.new("RGBA", (wide, length + tall // 2))
    draw = ImageDraw.Draw(image)
    middle = wide // 2
    draw.ellipse((0, length - tall // 2, wide - 1, length + tall // 2 - 1), outline=cool)
    draw.ellipse((5, length - tall // 4, wide - 6, length + tall // 4 - 1), fill=flow, outline=flow)
    draw.ellipse((9, length - 2, wide - 10, length + 1), fill=hot)
    half = POUR_WIDTH // 2
    draw.rectangle((middle - half, 0, middle + half, length), fill=cool)
    draw.rectangle((middle - half + 1, 0, middle + half - 1, length), fill=flow)
    for y in range(0, length, 5):
        draw.line(((middle, y), (middle, y + 2)), fill=hot)
    return image


def build_cast_shadow(stage: Stage, colour: Rgb) -> tuple[Image.Image, tuple[float, float]]:
    """Return the island's shadow on the surface below it, and the world pixel of the
    picture's top left corner: every solid cell's diamond, dithered, on the plane of
    :func:`surface_level`."""
    level = surface_level(stage)
    cells = [(cx, cy) for cy, row in enumerate(stage.cells) for cx, cell in enumerate(row) if cell]
    corners = [project(cx, cy, level) for cx, cy in cells]
    left = min(x for x, _ in corners) - TILE_W // 2
    right = max(x for x, _ in corners) + TILE_W // 2
    top = max(y for _, y in corners)
    bottom = min(y for _, y in corners) - TILE_H
    width, height = round(right - left), round(top - bottom)
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    assert pixels is not None
    for corner_x, corner_y in corners:
        middle = round(corner_x - left)
        first = round(top - corner_y)
        for row in range(TILE_H):
            half = (row + 1) * 2 if row < TILE_H // 2 else (TILE_H - row) * 2
            for x in range(middle - half, middle + half):
                y = first + row
                if 0 <= x < width and 0 <= y < height and (x + y) % 2 == 0:
                    pixels[x, y] = (*colour, 255)
    return image, (left, top)
