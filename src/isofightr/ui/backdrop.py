"""The menu backdrop: dusk over floating isles, drifting slowly.

Plan note "09 - Art Direction" ("UI theme", decision D-061): the stage backdrop painter's
layers in a dusk mood, scrolling at different speeds, with a few translucent isometric
tiles floating up the screen. The layers are painted by ``tools/build_ui_art.py`` into
``assets/ui/backdrop/``; this module says where everything is at a given tick, and
:mod:`isofightr.ui.backdrop_layer` draws it.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.paths import ASSETS_DIR
from isofightr.render.backdrop import LAYER_WIDTH, Mood, clouds, islands, sky
from isofightr.ui import theme

BACKDROP_DIR: Final[Path] = ASSETS_DIR / "ui" / "backdrop"
DUSK: Final[Mood] = Mood(
    sky=("323353", "323353", "484a77", "6b3e75", "a24b6f"),
    cloud=("905ea9", "6b3e75", "484a77"),
    island_top="0b8a8f",
    island_side=("0b5e65", "323353"),
    ruin="8fd3ff",
)
"""The menu sky: deep navy at the top, plum and a last band of rose at the horizon, teal islands."""
BACKDROP_SEED: Final[int] = 61


@dataclass(frozen=True, slots=True)
class BackdropLayer:
    """One scrolling layer."""

    image: str
    speed: float
    """Pixels it moves left per tick (0 = still)."""


LAYERS: Final[tuple[BackdropLayer, ...]] = (
    BackdropLayer("bg_0_sky.png", 0.0),
    BackdropLayer("bg_1_far_clouds.png", 0.05),
    BackdropLayer("bg_2_islands.png", 0.1),
    BackdropLayer("bg_3_near_clouds.png", 0.2),
)
"""Back to front. The slowest layer takes about seven minutes to come round."""


def paint_layers(seed: int = BACKDROP_SEED) -> dict[str, Image.Image]:
    """Paint the backdrop layers (the build tool saves them)."""
    return {
        "bg_0_sky.png": sky(DUSK),
        "bg_1_far_clouds.png": clouds(DUSK, seed, 7, (240, 300), (10, 16)),
        "bg_2_islands.png": islands(DUSK, seed + 1, 6, (60, 200), (10, 22)),
        "bg_3_near_clouds.png": clouds(DUSK, seed + 2, 5, (316, 350), (18, 28)),
    }


def layer_shift(tick: int, speed: float, width: int = LAYER_WIDTH) -> int:
    """Return how many pixels a layer has scrolled left at ``tick``: 0 to ``width - 1``."""
    return int(tick * speed) % width


# --- drifting tiles ----------------------------------------------------------------------
TILE_HALF_WIDTHS: Final[tuple[int, ...]] = (8, 12, 16)
"""Half the width of a drifting tile's top diamond, by size index."""
TILE_ALPHA: Final[int] = 72
DRIFT_MARGIN: Final[int] = 40
"""How far past the top and bottom a tile travels before it wraps round."""


@dataclass(frozen=True, slots=True)
class DriftTile:
    """One floating tile: where it starts and how it moves."""

    x: int
    y: int
    rise: float
    """Pixels it climbs per tick."""
    sway: int
    """How far it wanders sideways, in pixels."""
    period: int
    """Ticks for one sway there and back."""
    size: int
    """Index into :data:`TILE_HALF_WIDTHS`."""


DRIFT_TILES: Final[tuple[DriftTile, ...]] = (
    DriftTile(52, 40, 0.11, 6, 540, 1),
    DriftTile(148, 250, 0.07, 4, 700, 0),
    DriftTile(236, 120, 0.15, 8, 480, 2),
    DriftTile(330, 310, 0.09, 5, 620, 0),
    DriftTile(418, 60, 0.13, 7, 560, 1),
    DriftTile(506, 210, 0.06, 4, 760, 0),
    DriftTile(592, 140, 0.12, 6, 500, 2),
)


def drift_positions(tick: int) -> list[tuple[int, int, int]]:
    """Return ``(x, y, size)`` of every drifting tile at ``tick``: the centre of its top
    face in native pixels (y up). Tiles climb, sway from side to side, and wrap."""
    span = NATIVE_H + 2 * DRIFT_MARGIN
    spots = []
    for tile in DRIFT_TILES:
        y = (tile.y + DRIFT_MARGIN + int(tick * tile.rise)) % span - DRIFT_MARGIN
        phase = (tick % tile.period) / tile.period
        # A triangle wave: out and back at a steady pace.
        swing = 4 * abs(phase - 0.5) - 1
        spots.append((tile.x + round(tile.sway * swing), y, tile.size))
    return spots


def build_drift_tile(half: int) -> Image.Image:
    """Return a translucent isometric block ``2 * half`` pixels wide: a lit top diamond over
    two side faces."""
    width, top, side = half * 2, half, half
    image = Image.new("RGBA", (width, top + side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    centre, middle, last = half, top // 2, width - 1
    left = [(0, middle), (centre, top), (centre, top + side - 1), (0, middle + side - 1)]
    right = [(last, middle), (centre, top), (centre, top + side - 1), (last, middle + side - 1)]
    draw.polygon(left, fill=theme.with_alpha(theme.STEEL, TILE_ALPHA))
    draw.polygon(right, fill=theme.with_alpha(theme.NAVY, TILE_ALPHA))
    diamond = [(0, middle), (centre, 0), (last, middle), (centre, top)]
    draw.polygon(diamond, fill=theme.with_alpha(theme.ICE, TILE_ALPHA))
    return image


assert NATIVE_W <= LAYER_WIDTH, "a layer must cover the screen"
