"""What to draw for a stage's hazards on a frame (decision D-063).

Plan note "03 - Isometric World and Rendering" ("Hazards"). Everything is a function of the
stage and the match frame, like the hazards themselves: the marks on the ground are ground
items (clipped to their surface and depth-sorted like any decal, D-060); jets, bolts and wind
streaks are effects drawn over the world.

With "reduce flashing" on, nothing alternates frame by frame: a jet holds one shape and a
bolt does not flicker. Pure Python (no ``arcade``).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Final

from PIL import Image

from isofightr.render import hazard_art as art
from isofightr.render.ground_items import DECAL_RANK, GroundItem
from isofightr.render.iso import project
from isofightr.sim.stage import Hazard, Stage

HAZARD_DECAL_BASE: Final[int] = 1 << 18
"""Ground item ids of hazard marks start here, above projectiles' and effects' items."""
MARK_TURN_TICKS: Final[int] = 6
"""Ticks between steps of a mark's crawling rim."""
JET_FRAME_TICKS: Final[int] = 3
JET_GROW_TICKS: Final[int] = 5
"""A jet takes this long to rise to full height, and as long to fall."""
BOLT_FRAME_TICKS: Final[int] = 2
STREAKS_WARN: Final[int] = 5
STREAKS_ACTIVE: Final[int] = 14
STREAK_LIFE: Final[int] = 36
"""Ticks a wind streak lives before it starts again from its own place."""
STREAK_SPEED: Final[float] = 6.0
"""How much faster than the wind's push a streak travels (it shows the wind, not a body)."""


@dataclass(frozen=True, slots=True)
class HazardSprite:
    """One effect of a hazard, drawn over the world."""

    key: tuple[object, ...]
    """What the image looks like: equal keys share a texture."""
    build: Callable[[], Image.Image]
    x: float
    """World pixel of the image's horizontal middle."""
    bottom: float
    """World pixel of the image's bottom edge."""


def warn_level(hazard: Hazard, into: int) -> int:
    """Return how bright a warning is ``into`` frames after it began (0 up to one short of
    ``hazard_art.ACTIVE_LEVEL``)."""
    return min(into * art.WARN_LEVELS // max(hazard.warn, 1), art.WARN_LEVELS - 1)


def ground_marks(stage: Stage, frame: int, calm: bool = False) -> list[GroundItem]:
    """Return the marks geysers and lightning put on the ground while they warn and while
    they are active."""
    marks = []
    for index, hazard in enumerate(stage.hazards):
        if hazard.kind not in art.MARK_COLOURS:
            continue
        phase, into, _ = hazard.moment(frame)
        if phase == "rest":
            continue
        level = art.ACTIVE_LEVEL if phase == "active" else warn_level(hazard, into)
        turn = 0 if calm else (frame // MARK_TURN_TICKS) % 2
        key = ("hazard-mark", hazard.kind, hazard.radius, level, turn)
        marks.append(
            GroundItem(
                HAZARD_DECAL_BASE + index,
                hazard.x,
                hazard.y,
                hazard.z,
                key,
                partial(art.build_mark, hazard.kind, hazard.radius, level, turn),
                DECAL_RANK,
            )
        )
    return marks


def _scatter(index: int, salt: int) -> float:
    mixed = (index * 2654435761 + salt * 40503) & 0xFFFFFFFF
    mixed = ((mixed ^ (mixed >> 15)) * 2246822519) & 0xFFFFFFFF
    return ((mixed ^ (mixed >> 13)) & 0xFFFF) / 0x10000


def _streaks(index: int, hazard: Hazard, frame: int, count: int) -> list[HazardSprite]:
    """Return a wind's streaks: each starts at its own fixed place in the wind's cylinder,
    travels down the wind and starts again."""
    push = hazard.push
    ahead = project(push.x, push.y, push.z)
    direction = art.streak_direction(ahead[0], ahead[1])
    sprites = []
    for number in range(count):
        age = (frame + round(_scatter(number, index + 1) * STREAK_LIFE)) % STREAK_LIFE
        turn = 2 * math.pi * _scatter(number, index + 7)
        out = hazard.radius * math.sqrt(_scatter(number, index + 13))
        travelled = age - STREAK_LIFE / 2
        x = hazard.x + math.cos(turn) * out + push.x * STREAK_SPEED * travelled
        y = hazard.y + math.sin(turn) * out + push.y * STREAK_SPEED * travelled
        z = hazard.z + 0.3 + _scatter(number, index + 19) * min(hazard.height, 3.0)
        z += push.z * STREAK_SPEED * travelled
        screen_x, screen_y = project(x, y, z)
        size = number % len(art.STREAK_LENGTHS)
        image_half = art.STREAK_LENGTHS[size] + 1.5
        sprites.append(
            HazardSprite(
                ("hazard-streak", direction, size),
                partial(art.build_streak, direction, size),
                screen_x,
                screen_y - image_half,
            )
        )
    return sprites


def hazard_sprites(stage: Stage, frame: int, calm: bool = False) -> list[HazardSprite]:
    """Return everything a stage's hazards draw over the world on a frame: a geyser's jet,
    a lightning bolt, a wind's streaks (a few while it warns, many while it blows)."""
    sprites: list[HazardSprite] = []
    for index, hazard in enumerate(stage.hazards):
        phase, into, _ = hazard.moment(frame)
        if phase == "rest":
            continue
        foot_x, foot_y = project(hazard.x, hazard.y, hazard.z)
        if hazard.kind == "wind":
            count = STREAKS_ACTIVE if phase == "active" else STREAKS_WARN
            sprites += _streaks(index, hazard, frame, count)
        elif phase != "active":
            continue
        elif hazard.kind == "geyser":
            left = hazard.active - into
            grown = min(into + 1, left, JET_GROW_TICKS) / JET_GROW_TICKS
            step = 0 if calm else (frame // JET_FRAME_TICKS) % art.JET_FRAMES
            shown = round(grown * JET_GROW_TICKS)
            key = ("hazard-jet", hazard.radius, hazard.height, step, shown)
            sprites.append(
                HazardSprite(
                    key,
                    partial(art.build_jet, hazard.radius, hazard.height, step, grown),
                    foot_x,
                    foot_y,
                )
            )
        else:
            step = 0 if calm else (frame // BOLT_FRAME_TICKS) % art.BOLT_FRAMES
            sprites.append(
                HazardSprite(
                    ("hazard-bolt", hazard.height, step),
                    partial(art.build_bolt, hazard.height, step),
                    foot_x,
                    foot_y,
                )
            )
    return sprites
