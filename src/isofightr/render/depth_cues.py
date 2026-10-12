"""Where a fighter is, said so that the picture cannot lie about it (decision D-065).

Plan note "03 - Isometric World and Rendering" ("Shadows and readability"). The game's
projection cannot tell height from distance toward the camera: a point moved by
``(+h, +h, +h)`` lands on the same pixels (:func:`twin`). A fighter in the air *off* the
island, in front of it, is therefore drawn exactly where one standing on the ground is. What
tells them apart is the marker on the ground below and the line up to the feet, and this
module says, for a fighter at a position on a stage, what those are:

- over a surface (a cell's top or a platform's deck): the marker lies on that surface, as
  it always did;
- over the void: the marker lies on the stage's reference plane (``Stage.reference_z``) and
  is dashed, so it is seen to be outside the island's footprint;
- under the island (below the top of a solid cell): the marker lies on that cell's top, right
  above the fighter, and is dashed;
- and when the feet are :data:`LINE_MIN_HEIGHT` or more from the marker, a dotted line joins
  them.

Pure Python (no ``arcade``, no Pillow): the renderer draws what this says.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Final

from isofightr.sim.stage import Stage

LINE_MIN_HEIGHT: Final[float] = 1.0
"""A height line is drawn when the feet are this far above or below the marker (units)."""
TWIN_HEIGHTS: Final[tuple[float, ...]] = (3.0, 2.0)
"""How high the depth lab lifts an off-stage twin: within a jump, the taller first."""


class Place(Enum):
    """What is under a fighter."""

    SURFACE = "surface"
    """A cell's top or a platform's deck at or below the feet."""
    VOID = "void"
    """Nothing: the fighter is off the stage."""
    UNDER = "under"
    """The fighter is below the top of a solid cell: under the island (or inside it)."""


@dataclass(frozen=True, slots=True)
class Cue:
    """The marker and the line for a fighter at one position."""

    place: Place
    marker_z: float
    """Height of the plane the marker lies on."""
    height: float
    """How far the feet are above the marker (negative: below it)."""
    dashed: bool
    """Whether the marker is the dashed ring of a fighter with no ground below."""
    line: float
    """Length of the height line in units (0 = none)."""
    through_solid: bool = False
    """Whether the line passes through solid ground (a fighter under the island): it cannot
    then be sorted among the stage's blocks and is drawn over them instead."""

    @property
    def grounded(self) -> bool:
        """Whether the fighter stands on its marker."""
        return self.place is Place.SURFACE and self.line == 0.0 and self.height < LINE_MIN_HEIGHT


def cue(stage: Stage, x: float, y: float, z: float) -> Cue:
    """Return the marker and line for feet at ``(x, y, z)`` on a stage (pass the stage as it
    is on the current frame, so moving platforms are where they are)."""
    support = stage.support_below(x, y, z)
    if support is not None:
        height = z - support
        return Cue(Place.SURFACE, support, height, False, _line(height))
    roof = stage.surface_top(x, y)
    if roof is not None:
        height = z - roof
        return Cue(Place.UNDER, roof, height, True, _line(height), through_solid=True)
    height = z - stage.reference_z
    return Cue(Place.VOID, stage.reference_z, height, True, _line(height))


def _line(height: float) -> float:
    return abs(height) if abs(height) >= LINE_MIN_HEIGHT else 0.0


def twin(x: float, y: float, z: float, lift: float) -> tuple[float, float, float]:
    """Return the point ``lift`` units higher and ``lift`` nearer the camera on both axes:
    it projects to exactly the same pixels as ``(x, y, z)``."""
    return (x + lift, y + lift, z + lift)


@dataclass(frozen=True, slots=True)
class TwinPair:
    """A place to stand on a stage, and the place in the air off the stage that is drawn
    on the same pixels."""

    ground: tuple[float, float, float]
    air: tuple[float, float, float]


def off_stage_twins(stage: Stage, count: int = 4) -> list[TwinPair]:
    """Return up to ``count`` pairs for a stage: the middle of a ground cell, and its twin in
    the air over the void. Cells are tried along the island's near edges, and the pairs are
    spread out across the screen."""
    found: list[TwinPair] = []
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None:
                continue
            x, y, z = cx + 0.5, cy + 0.5, cell.top
            if stage.support_below(x, y, z + 0.5) != z:
                continue  # a platform's post or deck is in the way of a clear look
            for lift in TWIN_HEIGHTS:
                air = twin(x, y, z, lift)
                over_void = stage.surface_top(air[0], air[1]) is None
                if over_void and stage.support_below(*air) is None:
                    found.append(TwinPair((x, y, z), air))
                    break
    if len(found) <= count:
        return found
    # Spread across the screen: sort by screen x (x - y) and take evenly spaced ones.
    found.sort(key=lambda pair: (pair.ground[0] - pair.ground[1], pair.ground[0]))
    step = (len(found) - 1) / (count - 1) if count > 1 else 0.0
    return [found[math.floor(index * step + 0.5)] for index in range(count)]
