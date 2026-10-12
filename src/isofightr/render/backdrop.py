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
DUSK: Final[Mood] = Mood(
    sky=("323353", "484a77", "6b3e75", "a24b6f", "f68181", "fbb954"),
    cloud=("f68181", "a24b6f", "6b3e75"),
    island_top="484a77",
    island_side=("6b3e75", "323353"),
    ruin="fca790",
)
"""Dusk: indigo overhead, the last orange along the horizon (Lily Pads)."""
NIGHT: Final[Mood] = Mood(
    sky=("2e222f", "323353", "323353", "484a77"),
    cloud=("625565", "3e3546", "2e222f"),
    island_top="484a77",
    island_side=("3e3546", "2e222f"),
    ruin="7f708a",
)
"""Night: near black overhead, a deep blue toward the horizon (Final Plateau)."""
VOID: Final[Mood] = Mood(
    sky=("2e222f", "2e222f", "323353"),
    cloud=("484a77", "3e3546", "2e222f"),
    island_top="484a77",
    island_side=("3e3546", "2e222f"),
    ruin="4d65b4",
)
"""No sky at all: the dark of a room with the lights off (Training Grid)."""
EMBER: Final[Mood] = Mood(
    sky=("2e222f", "45293f", "6e2727", "b33831", "f57d4a"),
    cloud=("6e2727", "45293f", "2e222f"),
    island_top="45293f",
    island_side=("6e2727", "2e222f"),
    ruin="f57d4a",
)
"""Smoke lit from below: black overhead, red and orange toward the ground (Ember Forge)."""
DAWN: Final[Mood] = Mood(
    sky=("4d9be6", "8fd3ff", "c7dcd0", "fdcbb0"),
    cloud=("ffffff", "fdcbb0", "c7dcd0"),
    island_top="ffffff",
    island_side=("9babb2", "7f708a"),
    ruin="ffffff",
)
"""A cold, clear dawn: blue overhead paling to peach at the horizon (Frostpeak)."""
GLOW: Final[Mood] = Mood(
    sky=("2e222f", "323353", "6b3e75", "a24b6f", "f04f78"),
    cloud=("6b3e75", "484a77", "323353"),
    island_top="484a77",
    island_side=("6b3e75", "323353"),
    ruin="f04f78",
)
"""A city's night: dark overhead, the streets' light staining the horizon (Neon Circuit)."""
MOODS: Final[dict[str, Mood]] = {
    "day": DAY,
    "sunset": SUNSET,
    "golden": GOLDEN,
    "dusk": DUSK,
    "night": NIGHT,
    "void": VOID,
    "ember": EMBER,
    "dawn": DAWN,
    "glow": GLOW,
}
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


# --- the pond at dusk (Lily Pads) ----------------------------------------------------------

HORIZON: Final[int] = 232
"""Pixels down the picture to the pond's far shore."""
MOON_CENTRE: Final[tuple[int, int]] = (176, 64)
MOON_RADIUS: Final[int] = 15
MOON_HALO: Final[int] = 40
MOON_COLOURS: Final[tuple[str, str, str]] = ("ffffff", "fdcbb0", "eaaded")
"""The moon's face, its seas, and its halo."""
STAR_COLOURS: Final[tuple[str, str]] = ("ffffff", "eaaded")
STARS: Final[int] = 46
TREE_COLOURS: Final[tuple[str, str]] = ("484a77", "323353")
"""The far shore's trees: their tops against the sky, then the dark under them."""
PAD_COLOURS: Final[tuple[str, str, str]] = ("239063", "165a4c", "0b5e65")
"""A far lily pad: its lit rim, its leaf, its shadow on the water."""
FLOWER_COLOURS: Final[tuple[str, str]] = ("ffffff", "ed8099")
REED_COLOURS: Final[tuple[str, str]] = ("2e222f", "3e3546")
GLINT_COLOURS: Final[tuple[str, str]] = ("fdcbb0", "fca790")
GLINT_FRAMES: Final[int] = 3
GLINTS: Final[int] = 90


def dusk_pond(mood: Mood, seed: int) -> Image.Image:
    """Return the sky and the still water under it: stars, a moon with a halo, and below the
    horizon the same sky upside down, with the moon's light broken into a path of streaks."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (NATIVE_W, NATIVE_H))
    above = sky(mood, NATIVE_W, HORIZON)
    image.paste(above, (0, 0))
    pixels = image.load()
    assert pixels is not None
    for _ in range(STARS):
        x, y = rng.randrange(NATIVE_W), rng.randrange(HORIZON // 2)
        pixels[x, y] = (*hex_rgb(STAR_COLOURS[0 if y < HORIZON // 4 else 1]), 255)
    face, seas, halo = (hex_rgb(value) for value in MOON_COLOURS)
    centre_x, centre_y = MOON_CENTRE
    for y in range(centre_y - MOON_HALO, centre_y + MOON_HALO + 1):
        for x in range(centre_x - MOON_HALO, centre_x + MOON_HALO + 1):
            distance = ((x - centre_x) ** 2 + (y - centre_y) ** 2) ** 0.5
            if distance <= MOON_RADIUS:
                pixels[x, y] = (*face, 255)
            elif distance <= MOON_HALO:
                strength = 1.0 - (distance - MOON_RADIUS) / (MOON_HALO - MOON_RADIUS)
                if strength * strength * 12 > BAYER_4[y % 4][x % 4]:
                    pixels[x, y] = (*halo, 255)
    for dx, dy, radius in ((-5, -4, 4), (4, 3, 5), (5, -7, 2), (-6, 6, 2)):
        for y in range(centre_y + dy - radius, centre_y + dy + radius + 1):
            for x in range(centre_x + dx - radius, centre_x + dx + radius + 1):
                if (x - centre_x - dx) ** 2 + (y - centre_y - dy) ** 2 <= radius * radius:
                    pixels[x, y] = (*seas, 255)
    # The water mirrors the sky, squeezed into what is left of the picture.
    depth = NATIVE_H - HORIZON
    for y in range(HORIZON, NATIVE_H):
        source = HORIZON - 1 - (y - HORIZON) * (HORIZON - 1) // depth
        for x in range(NATIVE_W):
            pixels[x, y] = above.getpixel((x, source))
    # The moon's path: streaks that widen toward the viewer.
    for y in range(HORIZON + 3, NATIVE_H, 3):
        reach = 3 + (y - HORIZON) * 16 // depth
        for _ in range(2):
            start = centre_x + rng.randint(-reach, reach)
            for x in range(start - rng.randint(1, reach), start + rng.randint(1, reach)):
                pixels[x % NATIVE_W, y] = (*(face if rng.random() < 0.4 else seas), 255)
    return image


def treeline(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return the far shore: a dark line of round treetops along the horizon, and its
    reflection, fading, in the water under it. It wraps."""
    rng = random.Random(seed)
    top, under = (hex_rgb(value) for value in TREE_COLOURS)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    count = width // 14
    for index in range(count):
        x = int((index + rng.uniform(0.0, 1.0)) * width / count)
        radius = rng.randint(7, 17)
        tall = int(radius * rng.uniform(0.9, 1.5))
        for shift in (-width, 0, width):
            draw.ellipse(
                (x + shift - radius, HORIZON - tall - 4, x + shift + radius, HORIZON + 2), fill=top
            )
            draw.ellipse(
                (x + shift - radius + 3, HORIZON - tall + 3, x + shift + radius, HORIZON + 4),
                fill=under,
            )
    draw.rectangle((0, HORIZON - 5, width, HORIZON + 5), fill=under)
    draw.rectangle((0, HORIZON + 6, width, height), fill=(0, 0, 0, 0))
    pixels = image.load()
    assert pixels is not None
    # The reflection: a dithered band that thins out with distance from the shore.
    for y in range(HORIZON + 6, HORIZON + 22):
        strength = 1.0 - (y - HORIZON - 6) / 16
        for x in range(width):
            if strength * 16 > BAYER_4[y % 4][x % 4] + 2:
                pixels[x, y] = (*under, 255)
    return image


def far_pads(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return lily pads lying on the water, small near the far shore and large near the
    viewer, a few of them in flower. It wraps."""
    rng = random.Random(seed)
    rim, leaf, shade = (hex_rgb(value) for value in PAD_COLOURS)
    petal, heart = (hex_rgb(value) for value in FLOWER_COLOURS)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    rows = 9
    for row in range(rows):
        y = HORIZON + 22 + row * (height - HORIZON - 24) // rows
        size = 7 + row * 3
        for _ in range(max(3, 9 - row)):
            x = rng.randrange(width)
            wide = int(size * rng.uniform(0.8, 1.3))
            tall = max(2, wide * 3 // 8)
            for shift in (-width, 0, width):
                at = x + shift
                draw.ellipse((at - wide, y - tall + 2, at + wide, y + tall + 2), fill=shade)
                draw.ellipse((at - wide, y - tall, at + wide, y + tall), fill=rim)
                draw.ellipse((at - wide + 1, y - tall + 1, at + wide - 1, y + tall), fill=leaf)
                # The notch every lily pad has, as a wedge of shadow.
                draw.polygon(((at, y), (at + wide, y - 1), (at + wide, y + 2)), fill=shade)
                if wide > 12 and (x + row) % 3 == 0:
                    draw.ellipse((at - wide // 2 - 3, y - 4, at - wide // 2 + 3, y), fill=heart)
                    draw.ellipse((at - wide // 2 - 1, y - 3, at - wide // 2 + 1, y - 2), fill=petal)
    return image


def near_reeds(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return clumps of reeds and cattails standing up from the bottom of the picture, dark
    against the water. It wraps."""
    rng = random.Random(seed)
    dark, soft = (hex_rgb(value) for value in REED_COLOURS)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    clumps = 9
    for clump in range(clumps):
        centre = int((clump + rng.uniform(0.15, 0.85)) * width / clumps)
        for _ in range(rng.randint(7, 12)):
            foot = centre + rng.randint(-34, 34)
            tall = rng.randint(34, 92)
            lean = rng.randint(-9, 9)
            colour = dark if rng.random() < 0.7 else soft
            for shift in (-width, 0, width):
                tip = (foot + shift + lean, height - tall)
                draw.line(((foot + shift, height), tip), fill=colour, width=2)
                if tall > 60 and lean % 2 == 0:
                    draw.rectangle((tip[0] - 1, tip[1] + 4, tip[0] + 2, tip[1] + 14), fill=dark)
    return image


def glints(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return the light on the ripples as ``GLINT_FRAMES`` frames stacked top to bottom: each
    short streak shows on two frames in three, a pixel further along each time."""
    rng = random.Random(seed)
    bright, soft = (hex_rgb(value) for value in GLINT_COLOURS)
    image = Image.new("RGBA", (width, height * GLINT_FRAMES))
    for number in range(GLINTS):
        x = rng.randrange(width)
        y = rng.randrange(HORIZON + 8, height - 2)
        long = 2 + (y - HORIZON) * 7 // (height - HORIZON) + rng.randint(0, 2)
        colour = bright if rng.random() < 0.35 else soft
        for frame in range(GLINT_FRAMES):
            if (frame + number) % GLINT_FRAMES == 0:
                continue
            for step in range(long):
                image.putpixel(((x + step + frame) % width, frame * height + y), (*colour, 255))
    return image


def paint_pond(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Lily Pads: a moon over still water at dusk, thin clouds, the far shore's trees, lily
    pads lying on the pond, glints on its ripples, and reeds close by."""
    return {
        "bg_0_sky.png": dusk_pond(mood, seed),
        "bg_1_far_clouds.png": clouds(mood, seed + 1, 6, (70, 170), (9, 14)),
        "bg_2_treeline.png": treeline(seed + 2),
        "bg_3_glints.png": glints(seed + 3),
        "bg_4_pads.png": far_pads(seed + 4),
        "bg_5_reeds.png": near_reeds(seed + 5),
    }


PAINTERS["pond"] = paint_pond


# --- aurora over the peaks (Final Plateau) -------------------------------------------------

NIGHT_STARS: Final[int] = 170
TWINKLE_FRAMES: Final[int] = 2
AURORA_FRAMES: Final[int] = 3
AURORA_GREEN: Final[tuple[str, str, str]] = ("8ff8e2", "30e1b9", "0b8a8f")
AURORA_VIOLET: Final[tuple[str, str, str]] = ("eaaded", "a884f3", "6b3e75")
"""A curtain of the aurora: its bright lower hem, its body, its fading top."""
PEAK_COLOURS: Final[tuple[str, str, str]] = ("9babb2", "484a77", "323353")
"""The far mountains: snow on the side the aurora lights, rock, rock in shadow."""


def starfield(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return the stars as ``TWINKLE_FRAMES`` frames stacked top to bottom: most are steady,
    one in four is dimmer on the second frame, and a few big ones have a cross of rays."""
    rng = random.Random(seed)
    bright, dim = (hex_rgb(value) for value in STAR_COLOURS)
    faint = hex_rgb("7f708a")
    image = Image.new("RGBA", (width, height * TWINKLE_FRAMES))
    for number in range(NIGHT_STARS):
        x, y = rng.randrange(width), rng.randrange(height * 3 // 4)
        big = number % 17 == 0
        for frame in range(TWINKLE_FRAMES):
            twinkles = number % 4 == 0 and frame == 1
            colour = faint if twinkles else bright if number % 3 else dim
            image.putpixel((x, frame * height + y), (*colour, 255))
            if big and not twinkles:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if 0 <= y + dy < height:
                        image.putpixel(((x + dx) % width, frame * height + y + dy), (*dim, 255))
    return image


def aurora(
    colours: tuple[str, str, str],
    seed: int,
    hem: int,
    reach: int,
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a curtain of the aurora as ``AURORA_FRAMES`` frames stacked top to bottom. Its
    lower hem waves about ``hem`` pixels down the picture; rays rise from it up to ``reach``
    pixels, thinning as they go. From frame to frame the rays change length a little, which
    reads as a shimmer. Whole waves fit the width, so the layer wraps."""
    rng = random.Random(seed)
    edge, body, top = (hex_rgb(value) for value in colours)
    waves = [
        (rng.randint(1, 2), rng.uniform(0.0, 6.28), 1.0),
        (rng.randint(3, 5), rng.uniform(0.0, 6.28), 0.45),
    ]
    rays = [rng.uniform(0.35, 1.0) for _ in range(width // 3 + 1)]
    gaps = [(rng.randint(2, 3), rng.uniform(0.0, 6.28))]
    image = Image.new("RGBA", (width, height * AURORA_FRAMES))
    pixels = image.load()
    assert pixels is not None
    for frame in range(AURORA_FRAMES):
        for x in range(width):
            turn = 2.0 * math.pi * x / width
            wave = sum(math.sin(turn * count + shift) * weight for count, shift, weight in waves)
            low = hem + round(wave * 16)
            # The curtain is brightest where it folds toward the viewer and breaks between.
            strength = 0.55 + 0.45 * math.sin(turn * gaps[0][0] + gaps[0][1])
            if strength < 0.25:
                continue
            ray = rays[(x // 3 + frame * 7) % len(rays)] * 0.35 + rays[x // 3] * 0.65
            tall = max(6, round(reach * ray * strength))
            for step in range(tall):
                y = low - step
                if not 0 <= y < height:
                    continue
                fade = 1.0 - step / tall
                if fade * strength * 16 <= BAYER_4[y % 4][x % 4] + 1:
                    continue
                colour = edge if step < 2 else body if fade > 0.5 else top
                pixels[x, frame * height + y] = (*colour, 255)
    return image


def peaks(
    seed: int,
    crest: int,
    tall: int,
    colours: tuple[str, str, str] = PEAK_COLOURS,
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a range of sharp mountains along the bottom of the picture: their summits about
    ``crest`` pixels down and up to ``tall`` pixels high, snow on their left flanks. It
    wraps."""
    rng = random.Random(seed)
    snow, rock, shade = (hex_rgb(value) for value in colours)
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    count = 11
    foot = crest + tall
    draw.rectangle((0, foot - 6, width, height), fill=shade)
    for index in range(count):
        x = int((index + rng.uniform(0.2, 0.8)) * width / count)
        rise = int(tall * rng.uniform(0.45, 1.0))
        half = int(rise * rng.uniform(1.0, 1.5))
        summit = foot - rise
        for shift in (-width, 0, width):
            at = x + shift
            draw.polygon(((at - half, foot), (at, summit), (at + half, foot)), fill=shade)
            draw.polygon(((at - half, foot), (at, summit), (at + half // 5, foot)), fill=rock)
            cap = rise // 3
            draw.polygon(
                (
                    (at - cap, summit + cap),
                    (at, summit),
                    (at + cap // 5, summit + cap),
                    (at - cap // 3, summit + cap - 3),
                ),
                fill=snow,
            )
    return image


def paint_aurora(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Final Plateau: a night sky full of stars, two curtains of aurora, far snowy peaks and
    a sea of dark cloud below."""
    return {
        "bg_0_sky.png": sky(mood),
        "bg_1_stars.png": starfield(seed),
        "bg_2_aurora_far.png": aurora(AURORA_VIOLET, seed + 1, 118, 70),
        "bg_3_aurora.png": aurora(AURORA_GREEN, seed + 2, 176, 120),
        "bg_4_peaks.png": peaks(seed + 3, 214, 60),
        "bg_5_bank.png": cloud_bank(mood, seed + 4, 300, 14, 30),
    }


PAINTERS["aurora"] = paint_aurora


# --- the holo-room (Training Grid) ---------------------------------------------------------

LATTICE_FAR: Final[tuple[str, int]] = ("3e3546", 160)
LATTICE_NEAR: Final[tuple[str, int]] = ("484a77", 320)
"""A lattice of the room's walls: the colour of its lines and the width of one diamond in
pixels (it must divide the layer's width, so the layer wraps)."""
PANEL_COLOURS: Final[tuple[str, str, str]] = ("4d65b4", "484a77", "4d9be6")
"""Read-outs floating in the room: their frames, their dim bars, their lit bars."""
PANEL_FRAMES: Final[int] = 2
PANELS: Final[int] = 14


def lattice(
    style: tuple[str, int], fade_from: int, width: int = LAYER_WIDTH, height: int = NATIVE_H
) -> Image.Image:
    """Return a lattice of diamonds in the game's own 2:1 slope, as if the grid went on
    across the walls of a room. Above ``fade_from`` pixels down it thins out to nothing."""
    colour, cell = hex_rgb(style[0]), style[1]
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        strength = min(1.0, 0.25 + 0.75 * y / max(fade_from, 1))
        for x in range(width):
            on_line = (x + 2 * y) % cell < 2 or (x - 2 * y) % cell < 2
            if on_line and strength * 16 > BAYER_4[y % 4][(x // 2) % 4]:
                pixels[x, y] = (*colour, 255)
    return image


def readouts(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return read-outs floating in the room as ``PANEL_FRAMES`` frames stacked top to
    bottom: framed panels of bars, one bar of each lit on alternate frames."""
    rng = random.Random(seed)
    frame_colour, dim, lit = (hex_rgb(value) for value in PANEL_COLOURS)
    image = Image.new("RGBA", (width, height * PANEL_FRAMES))
    draw = ImageDraw.Draw(image)
    for number in range(PANELS):
        x = int((number + rng.uniform(0.1, 0.9)) * width / PANELS)
        y = rng.randint(24, height - 90)
        wide, rows = rng.randint(22, 44), rng.randint(3, 6)
        tall = rows * 4 + 5
        lengths = [rng.randint(4, wide - 8) for _ in range(rows)]
        for frame in range(PANEL_FRAMES):
            top = frame * height + y
            for shift in (-width, 0, width):
                left = x + shift
                draw.rectangle((left, top, left + wide, top + tall), outline=frame_colour)
                draw.rectangle((left, top, left + 5, top + 1), fill=lit)
                for row, long in enumerate(lengths):
                    colour = lit if (row + number + frame) % rows == 0 else dim
                    bar_y = top + 4 + row * 4
                    draw.rectangle((left + 3, bar_y, left + 3 + long, bar_y + 1), fill=colour)
    return image


def paint_holo(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Training Grid: a dark room whose walls carry the grid on, far and near, with read-outs
    floating in it."""
    return {
        "bg_0_sky.png": sky(mood),
        "bg_1_far_lattice.png": lattice(LATTICE_FAR, 200),
        "bg_2_readouts.png": readouts(seed),
        "bg_3_near_lattice.png": lattice(LATTICE_NEAR, 330),
    }


PAINTERS["holo"] = paint_holo


# --- the volcano (Ember Forge) -------------------------------------------------------------

CONE_COLOURS: Final[tuple[str, str, str]] = ("6e2727", "45293f", "2e222f")
"""The volcano: the side its crater lights, its flank, its far side."""
LAVA_COLOURS: Final[tuple[str, str, str]] = ("fbff86", "f79617", "ea4f36")
"""Molten rock: white-hot, flowing, cooling."""
RIDGE_COLOURS: Final[tuple[str, str]] = ("45293f", "2e222f")
LAVA_FRAMES: Final[int] = 2
CRATER: Final[tuple[int, int]] = (184, 96)
"""Where the crater's lip is on the volcano's layer."""


def ember_sky(mood: Mood) -> Image.Image:
    """Return the mood's sky with the crater's glow thrown up into the smoke above where the
    volcano stands (a sky and a layer with no parallax are drawn the same distance off, so
    the crater's own x is the glow's)."""
    image = sky(mood)
    pixels = image.load()
    assert pixels is not None
    glow = hex_rgb(LAVA_COLOURS[2])
    centre_x, centre_y = CRATER[0], CRATER[1] - 14
    reach_x, reach_y = 120, 64
    for y in range(max(centre_y - reach_y, 0), centre_y + reach_y):
        for x in range(centre_x - reach_x, centre_x + reach_x):
            distance = (((x - centre_x) / reach_x) ** 2 + ((y - centre_y) / reach_y) ** 2) ** 0.5
            if distance < 1.0 and (1.0 - distance) ** 2 * 16 > BAYER_4[y % 4][x % 4]:
                pixels[x % NATIVE_W, y] = (*glow, 255)
    return image


def volcano(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return the volcano as ``LAVA_FRAMES`` frames stacked top to bottom: a broad cone with
    a broken crater, lava running down it in three streams whose bright beads move from one
    frame to the next, and lower cones either side. It wraps."""
    rng = random.Random(seed)
    lit, flank, far = (hex_rgb(value) for value in CONE_COLOURS)
    hot, flow, cool = (hex_rgb(value) for value in LAVA_COLOURS)
    image = Image.new("RGBA", (width, height * LAVA_FRAMES))
    draw = ImageDraw.Draw(image)
    crater_x, crater_y = CRATER
    foot = 300
    cones = [(crater_x, crater_y, 330, True)]
    for _ in range(4):
        cones.append((rng.randrange(width), rng.randint(190, 240), rng.randint(110, 190), False))
    streams = [(-26, 0.62), (4, 0.9), (30, 0.5)]
    for frame in range(LAVA_FRAMES):
        top = frame * height
        for x, y, half, main in sorted(cones, key=lambda cone: cone[3]):
            for shift in (-width, 0, width):
                at = x + shift
                lip = 34 if main else 12
                draw.polygon(
                    (
                        (at - half, top + foot),
                        (at - lip, top + y),
                        (at + lip, top + y),
                        (at + half, top + foot),
                    ),
                    fill=far,
                )
                draw.polygon(
                    (
                        (at - half, top + foot),
                        (at - lip, top + y),
                        (at + lip // 3, top + y),
                        (at - half // 6, top + foot),
                    ),
                    fill=flank,
                )
                if main:
                    draw.polygon(
                        (
                            (at - lip, top + y),
                            (at + lip, top + y),
                            (at + lip - 8, top + y + 7),
                            (at - lip + 10, top + y + 5),
                        ),
                        fill=flow,
                    )
                    draw.line(((at - lip, top + y), (at + lip, top + y)), fill=hot, width=2)
                    draw.polygon(
                        (
                            (at - lip, top + y),
                            (at - lip - 22, top + y + 40),
                            (at - lip + 6, top + y + 34),
                            (at - lip + 12, top + y + 5),
                        ),
                        fill=lit,
                    )
        draw.rectangle((0, top + foot, width, top + height), fill=far)
        # The streams: each wanders down the cone, hot beads sliding along it.
        for number, (start, share) in enumerate(streams):
            walk = random.Random(seed * 31 + number)
            x, y = crater_x + start, crater_y + 4
            step = 0
            while y < crater_y + (foot - crater_y) * share:
                x += walk.choice((-1, 0, 0, 1)) + (1 if start > 0 else -1 if start < -10 else 0)
                y += 2
                bead = (step + frame * 3) % 6 == 0
                colour = hot if bead else flow if step % 5 else cool
                for shift in (-width, 0, width):
                    draw.rectangle((x + shift, top + y, x + shift + 2, top + y + 1), fill=colour)
                step += 1
    return image


def lava_plain(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return the ground near the viewer as ``LAVA_FRAMES`` frames stacked top to bottom: a
    jagged ridge of black rock with a river of lava beyond it, whose glints move. It wraps."""
    rng = random.Random(seed)
    rock, shade = (hex_rgb(value) for value in RIDGE_COLOURS)
    hot, flow, cool = (hex_rgb(value) for value in LAVA_COLOURS)
    image = Image.new("RGBA", (width, height * LAVA_FRAMES))
    draw = ImageDraw.Draw(image)
    river = 296
    teeth = []
    x = 0
    while x < width:
        wide = rng.randint(14, 44)
        teeth.append((x, wide, rng.randint(8, 34)))
        x += wide - 4
    glints = [
        (rng.randrange(width), river + rng.randint(3, 20), rng.randint(4, 12)) for _ in range(60)
    ]
    for frame in range(LAVA_FRAMES):
        top = frame * height
        draw.rectangle((0, top + river, width, top + river + 26), fill=flow)
        draw.line(((0, top + river), (width, top + river)), fill=cool, width=2)
        for number, (gx, gy, long) in enumerate(glints):
            colour = hot if (number + frame) % 2 else cool
            at = (gx + frame * 3) % width
            draw.line(((at, top + gy), (at + long, top + gy)), fill=colour)
        draw.rectangle((0, top + river + 24, width, top + height), fill=shade)
        for tx, wide, tall in teeth:
            for shift in (-width, 0, width):
                at = tx + shift
                base = top + river + 26
                draw.polygon(
                    ((at, base), (at + wide // 2, base - tall), (at + wide, base)), fill=shade
                )
                draw.polygon(
                    ((at, base), (at + wide // 2, base - tall), (at + wide // 2 + 2, base)),
                    fill=rock,
                )
    return image


def paint_volcano(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Ember Forge: a sky of smoke lit from below, drifting smoke, a volcano running with
    lava, and a river of it beyond a ridge of black rock."""
    return {
        "bg_0_sky.png": ember_sky(mood),
        "bg_1_smoke.png": clouds(mood, seed, 7, (40, 130), (12, 20)),
        "bg_2_volcano.png": volcano(seed + 1),
        "bg_3_near_smoke.png": clouds(mood, seed + 2, 4, (150, 230), (16, 24)),
        "bg_4_plain.png": lava_plain(seed + 3),
    }


PAINTERS["volcano"] = paint_volcano


# --- snowy peaks at dawn (Frostpeak) -------------------------------------------------------

DAWN_SUN: Final[tuple[int, int]] = (150, 176)
FAR_SNOW_PEAKS: Final[tuple[str, str, str]] = ("ffffff", "c7dcd0", "9babb2")
NEAR_SNOW_PEAKS: Final[tuple[str, str, str]] = ("ffffff", "9babb2", "7f708a")
"""A range of snowy mountains: their sunlit snow, their rock, their rock in shadow."""


def paint_peaks(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Frostpeak: a low sun in a clear dawn sky, thin clouds, two ranges of snowy mountains,
    and a bank of cloud lying in the valley below."""
    return {
        "bg_0_sky.png": sunny_sky(mood, DAWN_SUN),
        "bg_1_far_clouds.png": clouds(mood, seed, 6, (50, 130), (10, 16)),
        "bg_2_far_peaks.png": peaks(seed + 1, 150, 90, FAR_SNOW_PEAKS),
        "bg_3_near_peaks.png": peaks(seed + 2, 200, 100, NEAR_SNOW_PEAKS),
        "bg_4_bank.png": cloud_bank(mood, seed + 3, 304, 12, 30),
    }


PAINTERS["peaks"] = paint_peaks


# --- the city at night (Neon Circuit) ------------------------------------------------------

FAR_TOWERS: Final[tuple[str, str]] = ("484a77", "6b3e75")
NEAR_TOWERS: Final[tuple[str, str]] = ("2e222f", "323353")
"""A row of towers: their walls, and the edge the city's glow catches."""
WINDOW_COLOURS: Final[tuple[str, ...]] = ("f9c22b", "f9c22b", "8ff8e2", "f04f78")
CITY_FRAMES: Final[int] = 2
TRAFFIC_COLOURS: Final[tuple[str, str]] = ("f04f78", "8ff8e2")
TRAFFIC: Final[int] = 9


def skyline(
    colours: tuple[str, str],
    seed: int,
    crest: int,
    tall: int,
    lit: float,
    width: int = LAYER_WIDTH,
    height: int = NATIVE_H,
) -> Image.Image:
    """Return a row of towers as ``CITY_FRAMES`` frames stacked top to bottom: flat roofs
    about ``crest`` pixels down, up to ``tall`` higher, some with a mast; a share ``lit`` of
    their windows are on, and a few of those go off on the second frame. It wraps."""
    rng = random.Random(seed)
    wall, edge = (hex_rgb(value) for value in colours)
    panes = [hex_rgb(value) for value in WINDOW_COLOURS]
    image = Image.new("RGBA", (width, height * CITY_FRAMES))
    draw = ImageDraw.Draw(image)
    towers = []
    x = 0
    while x < width:
        wide = rng.randint(22, 58)
        towers.append((x, min(wide, width - x), crest - rng.randint(0, tall), rng.random() < 0.25))
        x += wide
    for frame in range(CITY_FRAMES):
        top = frame * height
        flicker = random.Random(seed * 7 + 1)
        for left, wide, roof, mast in towers:
            draw.rectangle((left, top + roof, left + wide - 1, top + height), fill=wall)
            draw.line(((left, top + roof), (left, top + height)), fill=edge)
            draw.line(((left, top + roof), (left + wide - 1, top + roof)), fill=edge)
            if mast:
                middle = left + wide // 2
                draw.line(((middle, top + roof - 14), (middle, top + roof)), fill=edge)
            colour = panes[(left // 7) % len(panes)]
            for wy in range(roof + 5, height - 4, 6):
                for wx in range(left + 4, left + wide - 4, 5):
                    on = flicker.random() < lit
                    blinks = flicker.random() < 0.08
                    if on and not (blinks and frame == 1):
                        draw.rectangle((wx, top + wy, wx + 1, top + wy + 2), fill=colour)
    return image


def traffic(seed: int, width: int = LAYER_WIDTH, height: int = NATIVE_H) -> Image.Image:
    """Return a few lights crossing the sky (a layer that scrolls by itself): each a bright
    pixel with a short tail."""
    rng = random.Random(seed)
    image = Image.new("RGBA", (width, height))
    for number in range(TRAFFIC):
        x, y = rng.randrange(width), rng.randint(30, 150)
        colour = hex_rgb(TRAFFIC_COLOURS[number % len(TRAFFIC_COLOURS)])
        for tail in range(5):
            if tail in (0, 1, 3):
                image.putpixel(((x - tail) % width, y), (*colour, 255))
    return image


def paint_city(mood: Mood, seed: int) -> dict[str, Image.Image]:
    """Neon Circuit: a night sky glowing at the horizon, lights crossing it, and two rows of
    towers whose windows go on and off."""
    return {
        "bg_0_sky.png": sky(mood),
        "bg_1_traffic.png": traffic(seed),
        "bg_2_far_towers.png": skyline(FAR_TOWERS, seed + 1, 190, 60, 0.18),
        "bg_3_near_towers.png": skyline(NEAR_TOWERS, seed + 2, 262, 70, 0.3),
    }


PAINTERS["city"] = paint_city
