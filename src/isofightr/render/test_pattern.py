"""Procedural M0 test pattern for checking pixel-perfect scaling and the 60 Hz tick.

Roadmap M0: "a 1280x720 window rendering a 640x360 offscreen buffer at integer scale with a
test pattern". Every feature here exists to make a scaling or timing fault visible:

- a 1 px border and four colored corners prove nothing is cropped, stretched or flipped;
- 1 px checker and stripe blocks turn gray or moire if any filtering or non-integer scaling
  sneaks in;
- the diamond grid uses the real projection constants, as a preview of iso tiles;
- a marker walks 1 px per simulation tick along a ruler notched every second.

Pure Pillow (no ``arcade``) so the image can be unit tested. All coordinates in this module are
image coordinates (origin top-left, y down) unless a name says otherwise.
"""

from collections.abc import Callable
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from isofightr.config import NATIVE_H, NATIVE_W, TICK_RATE, TILE_H, TILE_W

type Rgba = tuple[int, int, int, int]

# --- Palette -------------------------------------------------------------------------------
BACKGROUND: Final[Rgba] = (24, 28, 44, 255)
BORDER: Final[Rgba] = (255, 255, 255, 255)
TEXT: Final[Rgba] = (232, 236, 244, 255)
DARK: Final[Rgba] = (0, 0, 0, 255)
LIGHT: Final[Rgba] = (255, 255, 255, 255)
TILE_LIGHT: Final[Rgba] = (108, 190, 96, 255)
TILE_DARK: Final[Rgba] = (72, 148, 84, 255)
TRACK: Final[Rgba] = (120, 128, 152, 255)
MARKER_FILL: Final[Rgba] = (232, 59, 59, 255)
MARKER_EDGE: Final[Rgba] = (255, 255, 255, 255)

# Player colors from the plan note "09 - Art Direction", one per corner so a flipped or
# mirrored image is obvious: top-left, top-right, bottom-left, bottom-right.
CORNER_COLORS: Final[tuple[Rgba, Rgba, Rgba, Rgba]] = (
    (232, 59, 59, 255),
    (77, 155, 230, 255),
    (249, 194, 43, 255),
    (30, 188, 115, 255),
)
COLOR_BARS: Final[tuple[Rgba, ...]] = (
    (255, 255, 255, 255),
    (255, 255, 0, 255),
    (0, 255, 255, 255),
    (0, 255, 0, 255),
    (255, 0, 255, 255),
    (255, 0, 0, 255),
    (0, 0, 255, 255),
    (0, 0, 0, 255),
)

# --- Layout --------------------------------------------------------------------------------
CORNER_SIZE: Final[int] = 8
TITLE_POS: Final[tuple[int, int]] = (16, 12)
TITLE_TEXT: Final[str] = f"ISOFIGHTR  M0 TEST PATTERN  {NATIVE_W}x{NATIVE_H}  1 PX DETAIL BELOW"

BLOCK_TOP: Final[int] = 32
BLOCK_SIZE: Final[int] = 64
BLOCK_GAP: Final[int] = 16
BLOCK_LEFT: Final[int] = 16

BAR_LEFT: Final[int] = 272
BAR_WIDTH: Final[int] = 32
RAMP_TOP: Final[int] = BLOCK_TOP + BLOCK_SIZE + 4
RAMP_HEIGHT: Final[int] = 12
RAMP_STEPS: Final[int] = 16
RAMP_STEP_WIDTH: Final[int] = 16

GRID_TILES: Final[int] = 8
GRID_ORIGIN: Final[tuple[int, int]] = (NATIVE_W // 2, 136)

TRACK_LEFT: Final[int] = 20
TRACK_SPAN: Final[int] = 600
TRACK_Y: Final[int] = 318
TRACK_NOTCH_HEIGHT: Final[int] = 5
TRACK_LABEL_POS: Final[tuple[int, int]] = (16, 336)
TRACK_LABEL_TEXT: Final[str] = "MARKER: 1 PX PER TICK, ONE NOTCH PER SECOND"

MARKER_SIZE: Final[int] = 8
MARKER_GAP_ABOVE_TRACK: Final[int] = 2


def build_test_pattern() -> Image.Image:
    """Return the static 640x360 RGBA test pattern (everything except the moving marker)."""
    image = Image.new("RGBA", (NATIVE_W, NATIVE_H), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default_imagefont()

    _draw_border_and_corners(image, draw)
    draw.text(TITLE_POS, TITLE_TEXT, fill=TEXT, font=font)
    _draw_one_pixel_blocks(image)
    _draw_color_bars(draw)
    _draw_iso_grid(image)
    _draw_marker_track(draw)
    draw.text(TRACK_LABEL_POS, TRACK_LABEL_TEXT, fill=TEXT, font=font)
    return image


def build_marker() -> Image.Image:
    """Return the small sprite that walks along the ruler, one pixel per simulation tick."""
    image = Image.new("RGBA", (MARKER_SIZE, MARKER_SIZE), MARKER_EDGE)
    ImageDraw.Draw(image).rectangle((1, 1, MARKER_SIZE - 2, MARKER_SIZE - 2), fill=MARKER_FILL)
    return image


def marker_offset(tick: int) -> int:
    """Return how far along the ruler the marker is at ``tick``, bouncing end to end."""
    phase = tick % (2 * TRACK_SPAN)
    return phase if phase <= TRACK_SPAN else 2 * TRACK_SPAN - phase


def marker_center_native(tick: int) -> tuple[int, int]:
    """Return the marker's center in native buffer coordinates (origin bottom-left, y up).

    The marker has an even size, so a whole-number center keeps its edges on pixel boundaries.
    """
    center_y_image = TRACK_Y - MARKER_GAP_ABOVE_TRACK - MARKER_SIZE // 2
    return (TRACK_LEFT + marker_offset(tick), NATIVE_H - center_y_image)


def _draw_border_and_corners(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, NATIVE_W - 1, NATIVE_H - 1), outline=BORDER)
    right = NATIVE_W - 1 - CORNER_SIZE
    bottom = NATIVE_H - 1 - CORNER_SIZE
    for (left, top), color in zip(
        ((1, 1), (right, 1), (1, bottom), (right, bottom)), CORNER_COLORS, strict=True
    ):
        image.paste(color, (left, top, left + CORNER_SIZE, top + CORNER_SIZE))


def _draw_one_pixel_blocks(image: Image.Image) -> None:
    """Draw 1 px checker, vertical-stripe and horizontal-stripe blocks, left to right."""
    pixels = image.load()
    assert pixels is not None
    patterns: tuple[Callable[[int, int], bool], ...] = (
        lambda x, y: (x + y) % 2 == 0,
        lambda x, y: x % 2 == 0,
        lambda x, y: y % 2 == 0,
    )
    for index, is_light in enumerate(patterns):
        left = BLOCK_LEFT + index * (BLOCK_SIZE + BLOCK_GAP)
        for y in range(BLOCK_SIZE):
            for x in range(BLOCK_SIZE):
                pixels[left + x, BLOCK_TOP + y] = LIGHT if is_light(x, y) else DARK


def _draw_color_bars(draw: ImageDraw.ImageDraw) -> None:
    for index, color in enumerate(COLOR_BARS):
        left = BAR_LEFT + index * BAR_WIDTH
        draw.rectangle((left, BLOCK_TOP, left + BAR_WIDTH - 1, BLOCK_TOP + BLOCK_SIZE - 1), color)
    for step in range(RAMP_STEPS):
        level = round(step * 255 / (RAMP_STEPS - 1))
        left = BAR_LEFT + step * RAMP_STEP_WIDTH
        draw.rectangle(
            (left, RAMP_TOP, left + RAMP_STEP_WIDTH - 1, RAMP_TOP + RAMP_HEIGHT - 1),
            (level, level, level, 255),
        )


def _draw_iso_grid(image: Image.Image) -> None:
    """Draw a checkered diamond grid using the real 2:1 projection constants.

    Tiles are painted back to front (increasing ``x + y``), the same order the depth key gives.
    """
    origin_x, origin_y = GRID_ORIGIN
    half_w, half_h = TILE_W // 2, TILE_H // 2
    for depth in range(2 * GRID_TILES - 1):
        for tile_x in range(GRID_TILES):
            tile_y = depth - tile_x
            if not 0 <= tile_y < GRID_TILES:
                continue
            top_x = origin_x + (tile_x - tile_y) * half_w
            top_y = origin_y + (tile_x + tile_y) * half_h
            color = TILE_LIGHT if (tile_x + tile_y) % 2 == 0 else TILE_DARK
            _fill_diamond(image, top_x, top_y, color)


def _fill_diamond(image: Image.Image, top_x: int, top_y: int, color: Rgba) -> None:
    """Fill one ``TILE_W`` x ``TILE_H`` diamond whose top corner is at ``(top_x, top_y)``.

    Rows widen by 4 px per step (the classic 2:1 pixel-art slope) so neighbours tessellate.
    """
    half_h = TILE_H // 2
    for row in range(TILE_H):
        steps_from_tip = row + 1 if row < half_h else TILE_H - row
        half_width = 2 * steps_from_tip
        image.paste(color, (top_x - half_width, top_y + row, top_x + half_width, top_y + row + 1))


def _draw_marker_track(draw: ImageDraw.ImageDraw) -> None:
    draw.line((TRACK_LEFT, TRACK_Y, TRACK_LEFT + TRACK_SPAN, TRACK_Y), fill=TRACK)
    for notch_x in range(TRACK_LEFT, TRACK_LEFT + TRACK_SPAN + 1, TICK_RATE):
        draw.line((notch_x, TRACK_Y, notch_x, TRACK_Y + TRACK_NOTCH_HEIGHT), fill=TRACK)
