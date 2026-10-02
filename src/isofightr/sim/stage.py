"""Stage geometry: heightmap grid, soft platforms, ledge lines and blast zones.

Plan note "11 - Stages" (file format and what the stage builder produces), with the collision
model from "04 - Movement and Physics" and ledge geometry from "06 - Shield Dodge Grab and
Ledge". The grid is top-down in world space: row index = world ``y``, column index = world
``x``; the cell ``(cx, cy)`` covers ``[cx, cx + 1) x [cy, cy + 1)``.

TOML reading and key validation live in :mod:`isofightr.data.stage_loader`; this module only
turns already-parsed values into an immutable :class:`Stage`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from isofightr.config import (
    LEDGE_MIN_DROP,
    MIN_PLATFORM_CLEARANCE,
    PLAYER_SPAWN_COUNT,
    SURFACE_EPSILON,
)
from isofightr.sim.math3d import Box3, Vec2, Vec3

VOID_SYMBOL: Final[str] = "."
DEFAULT_TILE: Final[str] = "default"

# Outward normals in a fixed order, so ledge generation is deterministic.
_SIDE_NORMALS: Final[tuple[Vec2, ...]] = (
    Vec2(1.0, 0.0),
    Vec2(-1.0, 0.0),
    Vec2(0.0, 1.0),
    Vec2(0.0, -1.0),
)


class StageError(ValueError):
    """A stage definition breaks a structural rule (bad grid, spawn in the void...)."""


@dataclass(frozen=True, slots=True)
class Cell:
    """One solid grid cell."""

    top: float
    """Height of the walkable top surface, in units (0 = main floor level)."""
    tile: str = DEFAULT_TILE
    """Tile name the renderer uses to pick art."""
    ledge: bool = True
    """Whether this cell's exposed sides can be grabbed as ledges."""


@dataclass(frozen=True, slots=True)
class SoftPlatform:
    """A thin deck you can land on from above and pass through from below."""

    x0: int
    y0: int
    x1: int
    y1: int
    z: float

    def contains(self, x: float, y: float) -> bool:
        """Return whether a ground position is over the deck (far edges exclusive, like cells)."""
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1


@dataclass(frozen=True, slots=True)
class LedgeLine:
    """A grabbable edge: a straight run of exposed cell sides at one height."""

    start: Vec2
    end: Vec2
    z: float
    """Top height of the cells the ledge belongs to."""
    normal: Vec2
    """Outward unit normal: ``(+-1, 0)`` or ``(0, +-1)`` in world space (a screen diagonal)."""

    @property
    def length(self) -> float:
        """Length of the ledge line in units."""
        return (self.end - self.start).length()


@dataclass(frozen=True, slots=True)
class BackgroundLayer:
    """One parallax background image."""

    image: str
    parallax: float


@dataclass(frozen=True, slots=True)
class Stage:
    """An immutable, fully validated stage."""

    id: str
    display_name: str
    tileset: str
    music: str | None
    cells: tuple[tuple[Cell | None, ...], ...]
    """``cells[cy][cx]``: the solid cell or ``None`` for void."""
    soft_platforms: tuple[SoftPlatform, ...]
    ledges: tuple[LedgeLine, ...]
    spawns: tuple[Vec2, ...]
    """Ground positions for players 1 to 4, in order."""
    respawn: Vec2
    bounds: Box3
    """Bounding box of the solid cells (z spans the lowest to the highest cell top)."""
    blast_zone: Box3
    camera_bounds: Box3
    backgrounds: tuple[BackgroundLayer, ...]

    @property
    def size_x(self) -> int:
        """Number of grid columns (extent along world x)."""
        return len(self.cells[0])

    @property
    def size_y(self) -> int:
        """Number of grid rows (extent along world y)."""
        return len(self.cells)

    def cell(self, cx: int, cy: int) -> Cell | None:
        """Return the solid cell at grid coordinates, or ``None`` for void or out of range."""
        if 0 <= cy < len(self.cells) and 0 <= cx < len(self.cells[0]):
            return self.cells[cy][cx]
        return None

    def cell_at(self, x: float, y: float) -> Cell | None:
        """Return the solid cell under a ground position (floor of the coordinates)."""
        return self.cell(math.floor(x), math.floor(y))

    def surface_top(self, x: float, y: float) -> float | None:
        """Return the top height of the solid cell under a ground position, or ``None``."""
        cell = self.cell_at(x, y)
        return None if cell is None else cell.top

    def support_below(self, x: float, y: float, z: float) -> float | None:
        """Return the highest surface at or below height ``z`` under a ground position.

        Surfaces are solid cell tops and soft platform decks. ``None`` means nothing is below
        (over the void, or under the surface of a solid cell).
        """
        limit = z + SURFACE_EPSILON
        best: float | None = None
        cell_top = self.surface_top(x, y)
        if cell_top is not None and cell_top <= limit:
            best = cell_top
        for platform in self.soft_platforms:
            if (
                platform.z <= limit
                and platform.contains(x, y)
                and (best is None or platform.z > best)
            ):
                best = platform.z
        return best

    def spawn_point(self, player_index: int) -> Vec3:
        """Return the world spawn position of a player (0-based), standing on the surface."""
        return self._on_surface(self.spawns[player_index])

    def respawn_point(self) -> Vec3:
        """Return the respawn position on the surface (the revival platform hovers above it)."""
        return self._on_surface(self.respawn)

    def _on_surface(self, ground: Vec2) -> Vec3:
        top = self.surface_top(ground.x, ground.y)
        assert top is not None, "spawns are validated to be on solid ground"
        return ground.with_z(top)


def build_stage(
    *,
    id: str,
    display_name: str,
    tileset: str,
    grid_rows: Sequence[str],
    legend: Mapping[str, Cell],
    soft_platforms: Sequence[SoftPlatform],
    spawns: Sequence[Vec2],
    respawn: Vec2,
    blast_side: float,
    blast_top: float,
    blast_bottom: float,
    camera_margin: float,
    music: str | None = None,
    backgrounds: Sequence[BackgroundLayer] = (),
) -> Stage:
    """Validate parsed stage values and derive ledges, bounds, blast zone and camera bounds.

    Raises:
        StageError: if the grid is not rectangular, uses an unknown symbol, has no solid cell,
            or a platform or spawn breaks a structural rule.
    """
    cells = _parse_grid(grid_rows, legend)
    bounds = _solid_bounds(cells)
    stage = Stage(
        id=id,
        display_name=display_name,
        tileset=tileset,
        music=music,
        cells=cells,
        soft_platforms=tuple(soft_platforms),
        ledges=generate_ledges(cells),
        spawns=tuple(spawns),
        respawn=respawn,
        bounds=bounds,
        blast_zone=Box3(
            bounds.x_min - blast_side,
            bounds.x_max + blast_side,
            bounds.y_min - blast_side,
            bounds.y_max + blast_side,
            blast_bottom,
            blast_top,
        ),
        camera_bounds=_camera_bounds(bounds, soft_platforms, camera_margin),
        backgrounds=tuple(backgrounds),
    )
    _validate_platforms(stage)
    _validate_spawns(stage)
    if not blast_bottom < bounds.z_min or not blast_top > bounds.z_max:
        raise StageError("blast zone top and bottom must enclose every cell top")
    return stage


def generate_ledges(cells: Sequence[Sequence[Cell | None]]) -> tuple[LedgeLine, ...]:
    """Return the ledge lines of a grid: exposed sides of ledge-enabled cells, merged.

    A side is exposed when the neighbour is void, or solid but lower by more than
    ``LEDGE_MIN_DROP``. Collinear, touching segments with the same normal and height merge
    into one line. The result is sorted, so it never depends on iteration order.
    """
    # (normal, fixed coordinate, height) -> start positions of unit segments along the line.
    runs: dict[tuple[Vec2, int, float], list[int]] = {}
    for cy, row in enumerate(cells):
        for cx, cell in enumerate(row):
            if cell is None or not cell.ledge:
                continue
            for normal in _SIDE_NORMALS:
                neighbour = _cell_or_none(cells, cx + int(normal.x), cy + int(normal.y))
                if neighbour is not None and cell.top - neighbour.top <= LEDGE_MIN_DROP:
                    continue
                if normal.x != 0.0:
                    fixed = cx + 1 if normal.x > 0 else cx
                    along = cy
                else:
                    fixed = cy + 1 if normal.y > 0 else cy
                    along = cx
                runs.setdefault((normal, fixed, cell.top), []).append(along)

    ledges: list[LedgeLine] = []
    for normal in _SIDE_NORMALS:
        keys = sorted((key for key in runs if key[0] == normal), key=lambda key: (key[1], key[2]))
        for key in keys:
            _, fixed, top = key
            for first, last in _merge_unit_runs(runs[key]):
                line, low, high = float(fixed), float(first), float(last + 1)
                if normal.x != 0.0:
                    start, end = Vec2(line, low), Vec2(line, high)
                else:
                    start, end = Vec2(low, line), Vec2(high, line)
                ledges.append(LedgeLine(start=start, end=end, z=top, normal=normal))
    return tuple(ledges)


def _merge_unit_runs(starts: Sequence[int]) -> list[tuple[int, int]]:
    """Merge unit segment start positions into ``(first, last)`` runs of consecutive integers."""
    merged: list[tuple[int, int]] = []
    for position in sorted(starts):
        if merged and merged[-1][1] + 1 == position:
            merged[-1] = (merged[-1][0], position)
        else:
            merged.append((position, position))
    return merged


def _cell_or_none(cells: Sequence[Sequence[Cell | None]], cx: int, cy: int) -> Cell | None:
    if 0 <= cy < len(cells) and 0 <= cx < len(cells[0]):
        return cells[cy][cx]
    return None


def _parse_grid(
    grid_rows: Sequence[str], legend: Mapping[str, Cell]
) -> tuple[tuple[Cell | None, ...], ...]:
    if not grid_rows:
        raise StageError("grid is empty")
    width = len(grid_rows[0])
    rows: list[tuple[Cell | None, ...]] = []
    for cy, text in enumerate(grid_rows):
        if len(text) != width:
            raise StageError(f"grid row {cy} has {len(text)} cells, expected {width}")
        rows.append(tuple(_parse_symbol(symbol, cy, cx, legend) for cx, symbol in enumerate(text)))
    if width == 0 or all(cell is None for row in rows for cell in row):
        raise StageError("grid has no solid cells")
    return tuple(rows)


def _parse_symbol(symbol: str, cy: int, cx: int, legend: Mapping[str, Cell]) -> Cell | None:
    if symbol == VOID_SYMBOL:
        return None
    if symbol in legend:
        return legend[symbol]
    if symbol.isascii() and symbol.isdigit():
        return Cell(top=float(symbol))
    raise StageError(f"grid row {cy}, column {cx}: unknown symbol {symbol!r} (add it to [legend])")


def _solid_bounds(cells: Sequence[Sequence[Cell | None]]) -> Box3:
    solid = [(cx, cy, cell) for cy, row in enumerate(cells) for cx, cell in enumerate(row) if cell]
    return Box3(
        x_min=float(min(cx for cx, _, _ in solid)),
        x_max=float(max(cx for cx, _, _ in solid) + 1),
        y_min=float(min(cy for _, cy, _ in solid)),
        y_max=float(max(cy for _, cy, _ in solid) + 1),
        z_min=min(cell.top for _, _, cell in solid),
        z_max=max(cell.top for _, _, cell in solid),
    )


def _camera_bounds(bounds: Box3, platforms: Sequence[SoftPlatform], margin: float) -> Box3:
    highest = max([bounds.z_max, *(platform.z for platform in platforms)])
    return Box3(
        bounds.x_min - margin,
        bounds.x_max + margin,
        bounds.y_min - margin,
        bounds.y_max + margin,
        bounds.z_min - margin,
        highest + margin,
    )


def _validate_platforms(stage: Stage) -> None:
    for index, platform in enumerate(stage.soft_platforms):
        where = f"soft platform {index}"
        if platform.x0 >= platform.x1 or platform.y0 >= platform.y1:
            raise StageError(f"{where}: rect must have x0 < x1 and y0 < y1")
        if (
            platform.x0 < 0
            or platform.y0 < 0
            or platform.x1 > stage.size_x
            or platform.y1 > stage.size_y
        ):
            raise StageError(f"{where}: rect lies outside the grid")
        for cy in range(platform.y0, platform.y1):
            for cx in range(platform.x0, platform.x1):
                cell = stage.cell(cx, cy)
                if cell is not None and platform.z < cell.top + MIN_PLATFORM_CLEARANCE:
                    raise StageError(
                        f"{where}: z {platform.z} is less than {MIN_PLATFORM_CLEARANCE} above "
                        f"the cell at ({cx}, {cy}) with top {cell.top}"
                    )


def _validate_spawns(stage: Stage) -> None:
    if len(stage.spawns) != PLAYER_SPAWN_COUNT:
        raise StageError(f"expected {PLAYER_SPAWN_COUNT} spawns, got {len(stage.spawns)}")
    named = [(f"p{index + 1}", spawn) for index, spawn in enumerate(stage.spawns)]
    for name, spawn in [*named, ("respawn", stage.respawn)]:
        if stage.surface_top(spawn.x, spawn.y) is None:
            raise StageError(f"spawn {name} at ({spawn.x}, {spawn.y}) is not on solid ground")
