"""Draws a stage's parallax backdrop layers: sky, cloud banks and distant islands.

Plan note "09 - Art Direction" ("Environments": 3-4 parallax layers, lower saturation and
contrast than the playfield). The layers are generated once by ``tools/build_backdrop.py`` and
saved as stage background images; nothing here runs during a match. Colours come from the
master palette (Resurrect 64). Seeded, so a rebuild gives the same pictures.

Pure Python plus Pillow (no ``arcade``).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
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
GOLDEN: Final[Mood] = Mood(
    sky=("4d9be6", "8fd3ff", "fdcbb0", "fbb954"),
    cloud=("ffffff", "fdcbb0", "fca790"),
    island_top="a2a947",
    island_side=("fbb954", "cd683d"),
    ruin="ffffff",
)
"""Golden hour: a blue sky warming to peach and gold at the horizon (Twin Isles)."""
MOODS: Final[dict[str, Mood]] = {"day": DAY, "sunset": SUNSET, "golden": GOLDEN}
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


# --- themes ---------------------------------------------------------------------------------

Painter = Callable[[Mood, int], dict[str, Image.Image]]
"""Paints a theme's layers, back to front, as ``{file name: image}`` for a mood and a seed."""


def paint_sky(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """The open sky: a dithered gradient, far clouds, distant islands and near clouds."""
    return {
        "bg_0_sky.png": sky(mood),
        "bg_1_far_clouds.png": clouds(mood, seed, 8, (250, 300), (10, 16)),
        "bg_2_islands.png": islands(mood, seed + 1, 6, (50, 150), (9, 18)),
        "bg_3_near_clouds.png": clouds(mood, seed + 2, 5, (318, 350), (18, 26)),
    }


PAINTERS: Final[dict[str, Painter]] = {"sky": paint_sky}
"""One backdrop painter per theme (decision D-063); each stage's theme adds its own."""


# --- the cloud sea (Sky Ruins) -------------------------------------------------------------

SUN_CENTRE: Final[tuple[int, int]] = (506, 62)
SUN_RADIUS: Final[int] = 13
SUN_HALO: Final[int] = 34
SUN_COLOURS: Final[tuple[str, str]] = ("ffffff", "fbff86")
BIRD_COLOUR: Final[str] = "484a77"
BIRD_FRAMES: Final[tuple[tuple[str, ...], ...]] = (
    ("#...#", ".#.#.", "..#.."),
    (".....", "##.##", "..#.."),
)
"""A far-off bird with its wings up, then level (``#`` is a pixel)."""
BIRDS: Final[int] = 9
BIRD_BAND: Final[tuple[int, int]] = (58, 150)


def sunny_sky(mood: Mood, centre: tuple[int, int] = SUN_CENTRE) -> Image.Image:
    """Return the mood's sky with a small sun at ``centre`` and a dithered halo around it."""
    image = sky(mood)
    pixels = image.load()
    assert pixels is not None
    disc, glow = (hex_rgb(value) for value in SUN_COLOURS)
    centre_x, centre_y = centre
    for y in range(centre_y - SUN_HALO, centre_y + SUN_HALO + 1):
        for x in range(centre_x - SUN_HALO, centre_x + SUN_HALO + 1):
            distance = ((x - centre_x) ** 2 + (y - centre_y) ** 2) ** 0.5
            if distance <= SUN_RADIUS:
                pixels[x, y] = (*disc, 255)
            elif distance <= SUN_HALO:
                strength = 1.0 - (distance - SUN_RADIUS) / (SUN_HALO - SUN_RADIUS)
                if strength * strength * 16 > BAYER_4[y % 4][x % 4]:
                    pixels[x, y] = (*glow, 255)
    return image


def cloud_bank(
    mood: Mood,
    seed: int,
    top: int,
    swell: int,
    puff: int,
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a sea of cloud seen from above: an unbroken bank whose billowing top edge is
    about ``top`` pixels down, lit along its crests and darker with depth. It wraps."""
    rng = random.Random(seed)
    light, mid, shadow = (hex_rgb(value) for value in mood.cloud)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    floor = top + swell + puff // 2
    draw.rectangle((0, floor, width, height), fill=mid)
    count = max(4, width // puff)
    puffs = []
    for index in range(count):
        x = int((index + rng.uniform(0.2, 0.8)) * width / count)
        y = top + rng.randint(0, swell) + puff // 2
        puffs.append((x, y, int(puff * rng.uniform(0.75, 1.2))))
    for colour, lift, shrink in ((light, 0, 0), (mid, -3, 1)):
        for x, y, radius in puffs:
            for shift in (-width, 0, width):
                rx, ry = int(radius * 1.5) - shrink, radius - shrink
                draw.ellipse(
                    (x + shift - rx, y - ry - lift, x + shift + rx, y + ry - lift), fill=colour
                )
    # Deeper in, the bank falls into its own shadow: dithered, so no new colour appears.
    pixels = image.load()
    assert pixels is not None
    depth = max(height - floor, 1)
    for y in range(floor, height):
        strength = (y - floor) / depth
        for x in range(width):
            if strength * 16 > BAYER_4[y % 4][x % 4]:
                pixels[x, y] = (*shadow, 255)
    return image


def birds(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return a flock of far-off birds as two frames stacked top to bottom (wings up, wings
    level), for a ``[[background]]`` layer with ``frames = 2``."""
    rng = random.Random(seed)
    colour = (*hex_rgb(BIRD_COLOUR), 255)
    image = Image.new("RGBA", (width, height * len(BIRD_FRAMES)))
    spots = []
    lead_x, lead_y = rng.randint(80, width - 80), rng.randint(*BIRD_BAND)
    for index in range(BIRDS):
        # Two loose skeins: each bird a little behind and beside the one before.
        if index == BIRDS // 2:
            lead_x = (lead_x + width // 2) % width
            lead_y = rng.randint(*BIRD_BAND)
        along = index % (BIRDS // 2 + 1)
        spots.append((lead_x + along * rng.randint(9, 14), lead_y + along * rng.randint(-5, 6)))
    for frame, rows in enumerate(BIRD_FRAMES):
        for number, (x, y) in enumerate(spots):
            # Neighbours beat out of step: every other bird shows the other frame.
            shape = BIRD_FRAMES[(frame + number) % len(BIRD_FRAMES)] if number % 2 else rows
            for row, line in enumerate(shape):
                for column, mark in enumerate(line):
                    if mark == "#":
                        image.putpixel(((x + column) % width, frame * height + y + row), colour)
    return image


def paint_cloud_sea(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Sky Ruins: a sunlit sky, far clouds, distant ruined islands and birds, above a sea
    of cloud in two banks that drift at different speeds."""
    return {
        "bg_0_sky.png": sunny_sky(mood),
        "bg_1_far_clouds.png": clouds(mood, seed, 7, (70, 150), (8, 13)),
        "bg_2_birds.png": birds(seed + 2),
        "bg_3_islands.png": islands(mood, seed + 1, 6, (120, 205), (10, 20)),
        "bg_4_far_bank.png": cloud_bank(mood, seed + 3, 236, 14, 22),
        "bg_5_near_bank.png": cloud_bank(mood, seed + 4, 286, 18, 34),
    }


PAINTERS["cloud_sea"] = paint_cloud_sea


# --- meadow hills (Twin Isles) -------------------------------------------------------------

LOW_SUN: Final[tuple[int, int]] = (432, 150)
FAR_HILLS: Final[tuple[str, str]] = ("92a984", "547e64")
NEAR_HILLS: Final[tuple[str, str]] = ("a2a947", "676633")
"""A range of hills: the colour of its sunlit crest, then of its slopes."""


def hills(
    colours: tuple[str, str],
    seed: int,
    crest: int,
    swell: int,
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a range of rolling hills along the bottom of the picture: the ridge is a few
    long waves about ``crest`` pixels down, ``swell`` pixels high, lit along its top. Whole
    waves fit the width, so the layer wraps."""
    rng = random.Random(seed)
    lit, slope = (hex_rgb(value) for value in colours)
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    assert pixels is not None
    waves = [
        (rng.randint(2, 4), rng.uniform(0.0, 6.28), 1.0),
        (rng.randint(5, 9), rng.uniform(0.0, 6.28), 0.4),
    ]
    for x in range(width):
        turn = 2.0 * math.pi * x / width
        ridge = sum(math.sin(turn * count + shift) * weight for count, shift, weight in waves)
        top = crest + round(ridge * swell / 1.4)
        for y in range(max(top, 0), height):
            # The crest is lit; a dithered band below it fades into the slope.
            depth = y - top
            sunlit = depth < 2 or (
                depth < 12 and (12 - depth) * 16 / 12 > BAYER_4[y % 4][x % 4] + 4
            )
            pixels[x, y] = (*(lit if sunlit else slope), 255)
    return image


def paint_meadow(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Twin Isles: a low sun in a golden-hour sky, lit clouds, far islands, and two ranges
    of hills rolling away below."""
    return {
        "bg_0_sky.png": sunny_sky(mood, LOW_SUN),
        "bg_1_far_clouds.png": clouds(mood, seed, 7, (60, 150), (9, 15)),
        "bg_2_islands.png": islands(mood, seed + 1, 5, (110, 190), (10, 18)),
        "bg_3_far_hills.png": hills(FAR_HILLS, seed + 2, 262, 12),
        "bg_4_near_hills.png": hills(NEAR_HILLS, seed + 3, 300, 16),
    }


PAINTERS["meadow"] = paint_meadow
