"""Draw order for the isometric world: which sprite is painted before which.

Implements "Depth sorting rules" and the sorted passes of "Render layers" in the plan note
"03 - Isometric World and Rendering", as one merged order (decision D-019) instead of separate
below-surface and above-surface passes.

The order is a topological sort. Two sprites are only constrained when they overlap on
screen, and then geometry decides which is in front:

- Along a view ray, ``x``, ``y`` and ``z`` all grow toward the camera at the same rate. So
  anything that lies entirely above something else is in front of it wherever they overlap.
- Otherwise a cell-shaped block (a column of solid ground, a platform deck cell) is in front
  of a point that is behind it on *both* ground axes. A point in front of the block on either
  axis can never be hidden by it.
- Two upright sprites (fighters) that share a height range sort by the depth key of their
  feet, ``x + y``, then height, then id (plan note 03).

**Static items** (stage geometry) get their mutual constraints once, at load. **Dynamic
items** (fighters, their ground shadows, later projectiles) add theirs each frame, and the
order is only recomputed when those constraints change.

Assumption (stage design rule in the plan note "11 - Stages"): no overhangs or tunnels. A
fighter passing through a soft platform is drawn entirely on one side of the deck cell it is
inside, which is wrong by at most one cell for the few frames it takes.

Pure Python (no ``arcade``), so the ordering is unit tested without a window.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum

from isofightr.config import DECK_THICKNESS, SURFACE_EPSILON, TILE_H, Z_PX
from isofightr.render.iso import HALF_TILE_W, project
from isofightr.sim.stage import NO_PLATFORM, Stage


@dataclass(frozen=True, slots=True)
class ScreenRect:
    """An axis-aligned rectangle in world pixels (y up)."""

    left: float
    bottom: float
    right: float
    top: float

    def overlaps(self, other: ScreenRect) -> bool:
        """Return whether the rectangles share any area (touching edges do not count)."""
        return (
            self.left < other.right
            and other.left < self.right
            and self.bottom < other.top
            and other.bottom < self.top
        )


class StaticKind(IntEnum):
    """What a static item is. The value breaks ties between items on the same cell."""

    COLUMN = 0
    DECAL = 1
    DECK = 2


@dataclass(frozen=True, slots=True)
class StaticItem:
    """One piece of stage geometry: it occupies one grid cell between two heights."""

    kind: StaticKind
    cx: int
    cy: int
    bottom: float
    """Height of the item's underside, in units."""
    top: float
    """Height of the item's top surface, in units."""
    platform_index: int
    """Index into ``stage.soft_platforms`` for decks and decals, else ``NO_PLATFORM``."""
    rect: ScreenRect


@dataclass(frozen=True, slots=True)
class DynamicItem:
    """Something that moves: an upright sprite standing at a world position."""

    item_id: int
    """Unique and stable: the final tie-break, so the order never flickers."""
    rank: int
    """Tie-break among items at the same place: lower is drawn first (shadows before bodies)."""
    x: float
    y: float
    z: float
    """Height of the item's feet (for a shadow: the surface it lies on)."""
    height: float
    """How far the item extends above its feet, in units (0 for a flat shadow)."""
    rect: ScreenRect
    """Bounds of every pixel the sprite draws."""

    @property
    def key(self) -> float:
        """Depth key of the feet: larger is nearer the camera."""
        return self.x + self.y

    @property
    def back_to_front(self) -> tuple[float, float, int, int]:
        """Sort key among dynamic items: depth key, then height, then rank, then id."""
        return (self.key, self.z, self.rank, self.item_id)


@dataclass(frozen=True, slots=True)
class DrawEntry:
    """One step of the final draw order: a static item index or a dynamic item id."""

    is_static: bool
    index: int


def sprite_rect(
    x: float, y: float, z: float, half_width: float, below: float, above: float
) -> ScreenRect:
    """Return the screen rectangle of an upright sprite whose feet are at a world position.

    ``half_width``, ``below`` and ``above`` are pixel extents measured from the projected feet.
    """
    sx, sy = project(x, y, z)
    return ScreenRect(sx - half_width, sy - below, sx + half_width, sy + above)


def cell_block_rect(cx: int, cy: int, bottom: float, top: float) -> ScreenRect:
    """Return the screen rectangle of a cell-sized block between two heights."""
    centre_x, back_y = project(cx, cy, top)
    return ScreenRect(
        centre_x - HALF_TILE_W,
        back_y - TILE_H - (top - bottom) * Z_PX,
        centre_x + HALF_TILE_W,
        back_y,
    )


def static_goes_first(first: StaticItem, second: StaticItem) -> bool | None:
    """Return whether ``first`` must be drawn before ``second`` (``None``: no constraint).

    Only meaningful for items whose rectangles overlap.
    """
    if first.top <= second.bottom + SURFACE_EPSILON:
        return True
    if second.top <= first.bottom + SURFACE_EPSILON:
        return False
    if (first.cx, first.cy) == (second.cx, second.cy):
        return (first.top, first.kind) < (second.top, second.kind)
    if first.cx <= second.cx and first.cy <= second.cy:
        return True
    if second.cx <= first.cx and second.cy <= first.cy:
        return False
    return None  # side by side on a screen diagonal: neither can hide the other


def static_hides(static: StaticItem, item: DynamicItem) -> bool:
    """Return whether ``static`` is in front of ``item`` where their sprites overlap."""
    if static.top <= item.z + SURFACE_EPSILON:
        return False  # the item is entirely above it
    if static.bottom >= item.z + item.height - SURFACE_EPSILON:
        return True  # it is entirely above the item
    return item.x < static.cx + 1 and item.y < static.cy + 1


def dynamic_goes_first(first: DynamicItem, second: DynamicItem) -> bool:
    """Return whether ``first`` is drawn before ``second`` when their sprites overlap."""
    second_above = second.z >= first.z + first.height - SURFACE_EPSILON
    first_above = first.z >= second.z + second.height - SURFACE_EPSILON
    if second_above != first_above:
        # One is entirely above the other (a fighter standing on the plane a shadow lies on
        # counts), so it is in front wherever they overlap.
        return second_above
    return first.back_to_front < second.back_to_front


class DepthSorter:
    """Holds a stage's static draw constraints and merges dynamic items into the order."""

    def __init__(self, stage: Stage) -> None:
        self.stage = stage
        self.statics: tuple[StaticItem, ...] = _build_statics(stage)
        count = len(self.statics)

        # Statics grouped by screen diagonal (cx - cy): a sprite only ever overlaps the few
        # diagonals around its own, which keeps every overlap scan short.
        self._by_diagonal: dict[int, list[int]] = {}
        for index, item in enumerate(self.statics):
            self._by_diagonal.setdefault(item.cx - item.cy, []).append(index)

        self._successors: list[list[int]] = [[] for _ in range(count)]
        self._blockers: list[int] = [0] * count
        for index, item in enumerate(self.statics):
            for other in self._overlapping_statics(item.rect):
                if other <= index:
                    continue
                first = static_goes_first(item, self.statics[other])
                if first is None:
                    continue
                before, after = (index, other) if first else (other, index)
                self._successors[before].append(after)
                self._blockers[after] += 1

        self._cached_signature: object = None
        self._cached_order: list[DrawEntry] = []

    def draw_order(self, items: Sequence[DynamicItem]) -> list[DrawEntry]:
        """Return the full back-to-front draw order of statics and dynamic items."""
        ordered = sorted(items, key=lambda entry: entry.back_to_front)
        static_count = len(self.statics)
        # Constraint pairs (before, after) over node numbers: statics first, then dynamics
        # in back-to-front order, so the tie-break draws dynamics as late as allowed.
        edges: list[tuple[int, int]] = []
        for offset, item in enumerate(ordered):
            node = static_count + offset
            for index in self._overlapping_statics(item.rect):
                if static_hides(self.statics[index], item):
                    edges.append((node, index))
                else:
                    edges.append((index, node))
            for other_offset in range(offset):
                other = ordered[other_offset]
                if item.rect.overlaps(other.rect):
                    other_node = static_count + other_offset
                    if dynamic_goes_first(other, item):
                        edges.append((other_node, node))
                    else:
                        edges.append((node, other_node))

        signature = (tuple(item.item_id for item in ordered), tuple(edges))
        if signature != self._cached_signature:
            self._cached_signature = signature
            self._cached_order = self._sort(ordered, edges)
        return list(self._cached_order)

    def _sort(
        self, ordered: Sequence[DynamicItem], edges: Sequence[tuple[int, int]]
    ) -> list[DrawEntry]:
        """Topologically sort all nodes; lower node numbers go first whenever there is a choice."""
        static_count = len(self.statics)
        total = static_count + len(ordered)
        successors = [list(nodes) for nodes in self._successors] + [[] for _ in ordered]
        blockers = [*self._blockers, *([0] * len(ordered))]
        # Dynamic nodes also count how many *dynamic* nodes they still wait for.
        dynamic_blockers = [0] * total
        for before, after in edges:
            successors[before].append(after)
            blockers[after] += 1
            if before >= static_count and after >= static_count:
                dynamic_blockers[after] += 1

        ready = [node for node in range(total) if blockers[node] == 0]
        heapq.heapify(ready)
        done = [False] * total
        order: list[DrawEntry] = []
        while len(order) < total:
            node = heapq.heappop(ready) if ready else self._break_cycle(done, dynamic_blockers)
            if done[node]:
                continue
            done[node] = True
            if node < static_count:
                order.append(DrawEntry(True, node))
            else:
                order.append(DrawEntry(False, ordered[node - static_count].item_id))
            for following in successors[node]:
                blockers[following] -= 1
                if node >= static_count and following >= static_count:
                    dynamic_blockers[following] -= 1
                if blockers[following] == 0 and not done[following]:
                    heapq.heappush(ready, following)
        return order

    def _break_cycle(self, done: Sequence[bool], dynamic_blockers: Sequence[int]) -> int:
        """Pick the node to draw next when every remaining node waits on another.

        Cycles are rare: a sprite is one rectangle but may need to be both behind one static
        and on top of another that the first must precede (a shadow that pokes past the foot
        of a block, a fighter half-way through a deck). Being hidden by what is in front
        matters more than a few pixels of overhang, so the constraint to give up is "drawn
        after the ground it rests on": release the rear-most waiting dynamic item early.
        """
        static_count = len(self.statics)
        waiting = [node for node in range(static_count, len(done)) if not done[node]]
        for node in waiting:
            if dynamic_blockers[node] == 0:
                return node
        if waiting:
            return waiting[0]
        return next(node for node in range(static_count) if not done[node])

    def _overlapping_statics(self, rect: ScreenRect) -> list[int]:
        """Return the indices of statics whose rectangles overlap ``rect``, ascending."""
        # A static on diagonal d spans pixels ((d - 1) * 16, (d + 1) * 16).
        first_diagonal = math.floor(rect.left / HALF_TILE_W)
        last_diagonal = math.ceil(rect.right / HALF_TILE_W)
        found = [
            index
            for diagonal in range(first_diagonal, last_diagonal + 1)
            for index in self._by_diagonal.get(diagonal, ())
            if rect.overlaps(self.statics[index].rect)
        ]
        found.sort()
        return found


def _build_statics(stage: Stage) -> tuple[StaticItem, ...]:
    """Return the stage's static items, back to front by cell centre, lowest first."""
    island_bottom = stage.underside
    statics: list[StaticItem] = []
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None:
                continue
            rect = cell_block_rect(cx, cy, island_bottom, cell.top)
            statics.append(
                StaticItem(StaticKind.COLUMN, cx, cy, island_bottom, cell.top, NO_PLATFORM, rect)
            )

    shadowed: dict[tuple[int, int], int] = {}
    for index, platform in enumerate(stage.soft_platforms):
        deck_bottom = platform.z - DECK_THICKNESS
        for cy in range(platform.y0, platform.y1):
            for cx in range(platform.x0, platform.x1):
                rect = cell_block_rect(cx, cy, deck_bottom, platform.z)
                statics.append(
                    StaticItem(StaticKind.DECK, cx, cy, deck_bottom, platform.z, index, rect)
                )
                # With stacked platforms the lowest one casts the shadow onto the ground.
                current = shadowed.get((cx, cy))
                if current is None or platform.z < stage.soft_platforms[current].z:
                    shadowed[(cx, cy)] = index

    for (cx, cy), index in shadowed.items():
        cell = stage.cell(cx, cy)
        if cell is None:
            continue
        # The drop shadow is paint on the column's top, so it sorts like the column itself.
        rect = cell_block_rect(cx, cy, cell.top, cell.top)
        statics.append(StaticItem(StaticKind.DECAL, cx, cy, island_bottom, cell.top, index, rect))

    statics.sort(key=lambda item: (item.cx + item.cy, item.top, item.kind, item.cx))
    return tuple(statics)
