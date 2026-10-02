"""F3 debug overlay: iso grid with coordinates, ledge lines, platforms and the blast zone.

Plan notes "13 - Game Modes UI and Flow" (training mode keys: F3 shows the iso grid plus
coordinates, ledge lines and the blast-zone box) and "03 - Isometric World and Rendering"
(debug overlays draw at native resolution in their own layer).

Everything is precomputed once per stage; drawing is a handful of batched line calls.
"""

import arcade

from isofightr.render.camera import snap
from isofightr.render.iso import project
from isofightr.sim.math3d import Box3, Vec3
from isofightr.sim.stage import Stage
from isofightr.ui.pixel_font import GLYPH_HEIGHT, text_width
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

type Point = tuple[float, float]

GRID_COLOR = (255, 255, 255, 80)
PLATFORM_COLOR = (120, 255, 170, 200)
LEDGE_COLOR = (255, 224, 64, 255)
BLAST_COLOR = (255, 72, 72, 255)
X_LABEL_COLOR = (255, 170, 150, 255)
Y_LABEL_COLOR = (150, 200, 255, 255)
LINE_WIDTH = 1
LEDGE_TICK_LENGTH = 0.35
"""Length of the outward-normal tick drawn at each ledge's midpoint, in units."""
LABEL_OFFSET = 0.75
"""How far outside the grid the coordinate labels sit, in units."""
PIXEL_CENTRE = 0.5
"""Lines are drawn through pixel centres so 1 px lines stay crisp."""


def _point(position: Vec3) -> Point:
    sx, sy = project(position.x, position.y, position.z)
    return (snap(sx) + PIXEL_CENTRE, snap(sy) + PIXEL_CENTRE)


def _segment(start: Vec3, end: Vec3) -> list[Point]:
    return [_point(start), _point(end)]


def box_edges(box: Box3) -> list[tuple[Vec3, Vec3]]:
    """Return the twelve edges of a world-space box as pairs of corners."""
    corners = box.corners()
    return [
        (first, second)
        for index, first in enumerate(corners)
        for second in corners[index + 1 :]
        if sum(a != b for a, b in zip(_as_tuple(first), _as_tuple(second), strict=True)) == 1
    ]


def _as_tuple(vector: Vec3) -> tuple[float, float, float]:
    return (vector.x, vector.y, vector.z)


class StageOverlay:
    """Precomputed debug geometry for one stage, drawn in world pixel space."""

    def __init__(self, stage: Stage, glyphs: GlyphAtlas) -> None:
        """Build the line lists and coordinate labels."""
        self._grid = self._grid_lines(stage)
        self._platforms = self._platform_lines(stage)
        self._ledges = self._ledge_lines(stage)
        self._blast = [
            point for start, end in box_edges(stage.blast_zone) for point in _segment(start, end)
        ]
        self._labels: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._add_labels(stage, glyphs)

    def draw(self) -> None:
        """Draw the overlay. Call with the world camera active."""
        arcade.draw_lines(self._grid, GRID_COLOR, LINE_WIDTH)
        if self._platforms:
            arcade.draw_lines(self._platforms, PLATFORM_COLOR, LINE_WIDTH)
        arcade.draw_lines(self._blast, BLAST_COLOR, LINE_WIDTH)
        arcade.draw_lines(self._ledges, LEDGE_COLOR, LINE_WIDTH)
        self._labels.draw(pixelated=True)

    @staticmethod
    def _grid_lines(stage: Stage) -> list[Point]:
        edges: set[tuple[Vec3, Vec3]] = set()
        for cy, row in enumerate(stage.cells):
            for cx, cell in enumerate(row):
                if cell is None:
                    continue
                corners = [
                    Vec3(cx, cy, cell.top),
                    Vec3(cx + 1, cy, cell.top),
                    Vec3(cx + 1, cy + 1, cell.top),
                    Vec3(cx, cy + 1, cell.top),
                ]
                for index, corner in enumerate(corners):
                    following = corners[(index + 1) % len(corners)]
                    first, second = sorted((corner, following), key=_as_tuple)
                    edges.add((first, second))
        ordered = sorted(edges, key=lambda edge: (_as_tuple(edge[0]), _as_tuple(edge[1])))
        return [point for start, end in ordered for point in _segment(start, end)]

    @staticmethod
    def _platform_lines(stage: Stage) -> list[Point]:
        points: list[Point] = []
        for platform in stage.soft_platforms:
            corners = [
                Vec3(platform.x0, platform.y0, platform.z),
                Vec3(platform.x1, platform.y0, platform.z),
                Vec3(platform.x1, platform.y1, platform.z),
                Vec3(platform.x0, platform.y1, platform.z),
            ]
            for index, corner in enumerate(corners):
                points.extend(_segment(corner, corners[(index + 1) % len(corners)]))
        return points

    @staticmethod
    def _ledge_lines(stage: Stage) -> list[Point]:
        points: list[Point] = []
        for ledge in stage.ledges:
            points.extend(_segment(ledge.start.with_z(ledge.z), ledge.end.with_z(ledge.z)))
            middle = (ledge.start + ledge.end) / 2
            tip = middle + ledge.normal * LEDGE_TICK_LENGTH
            points.extend(_segment(middle.with_z(ledge.z), tip.with_z(ledge.z)))
        return points

    def _add_labels(self, stage: Stage, glyphs: GlyphAtlas) -> None:
        floor = stage.bounds.z_min
        for cx in range(stage.size_x):
            self._add_label(glyphs, str(cx), Vec3(cx + 0.5, -LABEL_OFFSET, floor), X_LABEL_COLOR)
        for cy in range(stage.size_y):
            self._add_label(glyphs, str(cy), Vec3(-LABEL_OFFSET, cy + 0.5, floor), Y_LABEL_COLOR)

    def _add_label(
        self, glyphs: GlyphAtlas, text: str, position: Vec3, color: tuple[int, int, int, int]
    ) -> None:
        sx, sy = project(position.x, position.y, position.z)
        left = snap(sx - text_width(text) / 2)
        bottom = snap(sy - GLYPH_HEIGHT / 2)
        PixelLabel(glyphs, self._labels, left, bottom, len(text), color).text = text
