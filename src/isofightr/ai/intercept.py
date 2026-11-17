"""The intercept search and what a candidate is worth (decision D-071).

Plan note "15 - CPU AI" ("Intercept search" and "Expected value"). The M10 CPU asked of each
move "started right here and now, does it overlap where the target will be on a straight
line?" and took the hardest hit that did. Two things are different here.

**What is searched.** Every recorded action is a candidate, and so is every *approach* (a run
or a walk with a move at its end, :attr:`CharacterKnowledge.approaches`) and every *extra*
(jab chains, charged smashes), each tested frame by frame against a predicted
:class:`~isofightr.ai.predict.Track` of the target, not a straight line. A track knows how
sure it is: a target that cannot act is exactly where the track says, a free one is somewhere
in a disc. So a candidate does not just reach or not: it has a **chance**.

**What it is worth.** One formula for every candidate::

    value = P(hit) x gain - P(blocked) x block cost - P(whiff) x whiff cost - other risks

``gain`` is the damage, a KO if the forecast says so, and the frame advantage the hit leaves.
The costs are what the opponent can do with the frames a blocked or missed move hands it,
scaled by the CPU's caution. A slow move thrown at a free opponent standing in its own reach
also risks being hit first. Nothing here is a dice roll: the CPU picks among the candidates
afterwards (:func:`choose`).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from isofightr import config
from isofightr.ai import forecast
from isofightr.ai.knowledge import Action, CharacterKnowledge, Outcome, Start
from isofightr.ai.predict import Track
from isofightr.ai.view import FighterView
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import constants as combat
from isofightr.sim.combat.shield import shield_damage
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import facing_from_move
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import Stage

LOOKAHEAD: Final[int] = 70
"""Hit frames later than this are not counted on."""
DRIFT_LIMIT: Final[int] = 30
"""An airborne attacker's own drift is extended at most this many frames."""
SHIELDING: Final[frozenset[StateId]] = frozenset(
    {StateId.SHIELD, StateId.SHIELD_STUN, StateId.SHIELD_DROP}
)
OWN_MOTION: Final[float] = 1.0
"""An air action whose recording travels further than this moves by itself."""
GRAB_ADVANTAGE: Final[int] = 12
"""Frames a landed grab is counted as being ahead by (a throw follows)."""


@dataclass(frozen=True, slots=True)
class Reading:
    """What the CPU reads off the situation once, for all candidates of a decision."""

    stage: Stage
    me: FighterView
    target: FighterView
    """The target as believed."""
    track: Track
    character: CharacterDef
    """The target's character."""
    theirs: CharacterKnowledge
    """The target's move knowledge: how fast and how far it can hit back."""
    caution: float = 1.0
    """Multiplier on every cost (above 1 when the CPU has more to lose)."""
    urge: float = 0.0
    passive: float = 0.0
    """0 to 1: how long the target has gone without attacking, against the CPU's patience."""
    """Value added to a likely hit after a long wait (impatience)."""
    guard: float = config.CPU_GUARD_GUESS
    """How likely a free, grounded target is to block."""
    threat_frames: int = 0
    """Frames until a hit the CPU already sees coming lands on it (0 = none)."""
    mine: CharacterKnowledge | None = None
    """The CPU's own move knowledge (how far it can strike to follow a hit up)."""
    their_action: Action | None = None
    """The recording of the move the target is performing, if it is in one."""
    their_frame: int = 0
    """How far into that recording it is."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """An action that could connect, and what the CPU makes of it."""

    action: Action
    aim: Vec2
    """The way it would be performed (a unit world direction, one of eight)."""
    frame: int
    """The action frame it is expected to connect on."""
    chance: float
    """How likely it is to reach the target at all (hit or blocked)."""
    value: float
    kills: bool = False
    hit: float = 0.0
    """The part of ``chance`` that is a clean hit."""


def _rotate(local: Vec3, forward: Vec2) -> Vec3:
    left = forward.perpendicular_left()
    return Vec3(
        local.x * forward.x + local.y * left.x, local.x * forward.y + local.y * left.y, local.z
    )


def aim_for(me: FighterView, action: Action, point: Vec3) -> Vec2:
    """The facing an action would be performed with: toward ``point`` for one that turns
    (snapped to the eight ways a fighter faces), the current facing otherwise."""
    if not action.turns:
        return me.facing.world
    toward = point.xy - me.pos.xy
    facing = facing_from_move(toward.normalized()) if toward.length() > 0.0 else None
    return (facing or me.facing).world


_FLAT: dict[int, tuple[Action, tuple[tuple[int, tuple[tuple[float, ...], ...]], ...]]] = {}
"""Each action's spheres as plain numbers, per hit frame: (x, y, z, radius, grab, projectile).
The search runs many times a second, and vector objects were most of its cost."""


def _flat(action: Action) -> tuple[tuple[int, tuple[tuple[float, ...], ...]], ...]:
    cached = _FLAT.get(id(action))
    if cached is not None and cached[0] is action:
        return cached[1]
    frames = tuple(
        (
            hit_frame.frame,
            tuple(
                (
                    sphere.centre.x,
                    sphere.centre.y,
                    sphere.centre.z,
                    sphere.radius,
                    1.0 if sphere.grab else 0.0,
                    1.0 if sphere.projectile else 0.0,
                )
                for sphere in hit_frame.spheres
            ),
        )
        for hit_frame in action.hit_frames
    )
    _FLAT[id(action)] = (action, frames)
    return frames


def connect(
    me: FighterView, target: FighterView, action: Action, aim: Vec2, track: Track
) -> tuple[int, float]:
    """The action frame on which ``action`` best reaches the target and the chance that it
    does: (0, 0.0) if it never comes near. A frame on which the target cannot have moved
    counts in full; later, the overlap is weighed against how far the target may have gone."""
    box = target.hurtbox
    hurt = box.radius
    bottom, top = box.z0 + hurt, box.z1 - hurt
    air = action.start is Start.AIR
    grounded = target.grounded
    fx, fy = aim.x, aim.y
    mx, my, mz = me.pos.x, me.pos.y, me.pos.z
    # A move that carries the fighter itself (a lunge, a recovery) ignores its drift.
    air = air and action.travel <= OWN_MOTION
    vx, vy, vz = (me.vel.x, me.vel.y, me.vel.z) if air else (0.0, 0.0, 0.0)
    safe_until = target.intangible_left
    points, spreads = track.points, track.spread
    last = len(points) - 1
    margin = config.CPU_REACH_MARGIN
    mobility = config.CPU_TARGET_MOBILITY
    best_frame, best = 0, 0.0
    for frame, spheres in _flat(action):
        if frame > LOOKAHEAD:
            break
        if frame <= safe_until:
            continue  # it would pass straight through
        index = min(frame - 1, last)
        feet = points[index]
        tx, ty = feet.x, feet.y
        low, high = feet.z + bottom, feet.z + top
        drift = float(min(frame, DRIFT_LIMIT))
        deepest = -1.0
        for x, y, z, radius, grab, projectile in spheres:
            if grab and not grounded:
                continue
            # Local (forward, left, up) to world: left of (fx, fy) is (-fy, fx).
            cx = mx + x * fx - y * fy
            cy = my + x * fy + y * fx
            cz = mz + z
            if air and not projectile:
                cx += vx * drift
                cy += vy * drift
                cz += vz * drift
            dz = cz - (low if cz < low else high if cz > high else cz)
            dx, dy = cx - tx, cy - ty
            overlap = radius + hurt - (dx * dx + dy * dy + dz * dz) ** 0.5
            if overlap > deepest:
                deepest = overlap
        if deepest <= margin:
            continue
        loose = spreads[index] * mobility
        chance = 1.0 if loose <= deepest else deepest / loose
        if chance > best + 0.05:
            best_frame, best = frame, chance
            if best >= 1.0:
                break
    return best_frame, best


def danger(reading: Reading, action: Action, aim: Vec2, upto: int) -> int:
    """The first frame, counted from now, on which the move the target is performing would
    hit the CPU **as it performs** ``action`` (its feet follow the action's path), or 0 if it
    does not by ``upto``. A run-up straight into a swing that is already coming is how a CPU
    gets hit out of its own moves."""
    theirs = reading.their_action
    if theirs is None:
        return 0
    me, target = reading.me, reading.target
    box = me.hurtbox
    hurt = box.radius
    bottom, top = box.z0 + hurt, box.z1 - hurt
    now = reading.their_frame
    here = theirs.offset_at(now)
    forward = target.facing.world
    tx, ty, tz = target.pos.x, target.pos.y, target.pos.z
    fx, fy = forward.x, forward.y
    for frame, spheres in _flat(theirs):
        ahead = frame - now
        if ahead <= 0:
            continue
        if ahead > upto:
            break
        step = action.offset_at(ahead)
        mx = me.pos.x + step.x * aim.x - step.y * aim.y
        my = me.pos.y + step.x * aim.y + step.y * aim.x
        mz = me.pos.z + step.z
        low, high = mz + bottom, mz + top
        for x, y, z, radius, grab, _projectile in spheres:
            if grab:
                continue
            lx, ly = x - here.x, y - here.y
            cx = tx + lx * fx - ly * fy
            cy = ty + lx * fy + ly * fx
            cz = tz + z - here.z
            dz = cz - (low if cz < low else high if cz > high else cz)
            dx, dy = cx - mx, cy - my
            if (dx * dx + dy * dy + dz * dz) ** 0.5 <= radius + hurt:
                return ahead
    return 0


def _strike(action: Action, frame: int) -> tuple[Outcome | None, float, int]:
    """The hitbox that decides the launch, the damage the whole action deals once it
    connects on ``frame``, and the frame its last hit lands on. A chain or a multi-hit adds
    up; hitboxes that share a frame are alternatives, so only the strongest counts."""
    own = [o for o in action.outcomes if o.projectile == action.projectile and o.frame >= frame]
    if not own:
        own = [o for o in action.outcomes if o.frame <= frame][-1:]
    if not own:
        return None, action.damage, frame
    by_frame: dict[int, Outcome] = {}
    for outcome in own:
        kept = by_frame.get(outcome.frame)
        if kept is None or outcome.box.damage > kept.box.damage:
            by_frame[outcome.frame] = outcome
    total = sum(outcome.box.damage for outcome in by_frame.values())
    last = by_frame[max(by_frame)]
    return last, total * forecast.FRESH * action.charge, max(max(by_frame), frame)


def _punish(frames: float) -> float:
    """What handing an opponent ``frames`` to act in is worth to it, in percent."""
    if frames <= 0:
        return 0.0
    return config.CPU_PUNISH_VALUE * min(frames / config.CPU_PUNISH_FRAMES, 1.0)


def weigh(reading: Reading, action: Action, aim: Vec2, frame: int, chance: float) -> Candidate:
    """Put a value on a candidate that reaches the target with ``chance`` on ``frame``."""
    me, target = reading.me, reading.target
    outcome, damage, last = _strike(action, frame)
    remaining = action.remaining(last)
    feet, _spread = reading.track.at(frame)
    kills = False
    if action.grab or outcome is None:
        advantage = GRAB_ADVANTAGE
    else:
        box = outcome.box
        weight = reading.character.weight
        centre = me.pos + Vec3(aim.x, aim.y, 0.0)
        heading = forecast.hit_heading(box, aim, centre, feet)
        final = box.damage * forecast.FRESH * action.charge
        before = target.damage + damage - final  # the earlier hits of a chain land first
        launch = forecast.hit_launch(box, final, before, weight, target.grounded, heading)
        advantage = forecast.advantage_on_hit(launch.knockback, remaining)
        flown = None
        if launch.knockback >= combat.TUMBLE_KB or advantage > 0:
            flown = forecast.flight(reading.stage, launch, feet, target.grounded, reading.character)
            kills = launch.knockback >= combat.TUMBLE_KB and flown.ko
        if advantage > 0 and flown is not None:
            # Frames ahead only set up a next hit if the victim is still within reach when
            # the CPU can act: a strong launch sends it far away, however long its hitstun.
            mine = reading.mine
            end = me.pos + _rotate(action.offset_at(action.commit), aim)
            there = flown.at(remaining)
            reach = (mine.strike_reach if mine is not None else 0.0) + config.CPU_FOLLOW_SLACK
            if flown.ko or (there.xy - end.xy).length() > reach:
                advantage = 0
    gain = damage + config.CPU_HIT_VALUE
    # Frames ahead on hit set up the next hit (a combo starter); frames behind are only risk.
    ahead = config.CPU_STARTER_VALUE if advantage > 0 else config.CPU_ADVANTAGE_VALUE
    gain += max(-15, min(advantage, 15)) * ahead
    if kills:
        gain += config.CPU_KO_VALUE

    # How the reach splits into a clean hit and a block.
    locked = reading.track.sure(frame)
    if action.grab:
        hit, blocked = chance, 0.0
    elif target.state in SHIELDING and locked:
        hit, blocked = 0.0, chance
    elif target.state in SHIELDING:
        hit, blocked = chance * 0.3, chance * 0.7
    elif locked or not target.grounded:
        hit, blocked = chance, 0.0
    else:
        blocked = chance * reading.guard
        hit = chance - blocked
    whiff = 1.0 - chance

    theirs = reading.theirs
    reply = max(theirs.fastest_hit, 1)
    on_shield = forecast.advantage_on_shield(damage, remaining, action.projectile)
    block_cost = _punish(-on_shield - reply)
    distance = (feet.xy - me.pos.xy).length()
    near = max(0.0, min(1.0, 1.5 - (distance - theirs.threat_reach) / 3.0))
    whiff_cost = _punish(action.commit - last - reply) * near
    # A slow move started inside a free opponent's own reach may simply be hit first: then
    # it gains nothing and the CPU takes the hit instead.
    beaten = 0.0
    closest = min(distance, (target.pos.xy - me.pos.xy).length())
    if not locked and closest <= theirs.strike_reach + config.CPU_STUFF_REACH:
        late = (frame - reply) / config.CPU_STUFF_FRAMES
        beaten = config.CPU_STUFF_GUESS * max(0.0, min(late, 1.0))
        beaten *= 1.0 - config.CPU_PASSIVE_DISCOUNT * reading.passive
    if reading.threat_frames and frame >= reading.threat_frames:
        beaten = 1.0  # something already on its way lands first
    elif danger(reading, action, aim, frame):
        beaten = 1.0  # the CPU would carry itself into the swing
    if blocked > 0.0 and shield_damage(damage) >= target.shield_hp > 0.0:
        # This block breaks the shield: as good as a hit, better.
        hit, blocked = hit + blocked, 0.0
        gain += config.CPU_SHIELD_BREAK_VALUE
    outcome_value = hit * gain - (blocked * block_cost + whiff * whiff_cost) * reading.caution
    value = (1.0 - beaten) * outcome_value - beaten * config.CPU_PUNISH_VALUE * reading.caution
    value += reading.urge * chance - frame * config.CPU_TIME_COST
    return Candidate(action, aim, frame, chance, value, kills, hit)


def search(
    reading: Reading,
    actions: Iterable[Action],
    allowed: Callable[[Action, Vec2], bool],
) -> list[Candidate]:
    """Every action that could reach the target, each with its chance and value.
    ``allowed(action, aim)`` is the caller's veto (an action that would carry the CPU off
    the stage, for one)."""
    me, target, track = reading.me, reading.target, reading.track
    start = Start.GROUND if me.grounded else Start.AIR
    hurt = target.hurtbox.radius
    found: list[Candidate] = []
    for action in actions:
        if action.start is not start or not action.hit_frames:
            continue
        if action.grab and not target.grounded:
            continue
        first = min(action.first_hit, LOOKAHEAD)
        feet, spread = track.at(first)
        if not action.projectile and action.envelope is not None:
            gap = (feet.xy - me.pos.xy).length() - spread - hurt
            if gap > action.envelope.radius + (me.vel.length() * first if not me.grounded else 0.0):
                continue  # out of reach whatever happens: the cheap test most actions fail
        aim = aim_for(me, action, feet)
        frame, chance = connect(me, target, action, aim, track)
        least = config.CPU_PROJECTILE_MIN_CHANCE if action.projectile else config.CPU_MIN_CHANCE
        if chance < least or not allowed(action, aim):
            continue
        found.append(weigh(reading, action, aim, frame, chance))
    return found


def choose(found: Sequence[Candidate], temperature: float, roll: float) -> Candidate | None:
    """Pick among the candidates worth doing (value above ``CPU_ACT_VALUE``): the best one
    most of the time, a worse one more often the higher the ``temperature``. ``roll`` is a
    uniform random number from the CPU's own dice."""
    worth = sorted((c for c in found if c.value > config.CPU_ACT_VALUE), key=lambda c: -c.value)
    if not worth:
        return None
    top = max(c.value for c in worth)
    scale = max(temperature, 1e-6)
    weights = [2.718281828 ** ((c.value - top) / scale) for c in worth]
    mark = roll * sum(weights)
    for candidate, weight in zip(worth, weights, strict=True):
        if mark < weight:
            return candidate
        mark -= weight
    return worth[0]
