"""Procedural placeholder art, drawn with Pillow at startup.

Implements "Placeholder art" in the plan note "09 - Art Direction": two-tone diamond blocks
for tiles, a colored capsule with a facing arrow for fighters, plus the blob shadow and
player ring from "03 - Isometric World and Rendering". Gameplay work never waits on art, and
the renderer treats these exactly like final sprites.

Pure Pillow (no ``arcade``), so shapes and sizes are unit tested. All coordinates in this
module are image coordinates (origin top-left, y down).
"""

from __future__ import annotations

import math
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
REVIVAL_PALETTE: Final[TilePalette] = TilePalette(
    top_light=(236, 244, 255, 255),
    top_dark=(236, 244, 255, 255),
    left=(150, 190, 240, 255),
    right=(110, 150, 215, 255),
)
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
LYING_HALF_LENGTH: Final[int] = BODY_HEIGHT // 2
LYING_HEIGHT: Final[int] = BODY_HALF_WIDTH * 2
"""A knocked-down fighter is the same capsule on its side."""
QUARTER_TURN_DEGREES: Final[int] = 90

# --- Hit sparks and attack swings ----------------------------------------------------------
SPARK_SIZES: Final[tuple[int, ...]] = (15, 23, 31, 43)
"""Canvas size of a spark, by tier: light, medium, heavy, KO strength. Odd, so it has a
centre pixel."""
SPARK_FRAME_SCALE: Final[tuple[float, ...]] = (0.55, 1.0, 1.0)
"""How much of the canvas each animation frame fills. The last frame is only an outline."""
SPARK_POINTS: Final[int] = 4
SPARK_INNER_RATIO: Final[float] = 0.3
SPARK_CORE_RATIO: Final[float] = 0.6
"""Size of the bright core of a spark, relative to the whole star."""
SPARK_COLORS: Final[dict[str, tuple[Rgba, Rgba]]] = {
    "normal": ((255, 244, 180, 255), (249, 194, 43, 255)),
    "slash": ((255, 255, 255, 255), (150, 220, 255, 255)),
    "fire": ((255, 230, 150, 255), (240, 96, 40, 255)),
    "electric": ((255, 255, 255, 255), (120, 200, 255, 255)),
    "ice": ((240, 250, 255, 255), (130, 200, 240, 255)),
    "darkness": ((220, 170, 255, 255), (120, 60, 180, 255)),
}
"""``(core, edge)`` colors of a spark, by hit effect name."""
SWING_ALPHA: Final[int] = 150
SWING_RIM_ALPHA: Final[int] = 230
SPHERE_WIDTH_PER_UNIT: Final[float] = TILE_W / 2 * math.sqrt(2.0)
"""Screen half-width in pixels of a sphere of radius 1: the projection of ``x - y``."""
SPHERE_HEIGHT_PER_UNIT: Final[float] = math.sqrt(2 * (TILE_H / 2) ** 2 + Z_PX**2)
"""Screen half-height in pixels of a sphere of radius 1 (``-(x + y) * 8 + z * 16``)."""

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


def build_revival_platform() -> Image.Image:
    """Return the small glowing platform a fighter stands on after a KO."""
    return build_block(REVIVAL_PALETTE, True, DECK_SIDE_PX)


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


def build_fighter(
    player_index: int,
    facing: Dir8,
    lying: bool = False,
    quarter_turns: int = 0,
    flash: bool = False,
) -> Image.Image:
    """Return the 64x64 placeholder fighter: a capsule, a darker head and a facing arrow.

    The arrow points where the facing direction goes on screen. Fighters facing toward the
    camera also get eyes, so front and back read differently at a glance.

    Args:
        player_index: picks the color.
        facing: where the arrow points.
        lying: draw the knocked-down pose (the capsule on its side) instead.
        quarter_turns: spin the standing sprite about its middle (tumbling).
        flash: paint every pixel white (hit flash, charge blink).
    """
    image = _build_lying(player_index) if lying else _build_standing(player_index, facing)
    if quarter_turns % 4 and not lying:
        # Pillow measures the centre from the image's top-left corner, in pixel edges.
        middle = (FIGHTER_PIVOT_X, FIGHTER_CANVAS - FIGHTER_PIVOT_FROM_BOTTOM - BODY_HEIGHT / 2)
        image = image.rotate(
            quarter_turns * QUARTER_TURN_DEGREES, resample=Image.Resampling.NEAREST, center=middle
        )
    if flash:
        white = Image.new("RGBA", image.size, WHITE)
        white.putalpha(image.getchannel("A"))
        image = white
    return image


def _build_lying(player_index: int) -> Image.Image:
    color = player_color(player_index)
    image = Image.new("RGBA", (FIGHTER_CANVAS, FIGHTER_CANVAS), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    feet_row = FIGHTER_CANVAS - FIGHTER_PIVOT_FROM_BOTTOM
    left = FIGHTER_PIVOT_X - LYING_HALF_LENGTH
    right = FIGHTER_PIVOT_X + LYING_HALF_LENGTH - 1
    top = feet_row - LYING_HEIGHT
    draw.rounded_rectangle(
        (left, top, right, feet_row - 1),
        radius=BODY_HALF_WIDTH - 1,
        fill=color,
        outline=shade(color, OUTLINE_SHADE),
    )
    draw.ellipse(
        (left + 1, top + 1, left + HEAD_HEIGHT, feet_row - 2), fill=shade(color, HEAD_SHADE)
    )
    return image


def _build_standing(player_index: int, facing: Dir8) -> Image.Image:
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


def build_spark(tier: int, effect: str, frame: int) -> Image.Image:
    """Return one frame of a hit spark: a four-point star that grows, then leaves an outline.

    Args:
        tier: 0 light to 3 KO strength; picks the size.
        effect: the hit effect name (``Effect.value``); picks the colors.
        frame: animation frame, 0 to 2.
    """
    size = SPARK_SIZES[min(tier, len(SPARK_SIZES) - 1)]
    core, edge = SPARK_COLORS.get(effect, SPARK_COLORS["normal"])
    image = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    centre = (size - 1) / 2
    outer = centre * SPARK_FRAME_SCALE[min(frame, len(SPARK_FRAME_SCALE) - 1)]
    inner = outer * SPARK_INNER_RATIO
    points = _star(centre, outer, inner)
    if frame >= len(SPARK_FRAME_SCALE) - 1:
        draw.polygon(points, outline=edge)
    else:
        draw.polygon(points, fill=edge)
        draw.polygon(_star(centre, outer * SPARK_CORE_RATIO, inner * SPARK_CORE_RATIO), fill=core)
    # Polygon rasterising is not quite symmetric; mirror it so the spark is.
    for flip in (Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM):
        image = Image.alpha_composite(image.transpose(flip), image)
    return image


def _star(centre: float, outer: float, inner: float) -> list[tuple[float, float]]:
    points = []
    for index in range(SPARK_POINTS * 2):
        radius = outer if index % 2 == 0 else inner
        angle = math.pi * index / SPARK_POINTS
        points.append((centre + math.sin(angle) * radius, centre - math.cos(angle) * radius))
    return points


def sphere_screen_size(radius: float) -> tuple[int, int]:
    """Return the ``(width, height)`` in pixels of a world sphere's outline on screen."""
    width = max(1, round(radius * SPHERE_WIDTH_PER_UNIT * 2))
    height = max(1, round(radius * SPHERE_HEIGHT_PER_UNIT * 2))
    return (width, height)


def build_swing(player_index: int, radius: float) -> Image.Image:
    """Return the placeholder "attack swing": a translucent blob the size of a hitbox.

    Until moves have animations this is the only visual of an attack, and it is drawn exactly
    where the hitbox is, so what you see is what hits.
    """
    width, height = sphere_screen_size(radius)
    red, green, blue, _ = player_color(player_index)
    image = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (0, 0, width - 1, height - 1),
        fill=(255, 255, 255, SWING_ALPHA),
        outline=(red, green, blue, SWING_RIM_ALPHA),
    )
    return image


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
