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
from dataclasses import dataclass, replace
from typing import Final

from isofightr.config import (
    AMBIENT_KINDS,
    AMBIENT_MAX,
    ISLAND_THICKNESS,
    LEDGE_MIN_DROP,
    MIN_PLATFORM_CLEARANCE,
    PLAYER_SPAWN_COUNT,
    PROP_LAYERS,
    SURFACE_EPSILON,
    UNDERSIDE_MAX_DEPTH,
)
from isofightr.sim.constants import (
    HAZARD_KINDS,
    HAZARD_SAFE_FRAMES,
    MAX_BOUNCE,
    MAX_PLATFORM_SPEED,
    MIN_MOTION_PERIOD,
    MOTION_KINDS,
    PATH_SAMPLES,
)
from isofightr.sim.math3d import ZERO2, ZERO3, Box3, Vec2, Vec3
from isofightr.sim.move_def import DirectionMode, Effect, HitboxDef

VOID_SYMBOL: Final[str] = "."
DEFAULT_TILE: Final[str] = "default"
NO_PLATFORM: Final[int] = -1
"""Stands in for a soft platform index when something is not on (or about) a platform."""

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
    traction: float = 1.0
    """Multiplier on the traction of whoever stands here (ice is about 0.25). Like the two
    below, it only counts while the match's stage hazards are on (decision D-063)."""
    drive: Vec2 = ZERO2
    """A conveyor: how far the cell carries a fighter standing on it, per frame."""
    bounce: float = 0.0
    """A spring: the upward speed it throws a fighter that touches it (0 = none)."""

    @property
    def plain(self) -> bool:
        """Whether the cell is ordinary ground (no surface modifier)."""
        return self.traction == 1.0 and self.drive == ZERO2 and self.bounce == 0.0


@dataclass(frozen=True, slots=True)
class PlatformMotion:
    """How a soft platform moves: a trip through ``points`` that repeats every ``period``
    frames. Where it is on a frame is a fixed function of the frame, so nothing is stored."""

    kind: str
    """``"ping_pong"`` (out through the points and back the same way), ``"loop"`` (through
    the points and straight home) or ``"bob"`` (up by its amplitude and down again)."""
    points: tuple[Vec3, ...]
    """Where it goes, as offsets from where it rests."""
    period: int
    phase: int = 0
    """Frames it is ahead: two platforms with the same trip need not move together."""

    def _stops(self) -> tuple[Vec3, ...]:
        if self.kind == "loop":
            return (ZERO3, *self.points)
        return (ZERO3, *self.points, *reversed(self.points[:-1]))

    def offset(self, frame: int) -> Vec3:
        """Return how far the platform is from its rest position on a frame. It eases out of
        each stop and into the next, so it never jerks."""
        stops = self._stops()
        leg = self.period / len(stops)
        moment = (frame + self.phase) % self.period
        index = min(int(moment // leg), len(stops) - 1)
        along = (moment - index * leg) / leg
        eased = along * along * (3.0 - 2.0 * along)
        start, end = stops[index], stops[(index + 1) % len(stops)]
        return start + (end - start) * eased


@dataclass(frozen=True, slots=True)
class SoftPlatform:
    """A thin deck you can land on from above and pass through from below."""

    x0: float
    y0: float
    x1: float
    y1: float
    z: float
    motion: PlatformMotion | None = None
    step: Vec3 = ZERO3
    """How far it moved since the frame before (set on the copies :meth:`Stage.at` makes):
    whoever stands on it is carried this far, and a landing is swept against it."""

    def at(self, frame: int) -> SoftPlatform:
        """Return the platform where it is on a frame (itself if it does not move)."""
        if self.motion is None:
            return self
        now, before = self.motion.offset(frame), self.motion.offset(frame - 1)
        return SoftPlatform(
            self.x0 + now.x,
            self.y0 + now.y,
            self.x1 + now.x,
            self.y1 + now.y,
            self.z + now.z,
            self.motion,
            now - before,
        )

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
class Hazard:
    """A stage's own danger (decision D-063): an upright cylinder at a fixed place that is
    quiet for ``rest`` frames, warns for ``warn`` frames, then is active for ``active``
    frames, round and round. A ``geyser`` or ``lightning`` hits whoever is in it, once per
    time it goes off; a ``wind`` pushes them while it blows."""

    kind: str
    x: float
    y: float
    radius: float
    z: float
    """Height of its foot."""
    height: float
    rest: int
    warn: int
    active: int
    phase: int = 0
    """Frames it is ahead in its cycle."""
    hitbox: HitboxDef | None = None
    """What a geyser or lightning hits with."""
    push: Vec3 = ZERO3
    """How far a wind carries a fighter, per frame."""

    @property
    def cycle(self) -> int:
        """Frames from one activation to the next."""
        return self.rest + self.warn + self.active

    def moment(self, frame: int) -> tuple[str, int, int]:
        """Return what the hazard is doing on a frame: ``("rest" | "warn" | "active", how
        many frames into that, which activation this is, counted from the match's start)``."""
        turn, inside = divmod(frame + self.phase, self.cycle)
        if inside < self.rest:
            return ("rest", inside, turn)
        if inside < self.rest + self.warn:
            return ("warn", inside - self.rest, turn)
        return ("active", inside - self.rest - self.warn, turn)

    def is_active(self, frame: int) -> bool:
        """Return whether the hazard hits or blows on a frame."""
        return (frame + self.phase) % self.cycle >= self.rest + self.warn

    def first_active(self) -> int:
        """Return the first frame of a match the hazard is active on."""
        inside = self.phase % self.cycle
        start = self.rest + self.warn
        return 0 if inside >= start else start - inside

    def covers(self, x: float, y: float, reach: float = 0.0) -> bool:
        """Return whether a ground position is within ``reach`` of the hazard's circle."""
        return (Vec2(x, y) - Vec2(self.x, self.y)).length() <= self.radius + reach

    def touches(self, pos: Vec3, radius: float, height: float) -> bool:
        """Return whether a body (feet at ``pos``) overlaps the hazard's cylinder."""
        return (
            self.covers(pos.x, pos.y, radius)
            and pos.z < self.z + self.height
            and pos.z + height > self.z
        )


def hazard_hitbox(damage: float, angle: float, bkb: float, kbg: float, effect: Effect) -> HitboxDef:
    """Return the hit a hazard deals, as the same kind of hitbox a move has: it launches
    away from the hazard's middle."""
    return HitboxDef(
        id=0,
        group=0,
        offset=ZERO3,
        radius=0.0,
        damage=damage,
        angle=angle,
        yaw=0.0,
        direction_mode=DirectionMode.RADIAL,
        bkb=bkb,
        kbg=kbg,
        fkb=0.0,
        hitlag_mult=1.0,
        sdi_mult=1.0,
        effect=effect,
        hits_ground=True,
        hits_air=True,
        rehit=0,
        clank=False,
    )


@dataclass(frozen=True, slots=True)
class BackgroundLayer:
    """One parallax background image."""

    image: str
    parallax: float
    scroll: float = 0.0
    """Pixels the layer drifts to the left every tick by itself (clouds, smoke)."""
    frames: int = 1
    """How many frames the image holds, stacked top to bottom (a short looping animation)."""
    frame_ticks: int = 0
    """Ticks each frame shows for (0 = the game's default)."""


@dataclass(frozen=True, slots=True)
class Prop:
    """A decoration from the stage's tileset. Looks only: it never collides (D-063)."""

    sprite: str
    x: float
    y: float
    layer: str = "world"
    """``"world"``: standing on the ground here. ``"below"``: hanging under the island."""
    period: int = 0
    """Ticks per frame of an animated prop (0 = the game's default)."""
    phase: int = 0
    """Ticks this prop's animation runs ahead, so neighbours do not move in step."""


@dataclass(frozen=True, slots=True)
class Ambient:
    """Slow sprites drifting across the screen (leaves, snow, embers). Looks only."""

    kind: str
    count: int
    front: int = 0
    """How many of them drift in front of the world; the rest are behind it."""


@dataclass(frozen=True, slots=True)
class Underside:
    """A ragged mass hanging under the island in place of its flat bottom. Looks only."""

    depth: float
    """How far the deepest part hangs below the island's underside, in units."""
    tile: str = "under"
    hang: tuple[str, ...] = ()
    """Tileset props hung from it here and there (roots, chains, icicles)."""


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
    description: str = ""
    """One line for the stage select screen (menu text only; empty = made from the data)."""
    props: tuple[Prop, ...] = ()
    ambient: Ambient | None = None
    underside_art: Underside | None = None
    hazards: tuple[Hazard, ...] = ()

    @property
    def moves(self) -> bool:
        """Whether any of the stage's platforms moves."""
        return any(platform.motion is not None for platform in self.soft_platforms)

    @property
    def has_mechanics(self) -> bool:
        """Whether the stage has anything the "stage hazards" rule switches off: a moving
        platform, a hazard, or ground that is not plain."""
        return (
            self.moves
            or bool(self.hazards)
            or any(cell is not None and not cell.plain for row in self.cells for cell in row)
        )

    def at(self, frame: int) -> Stage:
        """Return the stage as it is on a frame of a match: itself, unless a platform moves.

        The copy differs only in where its soft platforms are, so everything that reads
        platforms (collision, shadows, projectiles) sees them where they are now."""
        if not self.moves:
            return self
        return replace(
            self, soft_platforms=tuple(platform.at(frame) for platform in self.soft_platforms)
        )

    @property
    def size_x(self) -> int:
        """Number of grid columns (extent along world x)."""
        return len(self.cells[0])

    @property
    def size_y(self) -> int:
        """Number of grid rows (extent along world y)."""
        return len(self.cells)

    @property
    def underside(self) -> float:
        """Height of the island's underside: solid cells are solid from here up to their top.

        Below this a fighter can pass under the island, as under a floating stage in Smash.
        """
        return self.bounds.z_min - ISLAND_THICKNESS

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
    description: str = "",
    props: Sequence[Prop] = (),
    ambient: Ambient | None = None,
    underside_art: Underside | None = None,
    hazards: Sequence[Hazard] = (),
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
        description=description,
        props=tuple(props),
        ambient=ambient,
        underside_art=underside_art,
        hazards=tuple(hazards),
    )
    _validate_platforms(stage)
    _validate_spawns(stage)
    _validate_decor(stage)
    _validate_mechanics(stage)
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


def path_extent(platform: SoftPlatform) -> Box3:
    """Return the box a platform's deck stays inside over its whole trip (its own rectangle
    if it does not move)."""
    stops = (ZERO3,) if platform.motion is None else (ZERO3, *platform.motion.points)
    return Box3(
        platform.x0 + min(stop.x for stop in stops),
        platform.x1 + max(stop.x for stop in stops),
        platform.y0 + min(stop.y for stop in stops),
        platform.y1 + max(stop.y for stop in stops),
        platform.z + min(stop.z for stop in stops),
        platform.z + max(stop.z for stop in stops),
    )


def _camera_bounds(bounds: Box3, platforms: Sequence[SoftPlatform], margin: float) -> Box3:
    """The camera may frame everything solid and everywhere a platform ever goes."""
    extents = [path_extent(platform) for platform in platforms]
    highest = max([bounds.z_max, *(extent.z_max for extent in extents)])
    return Box3(
        min([bounds.x_min, *(extent.x_min for extent in extents)]) - margin,
        max([bounds.x_max, *(extent.x_max for extent in extents)]) + margin,
        min([bounds.y_min, *(extent.y_min for extent in extents)]) - margin,
        max([bounds.y_max, *(extent.y_max for extent in extents)]) + margin,
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
        for cy in range(int(platform.y0), int(platform.y1)):
            for cx in range(int(platform.x0), int(platform.x1)):
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


def _validate_decor(stage: Stage) -> None:
    """Check the stage's looks-only data: backdrop animation, props, ambience, underside."""
    for index, layer in enumerate(stage.backgrounds):
        if layer.frames < 1 or layer.frame_ticks < 0:
            raise StageError(f"background {index}: frames must be 1 or more, frame_ticks 0 or more")
    for index, prop in enumerate(stage.props):
        where = f"prop {index} ({prop.sprite})"
        if prop.layer not in PROP_LAYERS:
            raise StageError(f"{where}: layer must be one of {', '.join(PROP_LAYERS)}")
        if stage.cell_at(prop.x, prop.y) is None:
            raise StageError(f"{where}: ({prop.x}, {prop.y}) is not over solid ground")
        if prop.period < 0 or prop.phase < 0:
            raise StageError(f"{where}: period and phase must be 0 or more")
    ambient = stage.ambient
    if ambient is not None:
        if ambient.kind not in AMBIENT_KINDS:
            raise StageError(f"ambient: kind must be one of {', '.join(AMBIENT_KINDS)}")
        if not 1 <= ambient.count <= AMBIENT_MAX:
            raise StageError(f"ambient: count must be 1 to {AMBIENT_MAX}")
        if not 0 <= ambient.front <= ambient.count:
            raise StageError("ambient: front must be between 0 and count")
    under = stage.underside_art
    if under is not None and not 0.0 < under.depth <= UNDERSIDE_MAX_DEPTH:
        raise StageError(f"underside: depth must be above 0 and at most {UNDERSIDE_MAX_DEPTH}")


def _validate_motion(stage: Stage, index: int, platform: SoftPlatform) -> None:
    """Check a moving platform: a sane trip, never too fast for a fighter to ride, and
    always clear of the ground it passes over."""
    motion = platform.motion
    if motion is None:
        return
    where = f"soft platform {index}"
    if motion.kind not in MOTION_KINDS:
        raise StageError(f"{where}: motion kind must be one of {', '.join(MOTION_KINDS)}")
    if not motion.points or all(point == ZERO3 for point in motion.points):
        raise StageError(f"{where}: its motion goes nowhere")
    if motion.period < MIN_MOTION_PERIOD:
        raise StageError(f"{where}: motion period must be at least {MIN_MOTION_PERIOD} frames")
    if motion.phase < 0:
        raise StageError(f"{where}: motion phase must be 0 or more")
    blast = stage.blast_zone
    for sample in range(PATH_SAMPLES):
        frame = sample * motion.period // PATH_SAMPLES
        moved = platform.at(frame)
        if moved.step.length() > MAX_PLATFORM_SPEED:
            raise StageError(
                f"{where}: it moves {moved.step.length():.3f} units a frame, "
                f"more than {MAX_PLATFORM_SPEED} (lengthen the period)"
            )
        if not (
            blast.x_min < moved.x0
            and moved.x1 < blast.x_max
            and blast.y_min < moved.y0
            and moved.y1 < blast.y_max
            and blast.z_min < moved.z < blast.z_max
        ):
            raise StageError(f"{where}: its trip leaves the blast zone")
        for cy in range(math.floor(moved.y0), math.ceil(moved.y1)):
            for cx in range(math.floor(moved.x0), math.ceil(moved.x1)):
                cell = stage.cell(cx, cy)
                if cell is not None and moved.z < cell.top + MIN_PLATFORM_CLEARANCE:
                    raise StageError(
                        f"{where}: on its trip it comes within {MIN_PLATFORM_CLEARANCE} of "
                        f"the cell at ({cx}, {cy}) with top {cell.top}"
                    )


def _validate_mechanics(stage: Stage) -> None:
    """Check everything the "stage hazards" rule governs (decision D-063)."""
    for index, platform in enumerate(stage.soft_platforms):
        _validate_motion(stage, index, platform)
    spawns = [*stage.spawns, stage.respawn]
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None or cell.plain:
                continue
            where = f"cell ({cx}, {cy})"
            if not 0.0 < cell.traction <= 2.0:
                raise StageError(f"{where}: traction must be above 0 and at most 2")
            if not 0.0 <= cell.bounce <= MAX_BOUNCE:
                raise StageError(f"{where}: bounce must be 0 to {MAX_BOUNCE}")
            pushes = cell.drive != ZERO2 or cell.bounce > 0.0
            if pushes and any((int(spawn.x), int(spawn.y)) == (cx, cy) for spawn in spawns):
                raise StageError(f"{where}: a spawn stands on a conveyor or a spring")
    for index, hazard in enumerate(stage.hazards):
        where = f"hazard {index} ({hazard.kind})"
        if hazard.kind not in HAZARD_KINDS:
            raise StageError(f"{where}: kind must be one of {', '.join(HAZARD_KINDS)}")
        if hazard.radius <= 0.0 or hazard.height <= 0.0:
            raise StageError(f"{where}: radius and height must be above 0")
        if hazard.warn < 1 or hazard.active < 1 or hazard.rest < 0 or hazard.phase < 0:
            raise StageError(
                f"{where}: warn and active must be 1 or more, rest and phase 0 or more"
            )
        if hazard.kind == "wind":
            if hazard.push == ZERO3:
                raise StageError(f"{where}: a wind needs a push")
        elif hazard.hitbox is None or hazard.hitbox.damage <= 0.0:
            raise StageError(f"{where}: it needs damage")
        if hazard.first_active() < HAZARD_SAFE_FRAMES:
            for spawn in spawns:
                if hazard.covers(spawn.x, spawn.y):
                    raise StageError(
                        f"{where}: it is active over a spawn on frame {hazard.first_active()}, "
                        f"before frame {HAZARD_SAFE_FRAMES} (give it more rest or less phase)"
                    )
