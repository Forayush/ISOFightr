"""Draws a stage's parallax backdrop layers: sky, cloud banks and distant islands.

Plan note "09 - Art Direction" ("Environments": 3-4 parallax layers, lower saturation and
contrast than the playfield). The layers are generated once by ``tools/build_backdrop.py`` and
saved as stage background images; nothing here runs during a match. Colours come from the
master palette (Resurrect 64). Seeded, so a rebuild gives the same pictures.

Pure Python plus Pillow (no ``arcade``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageDraw

from isofightr.config import NATIVE_H, NATIVE_W

Rgb = tuple[int, int, int]

LAYER_WIDTH: Final[int] = NATIVE_W * 2
"""Layers repeat horizontally; twice the screen leaves room to scroll."""


def hex_rgb(value: str) -> Rgb:
    """Parse ``"rrggbb"``."""
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


@dataclass(frozen=True, slots=True)
class Mood:
    """The colours of one time of day."""

    sky: tuple[str, ...]
    """Top to bottom."""
    cloud: tuple[str, str, str]
    """Light, mid, shadow."""
    island_top: str
    island_side: tuple[str, str]
    ruin: str


DAY: Final[Mood] = Mood(
    sky=("4d9be6", "8fd3ff", "c7dcd0"),
    cloud=("ffffff", "c7dcd0", "9babb2"),
    island_top="b2ba90",
    island_side=("c7dcd0", "9babb2"),
    ruin="ffffff",
)
SUNSET: Final[Mood] = Mood(
    sky=("6b3e75", "cf657f", "f68181", "fbb954"),
    cloud=("fca790", "f68181", "cf657f"),
    island_top="a24b6f",
    island_side=("cf657f", "753c54"),
    ruin="fdcbb0",
)
MOODS: Final[dict[str, Mood]] = {"day": DAY, "sunset": SUNSET}
BAYER_4: Final[tuple[tuple[int, ...], ...]] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
"""Ordered-dither thresholds (out of 16): blends two palette colours without new ones."""


def sky(mood: Mood, width: int = NATIVE_W, height: int = NATIVE_H) -> Image.Image:
    """Return the sky: a vertical gradient through the mood's colours, ordered-dithered so
    only palette colours are used."""
    colors = [hex_rgb(value) for value in mood.sky]
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    assert pixels is not None
    steps = len(colors) - 1
    for y in range(height):
        position = y / (height - 1) * steps
        index = min(int(position), steps - 1)
        blend = position - index
        for x in range(width):
            pick = colors[index + 1] if blend * 16 > BAYER_4[y % 4][x % 4] else colors[index]
            pixels[x, y] = (*pick, 255)
    return image


def _cloud(
    draw: ImageDraw.ImageDraw, x: int, y: int, size: int, rng: random.Random, mood: Mood
) -> None:
    """One cumulus cloud: wide overlapping puffs over a flat, shaded base."""
    light, mid, shadow = (hex_rgb(value) for value in mood.cloud)
    puffs = []
    for index in range(6):
        along = (index - 2.5) / 2.5
        radius = int(size * (1.0 - 0.45 * abs(along)) * rng.uniform(0.75, 1.05))
        puffs.append((x + int(along * size * 1.6), y - radius // 2, radius))
    base = y + size // 3
    left = min(px for px, _, _ in puffs)
    right = max(px for px, _, _ in puffs)
    for colour, lift, shrink in ((shadow, 0, 0), (mid, 2, 1), (light, 4, 3)):
        for px, py, radius in puffs:
            rx, ry = int(radius * 1.3) - shrink, radius - shrink
            draw.ellipse((px - rx, py - ry - lift, px + rx, py + ry - lift), fill=colour)
        draw.rectangle(
            (left + shrink * 2, base - size // 2 - lift, right - shrink * 2, base - lift),
            fill=colour,
        )
    draw.rectangle(
        (left - size * 2, base + 1, right + size * 2, base + size * 2), fill=(0, 0, 0, 0)
    )


def clouds(
    mood: Mood,
    seed: int,
    count: int,
    band: tuple[int, int],
    sizes: tuple[int, int],
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a layer of clouds scattered across a horizontal band, wrapping at the edges."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    for index in range(count):
        x = int((index + rng.uniform(0.1, 0.9)) * width / count)
        y = rng.randint(*band)
        size = rng.randint(*sizes)
        for shift in (-width, 0, width):
            _cloud(draw, x + shift, y, size, random.Random(seed * 100 + index), mood)
    return image


def islands(
    mood: Mood,
    seed: int,
    count: int,
    band: tuple[int, int],
    sizes: tuple[int, int],
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a layer of small, hazy floating islands with rocky undersides; some carry
    ruined pillars."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    top_color = hex_rgb(mood.island_top)
    left_side, right_side = (hex_rgb(value) for value in mood.island_side)
    ruin = hex_rgb(mood.ruin)
    for index in range(count):
        cx = int((index + rng.uniform(0.2, 0.8)) * width / count)
        cy = rng.randint(*band)
        half = rng.randint(*sizes)
        quarter = half // 2
        lip = max(2, half // 6)
        # The rocky underside: a jagged outline from the left corner to the right one.
        under = [(-half, lip)]
        for step in range(1, 6):
            along = -half + step * half * 2 // 6
            depth = int((1 - abs(along) / half) * half * rng.uniform(0.7, 1.2)) + lip
            under.append((along, depth + quarter // 2))
        under.append((half, lip))
        for shift in (-width, 0, width):
            x = cx + shift
            outline = [(x + ux, cy + uy) for ux, uy in under]
            draw.polygon(
                [(x - half, cy), (x, cy + quarter), (x + half, cy), *reversed(outline)],
                fill=right_side,
            )
            draw.polygon(
                [
                    (x - half, cy),
                    (x, cy + quarter),
                    *[(x + ux, cy + uy) for ux, uy in under if ux <= 0],
                ],
                fill=left_side,
            )
            draw.polygon(
                [(x, cy - quarter), (x + half, cy), (x, cy + quarter), (x - half, cy)],
                fill=top_color,
            )
            if index % 2 == 0:
                for offset in (-half // 3, half // 5):
                    pillar = max(4, half // 3) + abs(offset) % 3
                    draw.rectangle((x + offset - 1, cy - pillar, x + offset + 1, cy), fill=ruin)
    return image
