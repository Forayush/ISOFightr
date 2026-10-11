"""The ragged mass under an island, and what hangs from it (decision D-063).

Plan note "03 - Isometric World and Rendering" ("Underside"). A stage with an ``[underside]``
table gets, under every solid cell, one more block hanging below the island's flat bottom:
shallow at the island's rim and deeper toward its middle, so the island tapers like a floating
rock. The blocks are cell-shaped, so the depth sorter treats them like any other stage
geometry (D-019). Tileset props may hang from the rim cells (roots, icicles).

Everything here is a fixed function of the stage, so a stage looks the same every match.
Pure Python (no ``arcade``).
"""

from __future__ import annotations

from typing import Final

from isofightr.config import UNDERSIDE_MAX_DEPTH
from isofightr.data.tileset_art import variant_index
from isofightr.sim.stage import Stage

RIM_DEPTH: Final[float] = 0.5
"""How far the block under a rim cell hangs, in units, before its own unevenness."""
DEPTH_PER_CELL: Final[float] = 0.5
"""How much deeper the mass gets with every cell from the rim."""
DEPTH_STEP: Final[float] = 0.25
"""Depths are whole multiples of this (4 pixels), and so is a cell's unevenness."""
UNEVEN_STEPS: Final[int] = 3
HANG_ONE_IN: Final[int] = 3
"""About one rim cell in this many gets something hanging from it."""
_NEIGHBOURS: Final[tuple[tuple[int, int], ...]] = ((1, 0), (-1, 0), (0, 1), (0, -1))


def rim_distances(stage: Stage) -> dict[tuple[int, int], int]:
    """Return, for every solid cell, how many cells it is from the void (a rim cell is 1)."""
    distance: dict[tuple[int, int], int] = {}
    frontier = []
    for cy in range(stage.size_y):
        for cx in range(stage.size_x):
            if stage.cell(cx, cy) is None:
                continue
            if any(stage.cell(cx + dx, cy + dy) is None for dx, dy in _NEIGHBOURS):
                distance[(cx, cy)] = 1
                frontier.append((cx, cy))
    while frontier:
        following = []
        for cx, cy in frontier:
            for dx, dy in _NEIGHBOURS:
                near = (cx + dx, cy + dy)
                if near not in distance and stage.cell(*near) is not None:
                    distance[near] = distance[(cx, cy)] + 1
                    following.append(near)
        frontier = following
    return distance


def under_depths(stage: Stage) -> dict[tuple[int, int], float]:
    """Return how far the block under each solid cell hangs below the island's underside, in
    units (empty for a stage without an ``[underside]`` table)."""
    art = stage.underside_art
    if art is None:
        return {}
    limit = min(art.depth, UNDERSIDE_MAX_DEPTH)
    depths = {}
    for (cx, cy), distance in rim_distances(stage).items():
        uneven = variant_index(cx + 11, cy + 5, UNEVEN_STEPS) * DEPTH_STEP
        depth = RIM_DEPTH + (distance - 1) * DEPTH_PER_CELL + uneven
        depths[(cx, cy)] = max(DEPTH_STEP, min(depth, limit))
    return depths


def lowest_point(stage: Stage) -> float:
    """Return the height of the lowest thing the stage draws: its underside, or the deepest
    block hanging under it."""
    depths = under_depths(stage)
    return stage.underside - max(depths.values(), default=0.0)


def hanging(stage: Stage) -> list[tuple[str, int, int]]:
    """Return what the stage's underside hangs by itself, as ``(prop name, cx, cy)``: one of
    the ``hang`` props under about a third of the rim cells that face the camera."""
    art = stage.underside_art
    if art is None or not art.hang:
        return []
    hung = []
    for cy in range(stage.size_y):
        for cx in range(stage.size_x):
            if stage.cell(cx, cy) is None:
                continue
            faces_camera = stage.cell(cx + 1, cy) is None or stage.cell(cx, cy + 1) is None
            if faces_camera and variant_index(cx + 3, cy + 17, HANG_ONE_IN) == 0:
                name = art.hang[variant_index(cx + 29, cy + 7, len(art.hang))]
                hung.append((name, cx, cy))
    return hung
