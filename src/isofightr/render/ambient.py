"""Ambient particles: a few slow sprites drifting across a stage (decision D-063).

Plan note "03 - Isometric World and Rendering" ("Ambience"). A stage's ``[ambient]`` table
names a kind (leaves, snow, embers...) and how many (at most ``AMBIENT_MAX``); some drift
behind the world and some in front. Where each one is on a tick is a fixed function of the
tick, so nothing is stored and nothing is random. The ones in front never cover a fighter: the
renderer hides any that would (:func:`covers`). With "reduce flashing" on they neither blink
nor turn.

Every colour is a Resurrect 64 entry. Pure Python (no ``arcade``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.sim.stage import Ambient

Rgba = tuple[int, int, int, int]
WRAP_MARGIN: Final[int] = 16
"""Sprites wrap this far outside the screen, so they never pop in or out on it."""
BACK_PARALLAX: Final[float] = 0.3
FRONT_PARALLAX: Final[float] = 1.0
"""How much of the camera's movement a sprite follows: the ones in front move with the world."""
FIGHTER_CLEARANCE: Final[int] = 3
"""A sprite in front is hidden within this many pixels of a fighter."""


def _rgba(value: str) -> Rgba:
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


@dataclass(frozen=True, slots=True)
class Style:
    """How one kind of ambient sprite looks and moves."""

    drift_x: float
    """Pixels per tick to the right (negative: to the left)."""
    drift_y: float
    """Pixels per tick upward (negative: falling)."""
    sway: float
    """How far it wanders sideways around its path, in pixels."""
    sway_ticks: int
    frames: tuple[tuple[str, ...], ...]
    """Each frame as rows of palette letters (``.`` is empty)."""
    colours: dict[str, Rgba]
    frame_ticks: int = 10
    blinks: bool = False
    """Whether it goes dark for part of its cycle (fireflies, sparks)."""


LEAF: Final[dict[str, Rgba]] = {"a": _rgba("91db69"), "b": _rgba("239063")}
PETAL: Final[dict[str, Rgba]] = {"a": _rgba("fdcbb0"), "b": _rgba("f68181")}
SNOW: Final[dict[str, Rgba]] = {"a": _rgba("ffffff"), "b": _rgba("c7dcd0")}
EMBER: Final[dict[str, Rgba]] = {"a": _rgba("fbb954"), "b": _rgba("ea4f36")}
GLOW: Final[dict[str, Rgba]] = {"a": _rgba("fbff86"), "b": _rgba("d5e04b")}
SAND: Final[dict[str, Rgba]] = {"a": _rgba("fbb954"), "b": _rgba("e6904e")}
RAIN: Final[dict[str, Rgba]] = {"a": _rgba("8fd3ff"), "b": _rgba("4d9be6")}
SPARK: Final[dict[str, Rgba]] = {"a": _rgba("8ff8e2"), "b": _rgba("30e1b9")}
MOTE: Final[dict[str, Rgba]] = {"a": _rgba("ffffff"), "b": _rgba("8fd3ff")}

STYLES: Final[dict[str, Style]] = {
    "leaves": Style(-0.35, -0.22, 6.0, 150, (("ab.", ".ab"), (".a", "ab", "b."), ("aab",)), LEAF),
    "petals": Style(-0.25, -0.16, 8.0, 180, (("a.", "ab"), ("ab",), (".a", "ba")), PETAL),
    "motes": Style(0.06, 0.05, 5.0, 240, (("a",), ("b",)), MOTE, frame_ticks=40),
    "snow": Style(-0.08, -0.3, 5.0, 200, (("a",), ("ab", "b.")), SNOW, frame_ticks=30),
    "embers": Style(0.05, 0.28, 4.0, 120, (("a",), ("b",), ("ab",)), EMBER, blinks=True),
    "fireflies": Style(0.04, 0.02, 12.0, 260, (("a",), (".b.", "bab", ".b.")), GLOW, 24, True),
    "sand": Style(-0.9, -0.04, 2.0, 90, (("ab",), ("aab",)), SAND),
    "rain": Style(-0.6, -2.4, 0.0, 60, ((".a", ".a", "b.", "b."),), RAIN),
    "sparks": Style(-0.1, -0.5, 3.0, 80, (("a",), ("b",)), SPARK, 6, True),
}
"""One style per name in ``config.AMBIENT_KINDS`` (a test checks they match)."""
BLINK_CYCLE: Final[int] = 5
"""A blinking sprite is dark for one part in this many of its cycle."""


@dataclass(frozen=True, slots=True)
class Mote:
    """One ambient sprite on one tick."""

    x: int
    """Screen pixel of its middle (0 = the screen's left edge)."""
    y: int
    """Screen pixel of its middle, counted up from the bottom."""
    frame: int
    front: bool
    visible: bool = True


def _scatter(index: int, salt: int) -> float:
    """Return a fixed number in 0..1 for a sprite: the same every match."""
    mixed = (index * 2654435761 + salt * 40503) & 0xFFFFFFFF
    mixed = ((mixed ^ (mixed >> 15)) * 2246822519) & 0xFFFFFFFF
    return ((mixed ^ (mixed >> 13)) & 0xFFFF) / 0x10000


def motes(
    ambient: Ambient | None, tick: int, camera_centre: tuple[int, int], calm: bool = False
) -> list[Mote]:
    """Return where every ambient sprite of a stage is on a tick, the ones in front last.

    ``camera_centre`` is the world pixel in the middle of the screen: sprites shift against
    it by their layer's parallax. ``calm`` is the "reduce flashing" setting.
    """
    if ambient is None:
        return []
    style = STYLES[ambient.kind]
    wide, tall = NATIVE_W + 2 * WRAP_MARGIN, NATIVE_H + 2 * WRAP_MARGIN
    found = []
    for index in range(ambient.count):
        front = index >= ambient.count - ambient.front
        parallax = FRONT_PARALLAX if front else BACK_PARALLAX
        speed = 0.7 + 0.6 * _scatter(index, 1)
        turn = 2 * math.pi * (tick / style.sway_ticks + _scatter(index, 2))
        x = _scatter(index, 3) * wide + style.drift_x * speed * tick + style.sway * math.sin(turn)
        y = _scatter(index, 4) * tall + style.drift_y * speed * tick
        x -= camera_centre[0] * parallax
        y -= camera_centre[1] * parallax
        cycle = tick // style.frame_ticks + index
        frame = 0 if calm else cycle % len(style.frames)
        visible = calm or not style.blinks or (cycle // len(style.frames)) % BLINK_CYCLE != 0
        found.append(
            Mote(
                round(x % wide) - WRAP_MARGIN, round(y % tall) - WRAP_MARGIN, frame, front, visible
            )
        )
    return found


def covers(mote: Mote, rects: list[tuple[float, float, float, float]]) -> bool:
    """Return whether a sprite in front would sit on a fighter: ``rects`` are the fighters'
    ``(left, bottom, right, top)`` on screen."""
    reach = FIGHTER_CLEARANCE
    return any(
        left - reach <= mote.x <= right + reach and bottom - reach <= mote.y <= top + reach
        for left, bottom, right, top in rects
    )


def build_mote(kind: str, frame: int) -> Image.Image:
    """Return one frame of an ambient sprite."""
    style = STYLES[kind]
    rows = style.frames[frame % len(style.frames)]
    image = Image.new("RGBA", (max(len(row) for row in rows), len(rows)))
    for y, row in enumerate(rows):
        for x, letter in enumerate(row):
            if letter != ".":
                image.putpixel((x, y), style.colours[letter])
    return image
