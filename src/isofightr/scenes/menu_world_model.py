"""Where things are on the Isle, the island every menu is drawn on, and how its camera moves.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). The menus are a
place: one hub island drawn by the battle's renderer. This module is the pure half of it: the
named camera framings ("stations") a screen asks for, the glide between two of them as a
function of the tick, the four spots of the ring (character select, results) and the part of
the plaza the fighters stroll on. :mod:`isofightr.scenes.menu_world` holds the sprites.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.paths import ASSETS_DIR, STAGE_FILE_NAME
from isofightr.data.stage_loader import load_stage_file
from isofightr.render.iso import project
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
        # The ring, close: four fighters across the screen, plates under them.
        Station("ring", ISLE_CENTRE, 2, (320, 136), strollers=False),
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
