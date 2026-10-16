"""Which hit pose a fighter shows, and which way its body is turned (decisions D-066, D-067).

Plan note "10 - Animation and Asset Pipeline" (hit animations). As in Melee, what a hit victim
shows follows **whether its hitstun is running**:

- **the freeze:** while a hit's hitlag holds the target (a launch is waiting), ``hurt_impact``;
- **a flinch** (hitstun running, not launched): ``hurt_light_*`` or ``hurt_heavy_*`` by the
  hit's knockback, ``*_front`` or ``*_back`` by the side it came from, timed by the state's
  frames, in the fighter's facing;
- **damage-fly** (hitstun running, launched: airborne with ``FLY_MIN_KB`` or more, or sliding
  on the ground with ``GROUND_FLY_MIN_KB`` or more, and always in the sim's tumble state):
  ``hurt_fly`` for the **whole** hitstun, the body along its current travel, one pose per band
  of elevation (Melee's DamageFly);
- **the tumble** (hitstun over, still in the sim's tumble state): ``tumble``'s twelve poses, a
  head-over-heels turn starting from the last fly pose's body angle and turning
  ``TUMBLE_TURN_DEGREES`` a tick until the fighter acts or lands (Melee's DamageFall). It never
  shows while hitstun runs.

The sim's ``TUMBLE`` state with hitstun left and without it already are Melee's DamageFly and
DamageFall, so none of this needs a sim change.

At the freeze the track also records what the hit's events say (D-067): the **height band** of
the hit point on the victim's hurtbox, the **damage tier**, the **effect**, whether the victim
was **airborne** when hit, and its damage after the hit; on the first tick of the launch it
decides the **reeling roll** (an airborne victim at 100% or more, launched at tumble strength
and not near vertically, about 30% of the time). The chance is a hash of the hit's match frame,
the victim's player index and its damage, so it is the same on every replay and draws nothing
from the sim's random numbers.

Damage-fly and tumble are drawn in the **direction opposite the travel**: the sheets show them
back first (``build/scratch/m16_author_hurt.py`` wrote them so), so a fighter launched by a hit
from the front keeps facing the hit. The heading is the travel snapped to eight ways and kept
while the fighter barely moves.

:class:`HurtMotion` is presentation state, stepped once per sim tick from the fighters
(:meth:`isofightr.render.effects.BattleEffects.observe`); it reads the sim and never writes to
it. Pure Python (no ``arcade``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from isofightr.data.sprite_sheet import AnimInfo
from isofightr.sim.events import Event, HazardHitEvent, HitEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Dir8, facing_from_move
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect

IMPACT_ANIM: Final[str] = "hurt_impact"
FLY_ANIM: Final[str] = "hurt_fly"
TUMBLE_ANIM: Final[str] = "tumble"

HIT_STATES: Final[frozenset[StateId]] = frozenset({StateId.FLINCH, StateId.TUMBLE})
"""The sim states a hit puts its victim in (hitstun runs in both)."""
HEAVY_FLINCH_KNOCKBACK: Final[float] = 40.0
"""A flinch from this much knockback or more is the heavy one."""
FLY_MIN_KB: Final[float] = 32.0
"""An airborne victim launched this hard shows damage-fly for its hitstun (D-067)."""
GROUND_FLY_MIN_KB: Final[float] = 80.0
"""A victim sliding on the ground shows damage-fly from this knockback (the tumble threshold)."""
FLY_ELEVATIONS: Final[tuple[float, ...]] = (90.0, 45.0, 0.0, -45.0, -90.0)
"""The elevation of the travel each ``hurt_fly`` pose is drawn for, in pose order."""
FLY_LOWEST_ELEVATION: Final[float] = -45.0
"""Damage-fly is drawn no steeper downward than this unless the launch itself started steeper
(a spike): the end of a long launch falls nearly straight down, and a head-first dive for half
a second reads wrong."""
FLINCH_FLY_LOWEST_ELEVATION: Final[float] = 0.0
"""A launch under the tumble threshold lands on its feet, into a flinch, so its damage-fly is
never drawn below level (diving head first for the last ticks before standing reads wrong)."""
TUMBLE_POSES: Final[int] = 12
TUMBLE_STEP_DEGREES: Final[float] = 360.0 / TUMBLE_POSES
TUMBLE_TURN_DEGREES: Final[float] = 8.0
"""Degrees a tick the tumble turns once hitstun is over: a turn in 0.75 s (D-067)."""
HEADING_MIN_SPEED: Final[float] = 0.02
"""Units a frame of sideways travel below which the heading is kept as it was."""

HIGH_HIT_SHARE: Final[float] = 0.65
"""A hit point this far up the hurtbox (its share of the height) or higher is a high hit."""
LOW_HIT_SHARE: Final[float] = 0.35
"""A hit point below this share of the hurtbox's height is a low hit."""
WEAK_MAX_DAMAGE: Final[float] = 6.0
"""Damage dealt up to this is a weak hit."""
MEDIUM_MAX_DAMAGE: Final[float] = 12.0
"""Damage dealt up to this (above ``WEAK_MAX_DAMAGE``) is a medium hit; more is heavy."""
ROLL_MIN_KB: Final[float] = 80.0
"""The reeling roll needs a launch of tumble strength..."""
ROLL_MIN_DAMAGE: Final[float] = 100.0
"""... on a victim at this damage or more (after the hit)..."""
ROLL_MAX_ELEVATION: Final[float] = 70.0
"""... launched less steeply than this, up or down..."""
ROLL_CHANCE: Final[float] = 0.3
"""... and it happens to this share of such hits."""


class HitHeight(Enum):
    """Where on the victim's body a hit landed (Melee's DamageHi, DamageN, DamageLw)."""

    HIGH = "high"
    MID = "mid"
    LOW = "low"


class DamageTier(Enum):
    """How hard a hit was by the damage it dealt (Melee's 1 to 3)."""

    WEAK = "weak"
    MEDIUM = "medium"
    HEAVY = "heavy"


def hit_height(fighter: Fighter, point: Vec3) -> HitHeight:
    """Return the height band of a hit at ``point`` on a fighter: the point's height on its
    hurtbox capsule (bottom to top, clamped) against ``HIGH_HIT_SHARE`` and ``LOW_HIT_SHARE``."""
    hurtbox = fighter.character.body.hurtbox
    bottom = fighter.pos.z + hurtbox.z0 - hurtbox.radius
    top = fighter.pos.z + hurtbox.z1 + hurtbox.radius
    share = min(max((point.z - bottom) / (top - bottom), 0.0), 1.0)
    if share >= HIGH_HIT_SHARE:
        return HitHeight.HIGH
    return HitHeight.LOW if share < LOW_HIT_SHARE else HitHeight.MID


def damage_tier(damage: float) -> DamageTier:
    """Return the tier of a hit that dealt ``damage``."""
    if damage <= WEAK_MAX_DAMAGE:
        return DamageTier.WEAK
    return DamageTier.MEDIUM if damage <= MEDIUM_MAX_DAMAGE else DamageTier.HEAVY


_MASK64: Final[int] = (1 << 64) - 1


def _mix64(value: int) -> int:
    """SplitMix64's finaliser: a fixed scramble of 64 bits (not Python's ``hash``, which
    changes from one process to the next)."""
    value = (value + 0x9E3779B97F4A7C15) & _MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
    return value ^ (value >> 31)


def roll_value(frame: int, player_index: int, damage: float) -> float:
    """Return a number in [0, 1) that is a fixed hash of a hit's match frame, the victim's
    player index and its damage after the hit (to a hundredth): the same on every run and
    replay, and nothing drawn from the sim."""
    mixed = _mix64(frame & _MASK64)
    mixed = _mix64(mixed ^ player_index)
    mixed = _mix64(mixed ^ (round(damage * 100.0) & _MASK64))
    return mixed / float(1 << 64)


def rolls(airborne: bool, knockback: float, damage: float, elevation: float, chance: float) -> bool:
    """Return whether a hit sends its victim into the reeling roll (Melee's DamageFlyRoll):
    hit in the air, a tumble-strength launch, at ``ROLL_MIN_DAMAGE`` or more, launched less
    steeply than ``ROLL_MAX_ELEVATION``, and ``chance`` (its :func:`roll_value`) under
    ``ROLL_CHANCE``."""
    return (
        airborne
        and knockback >= ROLL_MIN_KB
        and damage >= ROLL_MIN_DAMAGE
        and abs(elevation) < ROLL_MAX_ELEVATION
        and chance < ROLL_CHANCE
    )


def flinch_anim(knockback: float, behind: bool) -> str:
    """Return the flinch animation for a hit of ``knockback`` from the front or behind."""
    weight = "heavy" if knockback >= HEAVY_FLINCH_KNOCKBACK else "light"
    return f"hurt_{weight}_{'back' if behind else 'front'}"


def fly_pose(elevation: float) -> int:
    """Return the ``hurt_fly`` pose for travel at ``elevation`` degrees (nearest band)."""
    return min(range(len(FLY_ELEVATIONS)), key=lambda i: abs(FLY_ELEVATIONS[i] - elevation))


def tumble_pose(angle: float) -> int:
    """Return the ``tumble`` pose nearest a rotation angle in degrees."""
    return round(angle / TUMBLE_STEP_DEGREES) % TUMBLE_POSES


def body_angle(elevation: float) -> float:
    """Return the turn (degrees about the body's left-right axis, back first) that lays the
    body along travel at ``elevation``: upright going straight up, flat going level."""
    return 90.0 - elevation


@dataclass(slots=True)
class HurtTrack:
    """What one fighter's hit pose depends on beyond the sim's own state."""

    knockback: float = 0.0
    """The last hit's knockback."""
    behind: bool = False
    """Whether the last hit came from behind (it launches the fighter the way it faces)."""
    heading: Dir8 | None = None
    """The sheet direction while flying or tumbling: the opposite of the travel."""
    screen_right: bool = True
    """Whether the travel goes right on screen (which way the placeholder turns)."""
    elevation: float = 0.0
    """Degrees above level of the travel."""
    launch_elevation: float | None = None
    """The travel's elevation on the first tick after the freeze (``None`` until then)."""
    angle: float = 0.0
    """The body's turn about its left-right axis in degrees: the fly pose's while flying, then
    growing while it tumbles."""
    flying: bool = False
    """Hitstun is running and the victim is launched: damage-fly."""
    tumbling: bool = False
    """Hitstun is over and the victim still tumbles."""
    height: HitHeight = HitHeight.MID
    """Where the last hit landed on the body."""
    tier: DamageTier = DamageTier.WEAK
    """How hard the last hit was."""
    effect: Effect = Effect.NORMAL
    """The last hit's effect (electric has a pose of its own)."""
    airborne_hit: bool = False
    """Whether the victim was in the air when the last hit landed."""
    percent: float = 0.0
    """The victim's damage after the last hit."""
    chance: float = 1.0
    """The last hit's :func:`roll_value` (1.0 when no hit event was seen: it never rolls)."""
    rolling: bool = False
    """The launch is the reeling roll, decided on its first tick."""
    frozen: bool = False
    """The fighter was in a hit's freeze last tick."""


class HurtMotion:
    """The hit-pose state of every fighter, stepped once per sim tick."""

    def __init__(self) -> None:
        self.tracks: dict[int, HurtTrack] = {}

    def track(self, player_index: int) -> HurtTrack | None:
        """Return a fighter's track, or ``None`` if it was never stepped."""
        return self.tracks.get(player_index)

    def step(
        self, fighters: Iterable[Fighter], events: Iterable[Event] = (), frame: int = 0
    ) -> None:
        """Follow every fighter one tick. ``events`` are this tick's sim events and ``frame``
        the match frame they happened on: the hits among them describe the freeze."""
        hits = _hits_by_target(events)
        for fighter in fighters:
            track = self.tracks.setdefault(fighter.player_index, HurtTrack())
            hit = hits.get(fighter.player_index)
            frozen = fighter.hitlag > 0 and fighter.launch is not None
            if frozen and hit is not None:
                _record(track, fighter, hit, frame)
            elif frozen and not track.frozen:
                _forget(track, fighter)  # a freeze no event explains: plain defaults
            track.frozen = frozen
            _follow(track, fighter)


type _Hit = HitEvent | HazardHitEvent


def _hits_by_target(events: Iterable[Event]) -> dict[int, list[_Hit]]:
    hits: dict[int, list[_Hit]] = {}
    for event in events:
        if isinstance(event, HitEvent) or (isinstance(event, HazardHitEvent) and not event.blocked):
            hits.setdefault(event.target, []).append(event)
    return hits


def _forget(track: HurtTrack, fighter: Fighter) -> None:
    """Drop the last hit's data: a mid, weak, normal hit that never rolls."""
    track.height = HitHeight.MID
    track.tier = DamageTier.WEAK
    track.effect = Effect.NORMAL
    track.airborne_hit = not fighter.grounded
    track.percent = fighter.damage
    track.chance = 1.0


def _record(track: HurtTrack, fighter: Fighter, hits: list[_Hit], frame: int) -> None:
    """Note what the hit that launches the fighter says about its pose (of several on one tick,
    the last whose knockback is nearest the pending launch's)."""
    launch = fighter.launch
    assert launch is not None
    hit = min(reversed(hits), key=lambda event: abs(event.knockback - launch.knockback))
    track.height = hit_height(fighter, hit.position)
    track.tier = damage_tier(hit.damage)
    track.effect = hit.effect
    track.airborne_hit = not fighter.grounded
    track.percent = fighter.damage
    track.chance = roll_value(frame, fighter.player_index, fighter.damage)


def launched(fighter: Fighter, knockback: float) -> bool:
    """Return whether a victim in hitstun is launched (damage-fly) rather than flinching: in
    the sim's tumble state, airborne with ``FLY_MIN_KB`` or more, or sliding on the ground with
    ``GROUND_FLY_MIN_KB`` or more."""
    if fighter.state is StateId.TUMBLE:
        return True
    least = GROUND_FLY_MIN_KB if fighter.grounded else FLY_MIN_KB
    return knockback >= least


def pose_elevation(track: HurtTrack, fighter: Fighter) -> float:
    """Return the elevation damage-fly is drawn for: the travel's, but no steeper downward than
    ``FLY_LOWEST_ELEVATION`` (``FLINCH_FLY_LOWEST_ELEVATION`` for a launch that will land on
    its feet) unless the launch started steeper (a spike)."""
    tumbling = fighter.state is StateId.TUMBLE
    lowest = FLY_LOWEST_ELEVATION if tumbling else FLINCH_FLY_LOWEST_ELEVATION
    start = track.elevation if track.launch_elevation is None else track.launch_elevation
    return max(track.elevation, min(start, lowest))


def _follow(track: HurtTrack, fighter: Fighter) -> None:
    launch = fighter.launch
    if fighter.hitlag > 0 and launch is not None:
        # The freeze: remember the hit; whatever the body did before starts over.
        track.knockback = launch.knockback
        track.behind = launch.heading.dot(fighter.facing.world) > 0.0
        track.flying = track.tumbling = track.rolling = False
        track.heading = None
        track.launch_elevation = None
        return
    if fighter.state not in HIT_STATES:
        track.flying = track.tumbling = False
        track.heading = None
        return
    travel = fighter.vel + fighter.kb_vel
    sideways = travel.xy
    if sideways.length() >= HEADING_MIN_SPEED:
        track.heading = facing_from_move(-sideways, track.heading)
        track.screen_right = sideways.x - sideways.y > 0.0
    if track.heading is None:
        track.heading = fighter.facing
    track.elevation = math.degrees(math.atan2(travel.z, sideways.length()))
    if track.launch_elevation is None:
        # The launch's first tick (DI is applied by now): decide the reeling roll.
        track.launch_elevation = track.elevation
        track.rolling = fighter.state is StateId.TUMBLE and rolls(
            track.airborne_hit, track.knockback, track.percent, track.elevation, track.chance
        )
    if fighter.hitstun > 0:
        # Hitstun: damage-fly while launched, never the tumble.
        track.tumbling = False
        track.flying = launched(fighter, track.knockback)
        if track.flying:
            track.angle = body_angle(FLY_ELEVATIONS[fly_pose(pose_elevation(track, fighter))])
        return
    if fighter.state is not StateId.TUMBLE:
        track.flying = track.tumbling = False
        return
    # Hitstun is over and the fighter still tumbles: turn on from the last fly pose.
    if track.tumbling:
        track.angle += TUMBLE_TURN_DEGREES
    elif not track.flying:
        track.angle = body_angle(pose_elevation(track, fighter))
    track.flying = False
    track.tumbling = True


@dataclass(frozen=True, slots=True)
class HurtChoice:
    """A hit pose to draw instead of the state's own animation."""

    anim: str
    pose: int
    direction: Dir8 | None
    """The sheet direction, or ``None`` for the fighter's facing."""


def hurt_choice(
    fighter: Fighter, track: HurtTrack | None, anims: Mapping[str, AnimInfo]
) -> HurtChoice | None:
    """Return the hit pose a fighter shows, or ``None`` to show its state's own animation
    (no track, not hurt, or the character has no such animation)."""
    if track is None:
        return None
    if fighter.hitlag > 0 and fighter.launch is not None:
        return HurtChoice(IMPACT_ANIM, 0, None) if IMPACT_ANIM in anims else None
    if fighter.state not in HIT_STATES:
        return None
    if track.flying and FLY_ANIM in anims:
        return HurtChoice(FLY_ANIM, fly_pose(pose_elevation(track, fighter)), track.heading)
    if fighter.state is StateId.FLINCH:
        name = flinch_anim(track.knockback, track.behind)
        info = anims.get(name)
        return None if info is None else HurtChoice(name, info.pose_at(fighter.state_frame), None)
    if track.tumbling and TUMBLE_ANIM in anims and anims[TUMBLE_ANIM].poses == TUMBLE_POSES:
        return HurtChoice(TUMBLE_ANIM, tumble_pose(track.angle), track.heading)
    return None


def placeholder_spin(fighter: Fighter, track: HurtTrack | None) -> int:
    """Return the degrees (counterclockwise on screen) the placeholder capsule of a flying or
    tumbling fighter is turned: its pitch, snapped to the tumble's steps, the top moving the
    way the fighter travels on screen."""
    if track is None or fighter.state not in HIT_STATES or fighter.hitlag > 0:
        return 0
    if not (track.flying or track.tumbling):
        return 0
    step = tumble_pose(track.angle) * round(TUMBLE_STEP_DEGREES)
    return -step if track.screen_right else step
