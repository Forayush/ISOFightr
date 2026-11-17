"""Several opponents, teammates and the stage itself (decision D-071, M20 group 6).

Plan note "15 - CPU AI" ("Several opponents, teams, stages"):

- :func:`target_cost`: which opponent to fight. Near is good; an opponent the CPU cannot hurt
  (just respawned) is not worth walking up to; one at high percent is a KO waiting; in a
  timed match the leader (the best score) is the one to bring down; the
  current target is kept unless another is clearly better (so the CPU does not flit); and at
  KO percent itself, the CPU keeps out of two opponents already fighting each other.
- :func:`ally_risk`: how much of an action's hitboxes would pass over a teammate, so that with
  friendly fire on it is not swung through one.
- :func:`danger_zones` / :func:`clear_of`: hazards that hit and are active or about to be,
  and a place outside them.

Pure Python (no ``arcade``).
"""

from __future__ import annotations

from collections.abc import Sequence

from isofightr import config
from isofightr.ai.knowledge import Action
from isofightr.ai.view import FighterView, HazardView
from isofightr.sim.math3d import Vec2, Vec3


def _rotate(local: Vec3, forward: Vec2) -> Vec3:
    left = forward.perpendicular_left()
    return Vec3(
        local.x * forward.x + local.y * left.x, local.x * forward.y + local.y * left.y, local.z
    )


def target_cost(
    me: FighterView,
    other: FighterView,
    opponents: Sequence[FighterView],
    focus: int | None,
    timed: bool,
) -> float:
    """How much the CPU would rather not fight ``other`` (lower is better), among
    ``opponents`` (every opponent in play, ``other`` included)."""
    cost = (other.pos - me.pos).length()
    if other.invincible:
        cost += config.CPU_TARGET_INVINCIBLE_COST
    cost -= config.CPU_TARGET_PERCENT_VALUE * min(other.damage, config.CPU_TARGET_PERCENT_CAP)
    if len(opponents) > 1:
        if timed:
            # In a timed match the leader is the one to bring down. (In a stock match every
            # CPU going for the leader ganged up on the best player: level 9 won 14 of 44
            # mixed-level matches instead of 24.)
            best = max(o.score for o in opponents)
            if other.score >= best and any(o.score < best for o in opponents):
                cost -= config.CPU_TARGET_LEADER_VALUE
        if me.damage >= config.CPU_BRAWL_PERCENT:
            for third in opponents:
                if third.index == other.index:
                    continue
                if (third.pos - other.pos).length() <= config.CPU_BRAWL_RANGE:
                    cost += config.CPU_BRAWL_COST
                    break
    if focus is not None and other.index == focus:
        cost -= config.CPU_TARGET_HOLD
    return cost


def ally_risk(me: FighterView, action: Action, aim: Vec2, allies: Sequence[FighterView]) -> float:
    """0 to 1: the share of an action's hit frames whose hitboxes reach a teammate where it
    stands now (projectiles as recorded, the first stretch of their flight)."""
    if not allies or not action.hit_frames:
        return 0.0
    reached = 0
    for hit_frame in action.hit_frames:
        found = False
        for sphere in hit_frame.spheres:
            if sphere.grab:
                continue
            centre = me.pos + _rotate(sphere.centre, aim)
            for ally in allies:
                box = ally.hurtbox
                low = ally.pos.z + box.z0
                high = ally.pos.z + box.z1
                z = min(max(centre.z, low), high)
                gap = Vec3(centre.x - ally.pos.x, centre.y - ally.pos.y, centre.z - z).length()
                if gap <= sphere.radius + box.radius + config.CPU_ALLY_CLEARANCE:
                    found = True
                    break
            if found:
                break
        reached += found
    return reached / len(action.hit_frames)


def danger_zones(hazards: Sequence[HazardView]) -> list[HazardView]:
    """Hazards that hit and are active now or turn active within ``CPU_HAZARD_LOOKAHEAD``."""
    return [
        hazard
        for hazard in hazards
        if hazard.hits
        and (hazard.phase == "active" or hazard.frames_to_active <= config.CPU_HAZARD_LOOKAHEAD)
    ]


def inside(point: Vec3, zone: HazardView, margin: float) -> bool:
    """Whether ``point`` is in a hazard's cylinder (with ``margin`` around it)."""
    flat = (point.xy - zone.pos.xy).length()
    return (
        flat <= zone.radius + margin
        and zone.pos.z - margin <= point.z <= zone.pos.z + zone.height + margin
    )


def clear_of(point: Vec3, zones: Sequence[HazardView]) -> Vec3 | None:
    """``point`` moved straight out of any danger zone it is in (``None`` if it is in none);
    the height is left for the caller to find ground at."""
    margin = config.CPU_HAZARD_MARGIN
    for zone in zones:
        if not inside(point, zone, margin):
            continue
        away = point.xy - zone.pos.xy
        if away.length() == 0.0:
            away = Vec2(1.0, 0.0)
        out = zone.pos.xy + away.normalized() * (zone.radius + margin + config.CPU_HAZARD_STEP)
        return Vec3(out.x, out.y, point.z)
    return None


def hit_during(
    start: Vec3, offsets: Sequence[tuple[int, Vec3]], zones: Sequence[HazardView]
) -> bool:
    """Whether a path (``start`` plus each ``(frame, offset)``) is inside a hazard that is
    active on that frame. A hazard that is active now is taken to stay so for
    ``frames_left``; one that is coming, from ``frames_to_active`` for
    ``CPU_HAZARD_ACTIVE_GUESS`` frames."""
    for frame, offset in offsets:
        point = start + offset
        for zone in zones:
            if zone.phase == "active":
                live = frame <= zone.frames_left
            else:
                first = zone.frames_to_active
                live = first <= frame <= first + config.CPU_HAZARD_ACTIVE_GUESS
            if live and inside(point, zone, config.CPU_HAZARD_MARGIN):
                return True
    return False
