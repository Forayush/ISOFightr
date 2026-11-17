"""Where things are on the Isle, the island every menu is drawn on, and how its camera moves.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). The menus are a
place: one hub island drawn by the battle's renderer. This module is the pure half of it: the
named camera framings ("stations") a screen asks for, the glide between two of them as a
function of the tick, the four spots of the ring (character select, results) and the part of
the plaza the fighters stroll on. :mod:`isofightr.scenes.menu_world` holds the sprites.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.paths import ASSETS_DIR, STAGE_FILE_NAME
from isofightr.data.sprite_sheet import AnimInfo
from isofightr.data.stage_loader import load_stage_file
from isofightr.render.anim_select import AnimChoice
from isofightr.render.fighter_look import FighterLook
from isofightr.render.iso import project
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.stage import Stage
from isofightr.ui.anim import ease_in_out, lerp

ISLE_DIR: Final[Path] = ASSETS_DIR / "ui" / "isle"
"""The Isle's stage file and backdrop pictures. Not under ``assets/stages``: it is never
listed as a playable stage."""
GLIDE_TICKS: Final[int] = 24
"""How long the camera takes from one station to another."""
REST_ZOOMS: Final[tuple[int, ...]] = (1, 2)
"""The zooms a station may have: whole numbers, so the world's pixels stay square and whole
at rest (decision D-048). Only a glide passes through the fractions between them."""

RING_LINE: Final[float] = 14.0
"""``x + y`` of the ring: a line across the screen, so its fighters stand side by side."""
RING_STEP: Final[float] = 2.5
"""How far apart two neighbouring ring spots are along x (and, the other way, along y):
80 pixels on screen at 1x, 160 at the ring's 2x, a quarter of the screen each."""
RING_SPOTS: Final[tuple[tuple[float, float], ...]] = tuple(
    (
        (RING_LINE + (2 * index - 3) * RING_STEP) / 2,
        (RING_LINE - (2 * index - 3) * RING_STEP) / 2,
    )
    for index in range(4)
)
"""Where the four players' fighters stand at the ring, left to right on screen (world x, y)."""
WORKSHOP_SPOT: Final[tuple[float, float]] = (4.75, 4.75)
"""Where the options show a setting on the world: in front of the arch in the back corner."""
RING_PAD_BASE: Final[int] = 1 << 17
"""Ground item ids of the markers under the ring's spots (between the battle effects' ids
and the hazard marks': see ``render/ground_items.py``)."""
NUDGE_EASE: Final[float] = 0.18
"""The share of the way to its goal the camera's lean covers each tick."""


@dataclass(frozen=True, slots=True)
class Bounds:
    """A rectangle on the screen's own axes: ``x + y`` (depth) and ``x - y`` (across)."""

    depth_min: float
    depth_max: float
    across_min: float
    across_max: float

    def holds(self, x: float, y: float) -> bool:
        """Whether a ground position is inside."""
        return (
            self.depth_min <= x + y <= self.depth_max
            and self.across_min <= x - y <= self.across_max
        )

    def point(self, depth: float, across: float) -> tuple[float, float]:
        """Return the ground position at shares (0 to 1) of the way back to front and left
        to right."""
        total = lerp(self.depth_min, self.depth_max, depth)
        difference = lerp(self.across_min, self.across_max, across)
        return ((total + difference) / 2, (total - difference) / 2)


STROLL_BOUNDS: Final[Bounds] = Bounds(17.0, 20.5, -6.0, 6.0)
"""The plaza: the open marble in front of the ring, where the fighters stroll."""


@dataclass(frozen=True, slots=True)
class Station:
    """One framing of the Isle: a world point, and where on the screen it is drawn."""

    name: str
    look_at: tuple[float, float, float]
    """The world point (x, y, z) the framing is about."""
    zoom: int
    anchor: tuple[int, int]
    """The native screen pixel (y up) ``look_at`` is drawn at."""
    strollers: bool = True
    """Whether the strolling fighters are shown here (the ring has its own fighters)."""


ISLE_CENTRE: Final[tuple[float, float, float]] = (7.0, 7.0, 0.0)
STATIONS: Final[dict[str, Station]] = {
    station.name: station
    for station in (
        # The whole island, low on the screen: the sky above it is the logo's.
        Station("gate", ISLE_CENTRE, 1, (320, 140)),
        # The island on the right; the main menu's buttons stand on the left.
        Station("plaza", ISLE_CENTRE, 1, (428, 164)),
        # The ring, close: four fighters across the screen at twice their size, standing
        # low enough to clear the roster above them, with their plates below.
        Station("ring", ISLE_CENTRE, 2, (320, 106), strollers=False),
        # The ring framed higher: the results' plates go under the fighters.
        Station("podium", ISLE_CENTRE, 2, (320, 150), strollers=False),
        # The back corner, close, on the right: the options are on the left.
        Station("workshop", (*WORKSHOP_SPOT, 0.0), 2, (470, 140)),
    )
}
"""Every station, by name."""


@dataclass(frozen=True, slots=True)
class Pose:
    """Where the camera is: its centre in world pixels (y up) and its zoom."""

    x: float
    y: float
    zoom: float

    @property
    def centre(self) -> tuple[int, int]:
        """The centre on whole world pixels, as the renderer takes it."""
        return (round(self.x), round(self.y))

    @property
    def resting(self) -> bool:
        """Whether this is a pose the camera may stay in: whole pixels, a whole zoom."""
        return self.x == round(self.x) and self.y == round(self.y) and self.zoom in REST_ZOOMS


def rest_pose(station: Station) -> Pose:
    """Return the camera pose that draws a station's ``look_at`` at its ``anchor``.

    A world pixel ``w`` is drawn at ``(w - centre) * zoom + screen middle``, so the centre is
    ``w - (anchor - middle) / zoom``; it is rounded to a whole world pixel.
    """
    world_x, world_y = project(*station.look_at)
    return Pose(
        float(round(world_x - (station.anchor[0] - NATIVE_W / 2) / station.zoom)),
        float(round(world_y - (station.anchor[1] - NATIVE_H / 2) / station.zoom)),
        float(station.zoom),
    )


def camera_at(elapsed: int, start: Pose, goal: Pose, duration: int = GLIDE_TICKS) -> Pose:
    """Return the camera ``elapsed`` ticks into a glide from ``start`` to ``goal``: eased in
    and out, never past the goal, and exactly the goal once the glide is over."""
    if elapsed >= duration or duration <= 0 or start == goal:
        return goal
    amount = ease_in_out(max(elapsed, 0) / duration)
    return Pose(
        lerp(start.x, goal.x, amount),
        lerp(start.y, goal.y, amount),
        lerp(start.zoom, goal.zoom, amount),
    )


def screen_point(pose: Pose, x: float, y: float, z: float = 0.0) -> tuple[int, int]:
    """Return the native screen pixel (y up) a world point is drawn at by a camera pose."""
    world_x, world_y = project(x, y, z)
    centre_x, centre_y = pose.centre
    return (
        round((world_x - centre_x) * pose.zoom + NATIVE_W / 2),
        round((world_y - centre_y) * pose.zoom + NATIVE_H / 2),
    )


def load_isle() -> Stage:
    """Load the Isle's stage."""
    return load_stage_file(ISLE_DIR / STAGE_FILE_NAME)


# --- the ring's fighters -----------------------------------------------------------------------
#
# At the ring a player's fighter is shown by a stand-in: something the world renderer can
# draw (a place, a facing, a look) that is not a sim fighter. Character select changes it
# whenever a slot changes; the results put the winners in their victory animation.

RING_ENTITY_BASE: Final[int] = 100
"""Entity ids of stand-ins start here, clear of the strolling fighters' (0 to 3)."""
RING_FACING: Final[Dir8] = Dir8.S
"""Stand-ins face out of the screen."""
DROP_HEIGHT: Final[float] = 5.5
"""How high above its spot a fighter appears when its player joins (tiles)."""
DROP_TICKS: Final[int] = 14
LAND_TICKS: Final[int] = 10
"""Ticks of the landing animation after the drop."""
READY_TICKS: Final[int] = 64
"""Ticks the ready pose (the taunt) plays before the fighter stands easy again."""
IDLE_ANIM: Final[str] = "idle"


class Mood(Enum):
    """What a stand-in is doing."""

    IDLE = "idle"
    DROP_IN = "drop_in"
    """Falling onto its spot, then landing: a player joined, or picked another fighter."""
    READY = "ready"
    WIN = "win"
    LOST = "lost"


@dataclass(frozen=True, slots=True)
class RingPose:
    """How a stand-in is shown on a tick of its mood."""

    lift: float
    """Tiles above its spot."""
    anim: str
    frame: int
    """1-indexed frame of the animation."""
    dim: bool = False


def ring_pose(mood: Mood, ticks: int) -> RingPose:
    """Return what a stand-in shows ``ticks`` after its mood began."""
    ticks = max(ticks, 0)
    if mood is Mood.DROP_IN:
        if ticks < DROP_TICKS:
            fallen = (ticks / DROP_TICKS) ** 2  # it speeds up as it falls
            return RingPose(DROP_HEIGHT * (1.0 - fallen), "fall", ticks + 1)
        if ticks < DROP_TICKS + LAND_TICKS:
            return RingPose(0.0, "land", ticks - DROP_TICKS + 1)
        return RingPose(0.0, IDLE_ANIM, ticks - DROP_TICKS - LAND_TICKS + 1)
    if mood is Mood.READY:
        if ticks < READY_TICKS:
            return RingPose(0.0, "taunt", ticks + 1)
        return RingPose(0.0, IDLE_ANIM, ticks - READY_TICKS + 1)
    if mood is Mood.WIN:
        return RingPose(0.0, "victory", ticks + 1)
    if mood is Mood.LOST:
        return RingPose(0.0, IDLE_ANIM, ticks + 1, dim=True)
    return RingPose(0.0, IDLE_ANIM, ticks + 1)


def ring_look(
    character: str, anims: Mapping[str, AnimInfo], pose: RingPose, costume: int
) -> FighterLook:
    """Return the look of a stand-in: the pose's animation from the character's sheets (its
    ``idle`` if the animation is missing; the placeholder capsule if it has no sheets)."""
    name = pose.anim if pose.anim in anims else IDLE_ANIM
    if name not in anims:
        return FighterLook(dim=pose.dim)
    choice = AnimChoice(name, anims[name].pose_at(pose.frame), exact=name == pose.anim)
    return FighterLook(sprite=choice, costume=costume, character=character, dim=pose.dim)


@dataclass(slots=True)
class StandIn:
    """One fighter standing at the ring. It has what the world renderer asks of an entity
    (``WorldEntity``) and nothing of the sim."""

    index: int
    """Which of the four spots it stands on."""
    character: str
    costume: int = 0
    color_index: int = 0
    """The player colour its ground marker is drawn in."""
    mood: Mood = Mood.IDLE
    since: int = 0
    """The world tick its mood began on."""
    invincible: bool = False
    on_revival_platform: bool = False
    pos: Vec3 = ZERO3
    """Where it is on the tick being drawn (the world sets it before each draw)."""

    @property
    def entity_id(self) -> int:
        """Its id among the world's entities."""
        return RING_ENTITY_BASE + self.index

    @property
    def player_index(self) -> int:
        """The slot it stands for."""
        return self.index

    @property
    def facing(self) -> Dir8:
        """The way it faces."""
        return RING_FACING

    def pose(self, tick: int) -> RingPose:
        """Return how it is shown on a world tick."""
        return ring_pose(self.mood, tick - self.since)

    def pos_at(self, tick: int) -> Vec3:
        """Return where it is on a world tick: over its spot, as high as its pose says."""
        x, y = RING_SPOTS[self.index]
        return Vec3(x, y, self.pose(tick).lift)
