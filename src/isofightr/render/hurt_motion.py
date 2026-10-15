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
from typing import Final

from isofightr.data.sprite_sheet import AnimInfo
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Dir8, facing_from_move

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


class HurtMotion:
    """The hit-pose state of every fighter, stepped once per sim tick."""

    def __init__(self) -> None:
        self.tracks: dict[int, HurtTrack] = {}

    def track(self, player_index: int) -> HurtTrack | None:
        """Return a fighter's track, or ``None`` if it was never stepped."""
        return self.tracks.get(player_index)

    def step(self, fighters: Iterable[Fighter]) -> None:
        """Follow every fighter one tick."""
        for fighter in fighters:
            track = self.tracks.setdefault(fighter.player_index, HurtTrack())
            _follow(track, fighter)


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
        track.flying = track.tumbling = False
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
        track.launch_elevation = track.elevation
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
