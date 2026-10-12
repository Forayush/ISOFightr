"""How stage hazards look: the warning on the ground, and the thing itself (decision D-063).

Plan note "09 - Art Direction" ("Hazards"). A hazard must be read before it hurts: a geyser's
ground glows and brightens for its whole warning, lightning marks its circle, a wind sends a
few streaks ahead of itself. Then the geyser is a column of fire, the lightning a jagged bolt
with a bright ring, the wind many streaks.

Every colour is a Resurrect 64 entry. Drawn with Pillow; pure Python (no ``arcade``).
"""

from __future__ import annotations

import math
from typing import Final

from PIL import Image, ImageDraw

from isofightr.config import TILE_H, TILE_W, Z_PX

Rgba = tuple[int, int, int, int]
BAYER_4: Final[tuple[tuple[int, ...], ...]] = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
ROOT_TWO: Final[float] = math.sqrt(2.0)
WARN_LEVELS: Final[int] = 4
"""How many steps a warning brightens in before the hazard goes off."""
ACTIVE_LEVEL: Final[int] = WARN_LEVELS
JET_FRAMES: Final[int] = 3
BOLT_FRAMES: Final[int] = 2
STREAK_LENGTHS: Final[tuple[int, ...]] = (7, 11)
STREAK_DIRECTIONS: Final[int] = 16


def _rgba(value: str) -> Rgba:
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


CLEAR: Final[Rgba] = (0, 0, 0, 0)
MARK_COLOURS: Final[dict[str, tuple[Rgba, Rgba, Rgba]]] = {
    # kind: (rim, glow, hot)
    "geyser": (_rgba("ea4f36"), _rgba("f79617"), _rgba("fbff86")),
    "lightning": (_rgba("484a77"), _rgba("fbff86"), _rgba("ffffff")),
}
FIRE: Final[tuple[Rgba, Rgba, Rgba, Rgba]] = (
    _rgba("b33831"),
    _rgba("ea4f36"),
    _rgba("f79617"),
    _rgba("fbff86"),
)
"""A jet of fire from its dark edge to its bright core."""
BOLT: Final[tuple[Rgba, Rgba]] = (_rgba("8ff8e2"), _rgba("ffffff"))
STREAK: Final[tuple[Rgba, Rgba, Rgba]] = (_rgba("ffffff"), _rgba("8fd3ff"), _rgba("4d65b4"))
"""A wind streak's head, its tail, and the dark line under it that makes it read on pale
ground as well as on dark."""


def mark_size(radius: float) -> tuple[int, int]:
    """Return the pixel size of a circle of ``radius`` units lying on the ground: in this
    projection a circle is an ellipse twice as wide as it is tall."""
    half_w = max(round(radius * TILE_W / 2 * ROOT_TWO), 3)
    half_h = max(round(radius * TILE_H / 2 * ROOT_TWO), 2)
    return (2 * half_w + 1, 2 * half_h + 1)


def build_mark(kind: str, radius: float, level: int, turn: int = 0) -> Image.Image:
    """Return a hazard's mark on the ground: a broken rim with a glow inside that fills in
    as ``level`` rises from 0 to ``ACTIVE_LEVEL`` (the hazard is then going off). ``turn``
    walks the rim's gaps round, so the mark crawls."""
    rim, glow, hot = MARK_COLOURS[kind]
    width, height = mark_size(radius)
    image = Image.new("RGBA", (width, height), CLEAR)
    pixels = image.load()
    assert pixels is not None
    half_w, half_h = width // 2, height // 2
    density = (3, 6, 9, 12, 16)[min(max(level, 0), ACTIVE_LEVEL)]
    for y in range(height):
        for x in range(width):
            across, down = (x - half_w) / half_w, (y - half_h) / half_h
            distance = math.hypot(across, down)
            if distance > 1.0:
                continue
            if distance > 1.0 - 2.4 / half_w:
                angle = math.atan2(down, across)
                dash = int((angle + math.pi) / (2 * math.pi) * 16 + turn) % 2
                if dash == 0 or level >= ACTIVE_LEVEL:
                    pixels[x, y] = rim
                continue
            # The glow is thickest in the middle and thins toward the rim.
            if (1.0 - distance) * density > BAYER_4[y % 4][x % 4]:
                core = level >= ACTIVE_LEVEL - 1 and distance < 0.45
                pixels[x, y] = hot if core else glow
    return image


def build_jet(radius: float, height: float, frame: int, grown: float = 1.0) -> Image.Image:
    """Return one frame of a geyser's column of fire, ``height`` units tall at full size
    (``grown`` from 0 to 1 is how far up it has come). Its foot is the image's bottom
    middle."""
    half_w = max(round(radius * TILE_W / 2 * 0.8), 4)
    tall = max(round(height * Z_PX * min(max(grown, 0.05), 1.0)), 6)
    image = Image.new("RGBA", (2 * half_w + 5, tall + 4), CLEAR)
    pixels = image.load()
    assert pixels is not None
    centre = image.width // 2
    for y in range(image.height):
        up = (image.height - 1 - y) / image.height  # 0 at the foot, 1 at the top
        # The column narrows to a plume at the top and its edge flickers frame by frame.
        taper = 1.0 - up**3 * 0.75
        wobble = math.sin(y * 0.55 + frame * 2.1) * 1.4 + math.sin(y * 0.21 - frame * 1.3) * 0.9
        reach = half_w * taper + wobble
        for x in range(image.width):
            off = abs(x - centre)
            if off > reach:
                continue
            depth = 1.0 - off / max(reach, 1.0)  # 0 at the edge, 1 in the core
            band = min(int(depth * 4 + (0.6 if (x + y + frame) % 3 == 0 else 0.0)), 3)
            if up > 0.8 and band > 1:
                band -= 1  # the top cools
            pixels[x, y] = FIRE[band]
    return image


def build_bolt(height: float, frame: int) -> Image.Image:
    """Return one frame of a lightning bolt ``height`` units long, striking the image's
    bottom middle."""
    tall = max(round(height * Z_PX), 12)
    width = 25
    image = Image.new("RGBA", (width, tall), CLEAR)
    draw = ImageDraw.Draw(image)
    centre = width // 2
    points = [(centre, tall - 1)]
    segments = max(tall // 14, 3)
    for index in range(1, segments + 1):
        # A fixed zigzag (no randomness): each frame leans the other way.
        lean = ((index * 7 + frame * 5) % 9 - 4) * 2
        y = tall - 1 - index * tall // segments
        points.append((centre + lean, max(y, 0)))
    draw.line(points, fill=BOLT[0], width=3)
    draw.line(points, fill=BOLT[1], width=1)
    # A short fork a third of the way up.
    fork_x, fork_y = points[max(segments // 3, 1)]
    side = 6 if frame % 2 == 0 else -6
    draw.line([(fork_x, fork_y), (fork_x + side, fork_y + 9)], fill=BOLT[0], width=1)
    return image


def streak_direction(dx: float, dy: float) -> int:
    """Return which of ``STREAK_DIRECTIONS`` screen directions a screen vector points in."""
    turn = math.atan2(dy, dx) / (2 * math.pi)
    return round(turn * STREAK_DIRECTIONS) % STREAK_DIRECTIONS


def build_streak(direction: int, size: int) -> Image.Image:
    """Return a streak of wind: a short bright line fading at its tail, pointing along one
    of ``STREAK_DIRECTIONS`` screen directions (0 = right, counting anticlockwise)."""
    length = STREAK_LENGTHS[size % len(STREAK_LENGTHS)]
    angle = direction * 2 * math.pi / STREAK_DIRECTIONS
    side = 2 * length + 3
    image = Image.new("RGBA", (side, side), CLEAR)
    draw = ImageDraw.Draw(image)
    centre = side // 2
    head = (centre + math.cos(angle) * length, centre - math.sin(angle) * length)
    tail = (centre - math.cos(angle) * length, centre + math.sin(angle) * length)
    under = [(tail[0], tail[1] + 1), (head[0], head[1] + 1)]
    draw.line(under, fill=STREAK[2], width=1)
    draw.line([tail, (centre, centre)], fill=STREAK[1], width=1)
    draw.line([(centre, centre), head], fill=STREAK[0], width=1)
    return image
