"""Stage geometry questions a CPU asks: is there ground here, where is the nearest ledge,
where should I land.

Plan note "15 - CPU AI" ("Recovery logic") and "11 - Stages". Reads the immutable ``Stage``
only.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from isofightr import config
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import LedgeLine, Stage

CELL_CENTRE = 0.5


@dataclass(frozen=True, slots=True)
class LedgeTarget:
    """A ledge to recover to: the line, the nearest point on it, and its height."""

    ledge: LedgeLine
    point: Vec2

    @property
    def z(self) -> float:
        return self.ledge.z

    def approach(self, below: bool) -> Vec2:
        """Where to steer: outside the ledge while still below it (so as not to slide under
        the stage), inside it once level with it."""
        if below:
            return self.point + self.ledge.normal * config.CPU_LEDGE_APPROACH_OUT
        return self.point - self.ledge.normal * config.CPU_LEDGE_APPROACH_IN


def closest_point(ledge: LedgeLine, position: Vec2) -> Vec2:
    """The point of a ledge line nearest to ``position``."""
    along = ledge.end - ledge.start
    length_squared = along.dot(along)
    if length_squared == 0.0:
        return ledge.start
    t = max(0.0, min(1.0, (position - ledge.start).dot(along) / length_squared))
    return ledge.start + along * t


@cache
def ground_points(stage: Stage) -> tuple[Vec3, ...]:
    """Every place a fighter can stand: the centre of each solid cell's top and of each cell
    a soft platform covers."""
    points: list[Vec3] = []
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is not None:
                points.append(Vec3(cx + CELL_CENTRE, cy + CELL_CENTRE, cell.top))
    for platform in stage.soft_platforms:
        x = platform.x0 + CELL_CENTRE
        while x < platform.x1:
            y = platform.y0 + CELL_CENTRE
            while y < platform.y1:
                points.append(Vec3(x, y, platform.z))
                y += 1.0
            x += 1.0
    return tuple(points)


def ground_below(stage: Stage, x: float, y: float, z: float) -> float | None:
    """The height of whatever a fighter at ``(x, y, z)`` would land on, or ``None``."""
    return stage.support_below(x, y, z + config.CPU_STEP_HEIGHT)


def over_ground(stage: Stage, pos: Vec3) -> bool:
    """Whether something is below ``pos`` to land on."""
    return ground_below(stage, pos.x, pos.y, pos.z) is not None


def level_ground_ahead(stage: Stage, pos: Vec3, direction: Vec2, distance: float) -> bool:
    """Whether walking ``distance`` along ``direction`` keeps the feet on ground at about the
    same height (no drop and no wall)."""
    ahead = pos.xy + direction * distance
    below = ground_below(stage, ahead.x, ahead.y, pos.z)
    if below is None:
        return False
    return abs(below - pos.z) <= config.CPU_STEP_HEIGHT


def safe_spot(stage: Stage, target: Vec3, me: Vec3) -> Vec3:
    """The ground point nearest to ``target`` (horizontally), preferring ones at the height
    of ``me``: where to stand to reach a target that may be off the stage."""
    best = me
    best_score = float("inf")
    for point in ground_points(stage):
        score = (point.xy - target.xy).length() + abs(point.z - target.z) * 0.5
        if score < best_score:
            best, best_score = point, score
    if best is me:
        return me
    if not over_ground(stage, target):
        # Stand a little inside the edge, not on it.
        inward = stage.respawn - best.xy
        if inward.length() > 0.0:
            inward = inward.normalized() * config.CPU_SAFE_INSET
            return Vec3(best.x + inward.x, best.y + inward.y, best.z)
    return best


def recovery_ledge(
    stage: Stage, pos: Vec3, reachable_height: float, destination: Vec2 | None
) -> LedgeTarget | None:
    """The ledge to recover to: near, reachable, and (with a ``destination``) on the way.

    ``reachable_height`` is the highest ledge top the fighter can still get up to. Ledges
    above it are only picked if nothing else is left.
    """
    best: LedgeTarget | None = None
    best_score = float("inf")
    fallback: LedgeTarget | None = None
    fallback_score = float("inf")
    here = pos.xy
    for ledge in stage.ledges:
        point = closest_point(ledge, here)
        score = (point - here).length()
        if destination is not None:
            score += config.CPU_DESTINATION_BIAS * (point - destination).length()
        target = LedgeTarget(ledge, point)
        if ledge.z <= reachable_height:
            if score < best_score:
                best, best_score = target, score
        elif score < fallback_score:
            fallback, fallback_score = target, score
    return best if best is not None else fallback


# --- regions and routes ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Region:
    """Ground a fighter can walk around on without jumping: a group of touching solid cells
    of about the same height, or one soft platform."""

    index: int
    points: tuple[Vec3, ...]


@dataclass(frozen=True, slots=True)
class Link:
    """A jump (or drop) from one region to another: take off near ``start``, land near
    ``end``."""

    target: int
    start: Vec3
    end: Vec3
    cost: float


NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


@cache
def regions(stage: Stage) -> tuple[Region, ...]:
    """Every region of a stage: solid cells flood-filled by height, then each platform."""
    found: list[Region] = []
    seen: set[tuple[int, int]] = set()
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None or (cx, cy) in seen:
                continue
            group: list[Vec3] = []
            todo = [(cx, cy)]
            seen.add((cx, cy))
            while todo:
                x, y = todo.pop()
                here = stage.cells[y][x]
                assert here is not None
                group.append(Vec3(x + CELL_CENTRE, y + CELL_CENTRE, here.top))
                for dx, dy in NEIGHBOURS:
                    nx, ny = x + dx, y + dy
                    if (nx, ny) in seen or not (0 <= ny < len(stage.cells)):
                        continue
                    if not 0 <= nx < len(stage.cells[ny]):
                        continue
                    other = stage.cells[ny][nx]
                    if other is not None and abs(other.top - here.top) <= config.CPU_STEP_HEIGHT:
                        seen.add((nx, ny))
                        todo.append((nx, ny))
            found.append(Region(len(found), tuple(sorted(group, key=lambda p: (p.y, p.x)))))
    for platform in stage.soft_platforms:
        points = [
            Vec3(x + CELL_CENTRE, y + CELL_CENTRE, platform.z)
            for x in range(platform.x0, platform.x1)
            for y in range(platform.y0, platform.y1)
        ]
        found.append(Region(len(found), tuple(points)))
    return tuple(found)


def region_of(stage: Stage, pos: Vec3) -> int | None:
    """The region whose ground is under ``pos`` (within a step), or ``None``."""
    best: int | None = None
    best_distance = config.CPU_REGION_SNAP
    for region in regions(stage):
        for point in region.points:
            if abs(point.z - pos.z) > config.CPU_STEP_HEIGHT:
                continue
            distance = max(abs(point.x - pos.x), abs(point.y - pos.y))
            if distance < best_distance:
                best, best_distance = region.index, distance
    return best


@cache
def links(stage: Stage, reach: float, rise: float) -> tuple[tuple[Link, ...], ...]:
    """For each region, the regions a fighter can jump to: within ``reach`` units on the
    ground plane (centre to centre of the nearest cells) and at most ``rise`` higher."""
    table: list[list[Link]] = [[] for _ in regions(stage)]
    for source in regions(stage):
        for target in regions(stage):
            if target.index == source.index:
                continue
            best: Link | None = None
            for start in source.points:
                for end in target.points:
                    if end.z - start.z > rise:
                        continue
                    distance = (end.xy - start.xy).length()
                    if distance > reach:
                        continue
                    cost = distance + abs(end.z - start.z) * config.CPU_ROUTE_HEIGHT_COST
                    if best is None or cost < best.cost:
                        best = Link(target.index, start, end, cost)
            if best is not None:
                table[source.index].append(best)
    return tuple(tuple(row) for row in table)


def route(stage: Stage, start: int, goal: int, reach: float, rise: float) -> list[Link]:
    """The cheapest chain of jumps from region ``start`` to region ``goal`` (empty if they
    are the same region or there is no way)."""
    if start == goal:
        return []
    table = links(stage, round(reach, 2), round(rise, 2))
    cost: dict[int, float] = {start: 0.0}
    via: dict[int, Link] = {}
    came: dict[int, int] = {}
    frontier = [(0.0, start)]
    while frontier:
        frontier.sort()
        spent, here = frontier.pop(0)
        if here == goal:
            break
        if spent > cost.get(here, float("inf")):
            continue
        for link in table[here]:
            total = spent + link.cost
            if total < cost.get(link.target, float("inf")):
                cost[link.target] = total
                via[link.target] = link
                came[link.target] = here
                frontier.append((total, link.target))
    if goal not in via:
        return []
    chain = [via[goal]]
    while came[chain[-1].target] != start:
        previous = came[chain[-1].target]
        chain.append(via[previous])
    chain.reverse()
    return chain
