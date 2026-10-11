"""Where a stage's props stand or hang, and how the depth sorter sees them (decision D-063).

Plan note "03 - Isometric World and Rendering" ("Props"). A prop is a decoration from the
stage's tileset: it never collides and the sim does not know it. A **world** prop stands on
the ground at its position; a **below** prop hangs from the bottom of the island there. Each
is one :class:`~isofightr.render.depth.DynamicItem` with the exact rectangle of its frames, so
fighters pass in front of and behind it correctly (D-019).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from isofightr.config import PROP_DEFAULT_PERIOD, Z_PX
from isofightr.data.tileset_art import PropArt, TilesetArt
from isofightr.render.camera import snap
from isofightr.render.depth import DynamicItem, ScreenRect
from isofightr.render.iso import project
from isofightr.render.underside import hanging, under_depths
from isofightr.sim.stage import Stage

PROP_ITEM_BASE: Final[int] = 1 << 21
"""Depth sorter ids of props start here, above every fighter part and ground item."""
PROP_RANK: Final[int] = 1
BELOW_LAYER: Final[str] = "below"
CELL_MIDDLE: Final[float] = 0.5


@dataclass(frozen=True, slots=True)
class PlacedProp:
    """One prop of a stage, ready to draw."""

    index: int
    art: PropArt
    x: float
    y: float
    z: float
    """Height of the point it stands on or hangs from."""
    below: bool
    period: int
    phase: int

    def frame(self, tick: int) -> int:
        """Return which of the prop's frames shows on a tick."""
        if self.art.frames <= 1:
            return 0
        return ((tick + self.phase) // self.period) % self.art.frames

    @property
    def rect(self) -> ScreenRect:
        """The world pixels its frames cover."""
        sx, sy = (snap(value) for value in project(self.x, self.y, self.z))
        left, top = sx - self.art.pivot_x, sy + self.art.pivot_y
        return ScreenRect(left, top - self.art.height, left + self.art.width, top)

    @property
    def item(self) -> DynamicItem:
        """What the depth sorter needs to know: a standing prop rises from its position, a
        hanging one reaches down from it."""
        above = self.art.pivot_y / Z_PX
        drop = (self.art.height - self.art.pivot_y) / Z_PX
        return DynamicItem(
            item_id=PROP_ITEM_BASE + self.index,
            rank=PROP_RANK,
            x=self.x,
            y=self.y,
            z=self.z - drop if self.below else self.z,
            height=drop if self.below else above,
            rect=self.rect,
            fixed=True,
        )


def placed_props(stage: Stage, tileset: TilesetArt | None) -> list[PlacedProp]:
    """Return the stage's props (those it lists, then what its underside hangs by itself),
    leaving out any the tileset does not have."""
    if tileset is None:
        return []
    depths = under_depths(stage)
    wanted: list[tuple[str, float, float, bool, int, int]] = [
        (prop.sprite, prop.x, prop.y, prop.layer == BELOW_LAYER, prop.period, prop.phase)
        for prop in stage.props
    ]
    for count, (name, cx, cy) in enumerate(hanging(stage)):
        # Neighbours start their sway a few ticks apart, so the rim does not move as one.
        phase = count * 5
        wanted.append((name, cx + CELL_MIDDLE, cy + CELL_MIDDLE, True, 0, phase))

    placed = []
    for name, x, y, below, period, phase in wanted:
        art = tileset.prop(name)
        cell = stage.cell_at(x, y)
        if art is None or cell is None:
            continue
        z = stage.underside - depths.get((int(x), int(y)), 0.0) if below else cell.top
        placed.append(
            PlacedProp(len(placed), art, x, y, z, below, period or PROP_DEFAULT_PERIOD, phase)
        )
    return placed
