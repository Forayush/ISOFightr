"""Checks a stage against the design rules: the stage report.

Plan note "11 - Stages" ("Design rules") and decision D-063 (M14 group 0). Each rule gives a
:class:`Check` (passed or not, with the numbers), so ``tools/stage_report.py`` can print
them and a test can run them over every stage in ``assets/stages``:

- spawns at least 4 units apart, on solid ground;
- every island has a ledge to grab;
- every soft platform is reachable with one jump from a surface near it;
- the whole stage fits the play area (the screen between the HUD's bands) with a margin;
- the blast zones enclose the stage with room to be launched in;
- no notch in the ground narrower than 2 cells.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from isofightr.render.iso import project
from isofightr.render.underside import lowest_point
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.stage import Stage
from isofightr.ui.hud_layout import PLAY_AREA

MIN_SPAWN_GAP: Final[float] = 4.0
PLATFORM_REACH: Final[float] = 1.3
"""A platform may be this many full hops above the surface it is reached from (rule 3)."""
PLATFORM_NEAR: Final[float] = 3.0
"""How far to the side (in units) a surface may be and still be where one jumps from."""
FIT_MARGIN: Final[int] = 8
"""Pixels to keep free around the stage inside the play area."""
MIN_BLAST_SIDE: Final[float] = 5.0
MIN_BLAST_ABOVE: Final[float] = 6.0
"""The top blast zone must be this far above the highest surface."""
MIN_BLAST_BELOW: Final[float] = 3.0
"""The bottom blast zone must be this far under the island's underside."""
RULES: Final[tuple[str, ...]] = (
    "spawns",
    "ledges",
    "platforms_reachable",
    "fits_play_area",
    "blast_zones",
    "no_narrow_notch",
)
"""The name of every check, in the order they are reported."""


@dataclass(frozen=True, slots=True)
class Check:
    """One rule's verdict."""

    rule: str
    passed: bool
    detail: str


def hop_height(character: CharacterDef) -> float:
    """Return how high a character's full hop carries its feet: the rise summed frame by
    frame until gravity has used the jump's speed up."""
    movement = character.movement
    height, speed = 0.0, movement.full_hop_vz
    while speed > 0.0:
        height += speed
        speed -= movement.gravity
    return height


def islands(stage: Stage) -> list[set[tuple[int, int]]]:
    """Return the stage's separate pieces of solid ground, as sets of cells (cells touching
    side by side are one piece)."""
    seen: set[tuple[int, int]] = set()
    pieces: list[set[tuple[int, int]]] = []
    for cy in range(stage.size_y):
        for cx in range(stage.size_x):
            if stage.cell(cx, cy) is None or (cx, cy) in seen:
                continue
            piece = {(cx, cy)}
            todo = [(cx, cy)]
            while todo:
                x, y = todo.pop()
                for near in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if near not in piece and stage.cell(*near) is not None:
                        piece.add(near)
                        todo.append(near)
            seen |= piece
            pieces.append(piece)
    return pieces


def screen_extent(stage: Stage) -> tuple[float, float]:
    """Return the width and height in pixels of everything the stage draws: its ground down
    to the underside (or the mass hanging under it), and its platforms."""
    points = []
    bottom = lowest_point(stage)
    for cy in range(stage.size_y):
        for cx in range(stage.size_x):
            cell = stage.cell(cx, cy)
            if cell is None:
                continue
            for x, y in ((cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1)):
                points.append(project(x, y, cell.top))
                points.append(project(x, y, bottom))
    for platform in stage.soft_platforms:
        for x, y in (
            (platform.x0, platform.y0),
            (platform.x1, platform.y0),
            (platform.x0, platform.y1),
            (platform.x1, platform.y1),
        ):
            points.append(project(x, y, platform.z))
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _gap(low: float, high: float, other_low: float, other_high: float) -> float:
    """Return the distance between two spans on a line (0 if they overlap)."""
    return max(other_low - high, low - other_high, 0.0)


def _check_spawns(stage: Stage) -> Check:
    problems = []
    spawns = list(stage.spawns)
    for index, spawn in enumerate(spawns):
        if stage.surface_top(spawn.x, spawn.y) is None:
            problems.append(f"p{index + 1} is not on solid ground")
        for other_index in range(index):
            distance = (spawn - spawns[other_index]).length()
            if distance < MIN_SPAWN_GAP:
                problems.append(f"p{other_index + 1} and p{index + 1} are {distance:.1f} apart")
    closest = min(((a - b).length() for i, a in enumerate(spawns) for b in spawns[:i]), default=0.0)
    detail = "; ".join(problems) or f"{len(spawns)} spawns, the closest two {closest:.1f} apart"
    return Check("spawns", not problems, detail)


def _check_ledges(stage: Stage) -> Check:
    pieces = islands(stage)
    without = 0
    for piece in pieces:
        has_ledge = any(
            _ledge_cells(
                ledge.start.x,
                ledge.start.y,
                ledge.end.x,
                ledge.end.y,
                ledge.normal.x,
                ledge.normal.y,
            )
            & piece
            for ledge in stage.ledges
        )
        without += not has_ledge
    detail = f"{len(stage.ledges)} ledge lines on {len(pieces)} island(s)"
    if without:
        detail += f"; {without} island(s) have none"
    return Check("ledges", bool(stage.ledges) and not without, detail)


def _ledge_cells(
    x0: float, y0: float, x1: float, y1: float, normal_x: float, normal_y: float
) -> set[tuple[int, int]]:
    """Return the cells a ledge line belongs to: those just inside it along its length."""
    cells = set()
    if normal_x != 0.0:
        column = int(x0) - (1 if normal_x > 0 else 0)
        for row in range(int(min(y0, y1)), int(max(y0, y1))):
            cells.add((column, row))
    else:
        row = int(y0) - (1 if normal_y > 0 else 0)
        for column in range(int(min(x0, x1)), int(max(x0, x1))):
            cells.add((column, row))
    return cells


def _check_platforms(stage: Stage, hop: float) -> Check:
    reach = hop * PLATFORM_REACH
    surfaces = [
        (float(cx), float(cy), cx + 1.0, cy + 1.0, cell.top)
        for cy in range(stage.size_y)
        for cx in range(stage.size_x)
        if (cell := stage.cell(cx, cy)) is not None
    ]
    surfaces += [
        (float(p.x0), float(p.y0), float(p.x1), float(p.y1), p.z) for p in stage.soft_platforms
    ]
    problems = []
    worst = 0.0
    for index, platform in enumerate(stage.soft_platforms):
        rises = [
            platform.z - z
            for x0, y0, x1, y1, z in surfaces
            if z < platform.z
            and _gap(platform.x0, platform.x1, x0, x1) <= PLATFORM_NEAR
            and _gap(platform.y0, platform.y1, y0, y1) <= PLATFORM_NEAR
        ]
        rise = min(rises, default=float("inf"))
        worst = max(worst, rise)
        if rise > reach:
            problems.append(f"platform {index} is {rise:.2f} above the nearest surface")
    detail = "; ".join(problems) or (
        f"{len(stage.soft_platforms)} platform(s), the highest step {worst:.2f}"
        if stage.soft_platforms
        else "no platforms"
    )
    return Check("platforms_reachable", not problems, f"{detail} (one jump reaches {reach:.2f})")


def _check_fit(stage: Stage) -> Check:
    width, height = screen_extent(stage)
    room_w, room_h = PLAY_AREA.width - 2 * FIT_MARGIN, PLAY_AREA.height - 2 * FIT_MARGIN
    detail = f"{width:.0f} x {height:.0f} px in a play area of {room_w} x {room_h}"
    return Check("fits_play_area", width <= room_w and height <= room_h, detail)


def _check_blast_zones(stage: Stage) -> Check:
    zone, bounds = stage.blast_zone, stage.bounds
    top = max([bounds.z_max, *(platform.z for platform in stage.soft_platforms)])
    side = min(
        bounds.x_min - zone.x_min,
        zone.x_max - bounds.x_max,
        bounds.y_min - zone.y_min,
        zone.y_max - bounds.y_max,
    )
    above, below = zone.z_max - top, stage.underside - zone.z_min
    problems = []
    if side < MIN_BLAST_SIDE:
        problems.append(f"the side zone is only {side:.1f} from the ground")
    if above < MIN_BLAST_ABOVE:
        problems.append(f"the top zone is only {above:.1f} above the highest surface")
    if below < MIN_BLAST_BELOW:
        problems.append(f"the bottom zone is only {below:.1f} under the island")
    detail = "; ".join(problems) or f"side {side:.1f}, above {above:.1f}, below {below:.1f}"
    return Check("blast_zones", not problems, detail)


def _check_notches(stage: Stage) -> Check:
    notches = []
    for cy in range(stage.size_y):
        for cx in range(stage.size_x):
            if stage.cell(cx, cy) is not None:
                continue
            across = stage.cell(cx - 1, cy) is not None and stage.cell(cx + 1, cy) is not None
            along = stage.cell(cx, cy - 1) is not None and stage.cell(cx, cy + 1) is not None
            if across or along:
                notches.append((cx, cy))
    detail = f"1-wide notch at cells {notches[:6]}" if notches else "none"
    return Check("no_narrow_notch", not notches, detail)


def check_stage(stage: Stage, characters: Sequence[CharacterDef]) -> list[Check]:
    """Return every rule's verdict for a stage, in the order of :data:`RULES`. ``characters``
    is the roster: the lowest full hop among them decides what one jump reaches."""
    hop = min((hop_height(character) for character in characters), default=0.0)
    return [
        _check_spawns(stage),
        _check_ledges(stage),
        _check_platforms(stage, hop),
        _check_fit(stage),
        _check_blast_zones(stage),
        _check_notches(stage),
    ]


def failures(checks: Sequence[Check]) -> list[str]:
    """Return the names of the rules that did not pass."""
    return [check.rule for check in checks if not check.passed]
