"""Integration plus ground, soft-platform, wall and ceiling collision.

Plan note "04 - Movement and Physics" ("Stage collision (heightmap model)"). Stages are grids
of solid cells, each solid from the island's underside up to its top, plus soft platform
decks. A fighter is a vertical cylinder standing on its feet point.

Per tick, a state first updates the fighter's velocity (the helpers in the first half of this
module), then :func:`step` moves it and resolves collisions.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from isofightr.config import SURFACE_EPSILON
from isofightr.sim.combat.constants import KB_DECAY
from isofightr.sim.constants import (
    EDGE_TOLERANCE,
    PLATFORM_DROP_CLEARANCE,
    STEP_HEIGHT,
    WALL_SKIN,
)
from isofightr.sim.fighter import Fighter, GroundKind
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.stage import NO_PLATFORM, Stage

# --- velocity updates (called by states before the fighter is moved) -----------------------


def apply_traction(fighter: Fighter, multiplier: float = 1.0) -> None:
    """Slow a grounded fighter's ground velocity by its traction, stopping at zero."""
    horizontal = fighter.vel.xy
    speed = horizontal.length()
    loss = fighter.character.movement.traction * multiplier
    horizontal = Vec2() if speed <= loss else horizontal * ((speed - loss) / speed)
    fighter.vel = Vec3(horizontal.x, horizontal.y, 0.0)


def set_ground_velocity(fighter: Fighter, velocity: Vec2) -> None:
    """Set a grounded fighter's driven velocity (walk, dash, run)."""
    fighter.vel = Vec3(velocity.x, velocity.y, 0.0)


def apply_gravity(fighter: Fighter, multiplier: float = 1.0) -> None:
    """Accelerate an airborne fighter downward, capped at its fall speed.

    Fast fall replaces the cap: the fighter drops at ``fast_fall`` speed straight away.
    ``multiplier`` scales both gravity and the cap (a launched fighter falls more slowly).
    """
    stats = fighter.character.movement
    if fighter.fast_falling:
        fall = -stats.fast_fall
    else:
        fall = max(fighter.vel.z - stats.gravity * multiplier, -stats.max_fall * multiplier)
    fighter.vel = Vec3(fighter.vel.x, fighter.vel.y, fall)


def apply_air_drift(fighter: Fighter, multiplier: float = 1.0) -> None:
    """Steer an airborne fighter toward the stick, capped as a circle at its air speed.

    ``multiplier`` scales the acceleration (drift is weaker during hitstun).
    """
    stats = fighter.character.movement
    horizontal = fighter.vel.xy
    if fighter.buffer.stick_active:
        horizontal = clamp_length(
            horizontal + fighter.buffer.move * (stats.air_accel * multiplier), stats.air_speed
        )
    else:
        speed = horizontal.length()
        if speed <= stats.air_friction:
            horizontal = Vec2()
        else:
            horizontal = horizontal * ((speed - stats.air_friction) / speed)
    fighter.vel = Vec3(horizontal.x, horizontal.y, fighter.vel.z)


def decay_knockback(fighter: Fighter) -> None:
    """Shrink knockback velocity by ``KB_DECAY`` along its own direction, down to zero.

    On the ground the fighter's traction slows the slide as well.
    """
    speed = fighter.kb_vel.length()
    if speed == 0.0:
        return
    loss = KB_DECAY + (fighter.character.movement.traction if fighter.grounded else 0.0)
    if speed <= loss:
        fighter.kb_vel = ZERO3
    else:
        fighter.kb_vel = fighter.kb_vel * ((speed - loss) / speed)


def clamp_length(vector: Vec2, limit: float) -> Vec2:
    """Return ``vector`` shortened to ``limit`` if it is longer (a circular cap)."""
    length = vector.length()
    return vector if length <= limit else vector * (limit / length)


# --- movement and collision ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Support:
    """A surface under a fighter's feet."""

    height: float
    platform: int
    """Soft platform index, or ``NO_PLATFORM`` for a solid cell top."""

    @property
    def kind(self) -> GroundKind:
        """The ground kind a fighter standing on this surface has."""
        return GroundKind.CELL if self.platform == NO_PLATFORM else GroundKind.PLATFORM


@dataclass(frozen=True, slots=True)
class StepResult:
    """What happened to a fighter during one physics step."""

    landed: bool = False
    left_ground: bool = False
    fall_speed: float = 0.0
    """Downward speed just before a landing, in units per frame."""
    wall_normal: Vec2 | None = None
    """Set when an airborne fighter was stopped by a wall: the unit normal away from it."""
    wall_knockback: Vec3 = ZERO3
    """The knockback velocity the fighter had before the wall stopped it."""


_NOTHING = StepResult()


def step(stage: Stage, fighter: Fighter, stop_at_edges: bool = False) -> StepResult:
    """Move a fighter by its velocities for one tick and resolve stage collision.

    With ``stop_at_edges`` a grounded fighter is held at an edge instead of going over it.
    """
    if not fighter.in_play or fighter.ground is GroundKind.REVIVAL:
        return _NOTHING
    delta = fighter.vel + fighter.kb_vel
    if fighter.grounded:
        return _move_grounded(stage, fighter, delta.xy, stop_at_edges)
    return _move_airborne(stage, fighter, delta)


def nudge_grounded(
    stage: Stage, fighter: Fighter, offset: Vec2, stop_at_edges: bool = False
) -> StepResult:
    """Shift a grounded fighter sideways (pushboxes), with the same collision as walking."""
    return _move_grounded(stage, fighter, offset, stop_at_edges)


def shift(stage: Stage, fighter: Fighter, offset: Vec2) -> None:
    """Move a fighter sideways outside the normal step (SDI), respecting walls and edges."""
    if fighter.grounded:
        _move_grounded(stage, fighter, offset)
    else:
        x, y, _, _ = _slide_along_walls(stage, fighter, offset)
        fighter.pos = Vec3(x, y, fighter.pos.z)


def support_under(
    stage: Stage,
    x: float,
    y: float,
    low: float,
    high: float,
    radius: float,
    ignore_platform: int = NO_PLATFORM,
) -> Support | None:
    """Return the highest surface with ``low <= height <= high`` under a feet point.

    For a forgiving feel at edges (plan note 04, "Edge tolerance"), if nothing is directly
    under the feet point, points up to ``radius * EDGE_TOLERANCE`` away along each axis are
    tried in a fixed order.
    """
    reach = radius * EDGE_TOLERANCE
    for offset_x, offset_y in (
        (0.0, 0.0),
        (reach, 0.0),
        (-reach, 0.0),
        (0.0, reach),
        (0.0, -reach),
    ):
        found = _support_at(stage, x + offset_x, y + offset_y, low, high, ignore_platform)
        if found is not None:
            return found
    return None


def _support_at(
    stage: Stage, x: float, y: float, low: float, high: float, ignore_platform: int
) -> Support | None:
    best: Support | None = None
    top = stage.surface_top(x, y)
    if top is not None and low - SURFACE_EPSILON <= top <= high + SURFACE_EPSILON:
        best = Support(top, NO_PLATFORM)
    for index, platform in enumerate(stage.soft_platforms):
        if index == ignore_platform or not platform.contains(x, y):
            continue
        in_range = low - SURFACE_EPSILON <= platform.z <= high + SURFACE_EPSILON
        if in_range and (best is None or platform.z > best.height):
            best = Support(platform.z, index)
    return best


def _move_grounded(
    stage: Stage, fighter: Fighter, delta: Vec2, stop_at_edges: bool = False
) -> StepResult:
    pos = fighter.pos
    radius = fighter.character.body.radius
    x, y, _, _ = _slide_along_walls(stage, fighter, delta)
    low, high = pos.z - STEP_HEIGHT, pos.z + STEP_HEIGHT
    support = support_under(stage, x, y, low, high, radius)
    if support is None and stop_at_edges:
        # Held at the edge: keep whichever single axis of the move still has ground under it.
        for hold_x, hold_y in ((x, pos.y), (pos.x, y), (pos.x, pos.y)):
            support = support_under(stage, hold_x, hold_y, low, high, radius)
            if support is not None:
                x, y = hold_x, hold_y
                break
    if support is None:
        # Walked or was pushed off an edge: keep the height and start falling.
        fighter.pos = Vec3(x, y, pos.z)
        fighter.ground = GroundKind.NONE
        fighter.platform = NO_PLATFORM
        return StepResult(left_ground=True)
    fighter.pos = Vec3(x, y, support.height)
    fighter.ground = support.kind
    fighter.platform = support.platform
    return _NOTHING


def _move_airborne(stage: Stage, fighter: Fighter, delta: Vec3) -> StepResult:
    pos = fighter.pos
    body = fighter.character.body
    knockback = fighter.kb_vel
    x, y, blocked_x, blocked_y = _slide_along_walls(stage, fighter, delta.xy)
    wall_normal: Vec2 | None = None
    if blocked_x:
        wall_normal = Vec2(-1.0 if delta.x > 0 else 1.0, 0.0)
    elif blocked_y:
        wall_normal = Vec2(0.0, -1.0 if delta.y > 0 else 1.0)
    new_z = pos.z + delta.z

    if delta.z <= 0.0:
        # Swept landing: any surface the feet crossed or touched this tick. A cell top up to
        # one step above the feet also counts, so clipping an edge lands instead of sinking in.
        support = support_under(stage, x, y, new_z, pos.z, body.radius, fighter.drop_platform)
        lip = _cell_lip(stage, x, y, pos.z, new_z)
        if lip is not None and (support is None or lip > support.height):
            support = Support(lip, NO_PLATFORM)
        if support is not None:
            fighter.pos = Vec3(x, y, support.height)
            fighter.ground = support.kind
            fighter.platform = support.platform
            fighter.drop_platform = NO_PLATFORM
            fighter.vel = Vec3(fighter.vel.x, fighter.vel.y, 0.0)
            fighter.kb_vel = Vec3(fighter.kb_vel.x, fighter.kb_vel.y, 0.0)
            return StepResult(landed=True, fall_speed=-delta.z)
    else:
        lip = _cell_lip(stage, x, y, pos.z, new_z)
        if lip is not None:
            new_z = lip  # rising past an edge: the feet come out on top of it
        elif _hits_underside(stage, x, y, pos.z + body.height, new_z + body.height):
            new_z = stage.underside - body.height
            fighter.vel = Vec3(fighter.vel.x, fighter.vel.y, 0.0)

    fighter.pos = Vec3(x, y, new_z)
    if fighter.drop_platform != NO_PLATFORM:
        deck = stage.soft_platforms[fighter.drop_platform].z
        if new_z < deck - PLATFORM_DROP_CLEARANCE:
            fighter.drop_platform = NO_PLATFORM
    if wall_normal is not None:
        return StepResult(wall_normal=wall_normal, wall_knockback=knockback)
    return _NOTHING


def _cell_lip(stage: Stage, x: float, y: float, old_z: float, new_z: float) -> float | None:
    """Return the top of the solid cell under the feet if the feet are just below it.

    "Just below" means within one step height: walls stop anything lower, so this is the only
    way feet can be inside a cell's footprint and under its top.
    """
    top = stage.surface_top(x, y)
    if top is not None and new_z < top <= old_z + STEP_HEIGHT + SURFACE_EPSILON:
        return top
    return None


def _hits_underside(stage: Stage, x: float, y: float, old_head: float, new_head: float) -> bool:
    """Return whether a rising fighter's head crosses the island's underside this tick."""
    underside = stage.underside
    return (
        stage.surface_top(x, y) is not None
        and old_head <= underside + SURFACE_EPSILON
        and new_head > underside
    )


def _is_wall(stage: Stage, cx: int, cy: int, feet: float, height: float) -> bool:
    """Return whether a cell blocks a body standing at ``feet`` height.

    A cell is a wall when its solid span overlaps the body by more than a step: its top is
    more than ``STEP_HEIGHT`` above the feet, and its underside is below the head.
    """
    cell = stage.cell(cx, cy)
    return cell is not None and cell.top > feet + STEP_HEIGHT and stage.underside < feet + height


def _slide_along_walls(
    stage: Stage, fighter: Fighter, delta: Vec2
) -> tuple[float, float, bool, bool]:
    """Move the fighter's ground position by ``delta``, stopping each axis at walls.

    Axes are resolved one after the other, which slides the fighter along a wall it runs into
    at an angle. The blocked component of both velocities is removed. Returns the new
    ``x`` and ``y`` and whether each axis was blocked.
    """
    pos = fighter.pos
    body = fighter.character.body
    x, blocked_x = _advance(stage, pos.x, pos.y, delta.x, pos.z, body.radius, body.height, True)
    y, blocked_y = _advance(stage, pos.y, x, delta.y, pos.z, body.radius, body.height, False)
    if blocked_x or blocked_y:
        fighter.vel = _without(fighter.vel, blocked_x, blocked_y)
        fighter.kb_vel = _without(fighter.kb_vel, blocked_x, blocked_y)
    return x, y, blocked_x, blocked_y


def _without(velocity: Vec3, drop_x: bool, drop_y: bool) -> Vec3:
    return Vec3(0.0 if drop_x else velocity.x, 0.0 if drop_y else velocity.y, velocity.z)


def _advance(
    stage: Stage,
    along: float,
    across: float,
    step_along: float,
    feet: float,
    radius: float,
    height: float,
    along_is_x: bool,
) -> tuple[float, bool]:
    """Move one coordinate by ``step_along``, stopping at the first wall cell.

    The body is treated as a square of half-size ``radius``. Every grid line the leading
    edge crosses is checked, so a fast fighter cannot tunnel through a thin wall.
    """
    if step_along == 0.0:
        return along, False
    direction = 1 if step_along > 0 else -1
    first_across = math.floor(across - radius + WALL_SKIN)
    last_across = math.floor(across + radius - WALL_SKIN)
    lead_start = along + direction * radius
    lead_end = lead_start + step_along
    start_cell = math.floor(lead_start)
    end_cell = math.floor(lead_end)
    for cell in range(start_cell + direction, end_cell + direction, direction):
        for other in range(first_across, last_across + 1):
            cx, cy = (cell, other) if along_is_x else (other, cell)
            if _is_wall(stage, cx, cy, feet, height):
                boundary = cell if direction > 0 else cell + 1
                return boundary - direction * (radius + WALL_SKIN), True
    return along + step_along, False
