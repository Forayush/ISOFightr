"""Procedural placeholder art, drawn with Pillow at startup.

Implements "Placeholder art" in the plan note "09 - Art Direction": two-tone diamond blocks
for tiles, a colored capsule with a facing arrow for fighters, plus the blob shadow and
player ring from "03 - Isometric World and Rendering". Gameplay work never waits on art, and
the renderer treats these exactly like final sprites.

Pure Pillow (no ``arcade``), so shapes and sizes are unit tested. All coordinates in this
module are image coordinates (origin top-left, y down).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageDraw

from isofightr.config import DECK_THICKNESS, NATIVE_H, NATIVE_W, TILE_H, TILE_W, Z_PX
from isofightr.render.iso import project
from isofightr.sim.input_frame import Dir8

type Rgba = tuple[int, int, int, int]

TRANSPARENT: Final[Rgba] = (0, 0, 0, 0)
WHITE: Final[Rgba] = (255, 255, 255, 255)
INK: Final[Rgba] = (24, 20, 37, 255)

# --- Tiles ---------------------------------------------------------------------------------
HALF_TILE_W: Final[int] = TILE_W // 2
HALF_TILE_H: Final[int] = TILE_H // 2
GRASS_LIP_PX: Final[int] = 3
"""How far the top color hangs over the side faces, like turf over a cliff edge."""


@dataclass(frozen=True, slots=True)
class TilePalette:
    """Colors of one block: two top tones (checker), the lit left face, the shaded right."""

    top_light: Rgba
    top_dark: Rgba
    left: Rgba
    right: Rgba
    lip: Rgba | None = None


DEFAULT_TILE_PALETTE: Final[str] = "grass"
TILE_PALETTES: Final[dict[str, TilePalette]] = {
    "grass": TilePalette(
        top_light=(116, 196, 98, 255),
        top_dark=(94, 176, 88, 255),
        left=(150, 116, 90, 255),
        right=(110, 84, 72, 255),
        lip=(62, 137, 72, 255),
    ),
    "grid": TilePalette(
        top_light=(198, 206, 222, 255),
        top_dark=(166, 176, 198, 255),
        left=(112, 120, 144, 255),
        right=(82, 88, 112, 255),
    ),
    "stone": TilePalette(
        top_light=(172, 170, 178, 255),
        top_dark=(150, 148, 160, 255),
        left=(112, 108, 124, 255),
        right=(84, 80, 98, 255),
    ),
}
DECK_PALETTE: Final[TilePalette] = TilePalette(
    top_light=(222, 178, 116, 255),
    top_dark=(202, 156, 98, 255),
    left=(150, 104, 66, 255),
    right=(118, 80, 54, 255),
)
DECK_SIDE_PX: Final[int] = round(DECK_THICKNESS * Z_PX)
PLATFORM_SHADOW: Final[Rgba] = (16, 20, 40, 72)

# --- Fighters ------------------------------------------------------------------------------
FIGHTER_CANVAS: Final[int] = 64
FIGHTER_PIVOT_X: Final[int] = 32
FIGHTER_PIVOT_FROM_BOTTOM: Final[int] = 8
"""Feet pivot at (32, 8) from the bottom-left of the canvas (plan note 09)."""
BODY_HALF_WIDTH: Final[int] = 7
BODY_HEIGHT: Final[int] = 40
"""2.5 world units at 16 px per unit."""
HEAD_HEIGHT: Final[int] = 12
ARROW_CENTRE_ABOVE_FEET: Final[int] = 17
ARROW_BACK: Final[float] = 4.0
ARROW_FRONT: Final[float] = 6.0
ARROW_HEAD: Final[float] = 3.0
ARROW_OUTLINE_WIDTH: Final[int] = 3
ARROW_HEAD_OUTLINE_WIDTH: Final[int] = 2
OUTLINE_SHADE: Final[float] = 0.45
HEAD_SHADE: Final[float] = 0.7
EYE_HEIGHT_ABOVE_FEET: Final[int] = 33
EYE_SPREAD: Final[int] = 2

PLAYER_COLORS: Final[tuple[Rgba, ...]] = (
    (232, 59, 59, 255),
    (77, 155, 230, 255),
    (249, 194, 43, 255),
    (30, 188, 115, 255),
)
"""P1 red, P2 blue, P3 yellow, P4 green (plan note 09). Player indices wrap around."""

# --- Shadows -------------------------------------------------------------------------------
SHADOW_WIDTH: Final[int] = 20
SHADOW_HEIGHT: Final[int] = 10


@dataclass(frozen=True, slots=True)
class ShadowVariant:
    """How the blob shadow looks at one height band: it shrinks and fades as you rise."""

    max_height: float
    """Use this variant while the fighter is at most this far above the surface, in units."""
    blob_width: int
    blob_height: int
    blob_alpha: int


SHADOW_VARIANTS: Final[tuple[ShadowVariant, ...]] = (
    ShadowVariant(max_height=0.75, blob_width=14, blob_height=8, blob_alpha=128),
    ShadowVariant(max_height=2.5, blob_width=12, blob_height=6, blob_alpha=104),
    ShadowVariant(max_height=float("inf"), blob_width=8, blob_height=4, blob_alpha=80),
)

# --- Sky -----------------------------------------------------------------------------------
SKY_BANDS: Final[tuple[Rgba, ...]] = (
    (43, 62, 121, 255),
    (52, 80, 146, 255),
    (62, 100, 168, 255),
    (76, 124, 188, 255),
    (94, 148, 204, 255),
    (118, 172, 216, 255),
    (148, 196, 226, 255),
    (182, 218, 234, 255),
)


def shade(color: Rgba, factor: float) -> Rgba:
    """Return ``color`` with its RGB scaled by ``factor`` (alpha unchanged)."""
    red, green, blue, alpha = color
    return (round(red * factor), round(green * factor), round(blue * factor), alpha)


def tile_palette(tile: str) -> TilePalette:
    """Return the palette for a tile name, falling back to the default look."""
    return TILE_PALETTES.get(tile, TILE_PALETTES[DEFAULT_TILE_PALETTE])


def diamond_row_range(column: int) -> tuple[int, int]:
    """Return the first and last row of the 32x16 top diamond in a pixel column.

    The edges step 1 px down per 2 px across (the classic 2:1 pixel-art slope), so
    neighbouring tiles tessellate.
    """
    from_edge = column if column < HALF_TILE_W else TILE_W - 1 - column
    return (HALF_TILE_H - 1 - from_edge // 2, HALF_TILE_H + from_edge // 2)


def build_block(palette: TilePalette, light: bool, side_px: int) -> Image.Image:
    """Return a block sprite: a 32x16 top diamond over side faces ``side_px`` tall."""
    image = Image.new("RGBA", (TILE_W, TILE_H + side_px), TRANSPARENT)
    pixels = image.load()
    assert pixels is not None
    top = palette.top_light if light else palette.top_dark
    for column in range(TILE_W):
        first, last = diamond_row_range(column)
        face = palette.left if column < HALF_TILE_W else palette.right
        for row in range(first, last + 1):
            pixels[column, row] = top
        for offset in range(side_px):
            lipped = palette.lip is not None and offset < GRASS_LIP_PX
            pixels[column, last + 1 + offset] = palette.lip if lipped and palette.lip else face
    return image


def build_tile(tile: str, light: bool, side_px: int) -> Image.Image:
    """Return the block sprite for a stage cell whose sides hang ``side_px`` below its top."""
    return build_block(tile_palette(tile), light, side_px)


def build_deck(light: bool) -> Image.Image:
    """Return one cell of a soft platform deck: a thin wooden slab."""
    return build_block(DECK_PALETTE, light, DECK_SIDE_PX)


def build_platform_shadow() -> Image.Image:
    """Return the translucent diamond a soft platform casts on the ground cell beneath it."""
    image = Image.new("RGBA", (TILE_W, TILE_H), TRANSPARENT)
    pixels = image.load()
    assert pixels is not None
    for column in range(TILE_W):
        first, last = diamond_row_range(column)
        for row in range(first, last + 1):
            pixels[column, row] = PLATFORM_SHADOW
    return image


def player_color(player_index: int) -> Rgba:
    """Return a player's color; indices beyond four wrap around."""
    return PLAYER_COLORS[player_index % len(PLAYER_COLORS)]


def build_fighter(player_index: int, facing: Dir8) -> Image.Image:
    """Return the 64x64 placeholder fighter: a capsule, a darker head and a facing arrow.

    The arrow points where the facing direction goes on screen. Fighters facing toward the
    camera also get eyes, so front and back read differently at a glance.
    """
    color = player_color(player_index)
    outline = shade(color, OUTLINE_SHADE)
    image = Image.new("RGBA", (FIGHTER_CANVAS, FIGHTER_CANVAS), TRANSPARENT)
    draw = ImageDraw.Draw(image)

    feet_row = FIGHTER_CANVAS - FIGHTER_PIVOT_FROM_BOTTOM  # first row below the feet
    left = FIGHTER_PIVOT_X - BODY_HALF_WIDTH
    right = FIGHTER_PIVOT_X + BODY_HALF_WIDTH - 1
    top = feet_row - BODY_HEIGHT
    draw.rounded_rectangle(
        (left, top, right, feet_row - 1), radius=BODY_HALF_WIDTH - 1, fill=color, outline=outline
    )
    draw.ellipse((left + 1, top + 1, right - 1, top + HEAD_HEIGHT), fill=shade(color, HEAD_SHADE))

    screen_x, screen_y_up = project(facing.world.x, facing.world.y)
    length = (screen_x**2 + screen_y_up**2) ** 0.5
    direction = (screen_x / length, -screen_y_up / length)  # image space: y down
    if direction[1] >= 0:
        eye_row = feet_row - EYE_HEIGHT_ABOVE_FEET
        eye_centre = FIGHTER_PIVOT_X + round(direction[0] * EYE_SPREAD)
        for eye in (eye_centre - EYE_SPREAD, eye_centre + EYE_SPREAD - 1):
            image.putpixel((eye, eye_row), WHITE)
            image.putpixel((eye, eye_row + 1), INK)

    centre = (FIGHTER_PIVOT_X - 0.5, feet_row - ARROW_CENTRE_ABOVE_FEET - 0.5)
    _draw_arrow(draw, centre, direction)
    return image


def _draw_arrow(
    draw: ImageDraw.ImageDraw, centre: tuple[float, float], direction: tuple[float, float]
) -> None:
    """Draw a white arrow with a dark outline through ``centre`` along ``direction``."""
    dx, dy = direction
    side = (-dy, dx)
    tail = (centre[0] - dx * ARROW_BACK, centre[1] - dy * ARROW_BACK)
    tip = (centre[0] + dx * ARROW_FRONT, centre[1] + dy * ARROW_FRONT)
    neck = (tip[0] - dx * ARROW_HEAD, tip[1] - dy * ARROW_HEAD)
    head = [
        tip,
        (neck[0] + side[0] * ARROW_HEAD, neck[1] + side[1] * ARROW_HEAD),
        (neck[0] - side[0] * ARROW_HEAD, neck[1] - side[1] * ARROW_HEAD),
    ]
    draw.line((tail, tip), fill=INK, width=ARROW_OUTLINE_WIDTH)
    draw.polygon(head, fill=INK, outline=INK, width=ARROW_HEAD_OUTLINE_WIDTH)
    draw.line((tail, neck), fill=WHITE, width=1)
    draw.polygon(head, fill=WHITE)


def shadow_variant_index(height_above_surface: float) -> int:
    """Return which :data:`SHADOW_VARIANTS` entry applies at a height above the surface."""
    for index, variant in enumerate(SHADOW_VARIANTS):
        if height_above_surface <= variant.max_height:
            return index
    return len(SHADOW_VARIANTS) - 1


def build_shadow(player_index: int, variant_index: int) -> Image.Image:
    """Return the blob shadow with the player-colored ring around it (20x10)."""
    variant = SHADOW_VARIANTS[variant_index]
    image = Image.new("RGBA", (SHADOW_WIDTH, SHADOW_HEIGHT), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    left = (SHADOW_WIDTH - variant.blob_width) // 2
    top = (SHADOW_HEIGHT - variant.blob_height) // 2
    draw.ellipse(
        (left, top, left + variant.blob_width - 1, top + variant.blob_height - 1),
        fill=(0, 0, 0, variant.blob_alpha),
    )
    draw.ellipse((0, 0, SHADOW_WIDTH - 1, SHADOW_HEIGHT - 1), outline=player_color(player_index))
    return image


def build_sky() -> Image.Image:
    """Return the 640x360 banded sky gradient used until stages have real backgrounds."""
    image = Image.new("RGBA", (NATIVE_W, NATIVE_H), SKY_BANDS[-1])
    band_height = NATIVE_H // len(SKY_BANDS)
    for index, color in enumerate(SKY_BANDS):
        image.paste(color, (0, index * band_height, NATIVE_W, (index + 1) * band_height))
    return image
