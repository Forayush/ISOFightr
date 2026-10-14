"""Which hit pose a fighter shows, and which way its body is turned (decision D-066).

Plan note "10 - Animation and Asset Pipeline" (hit animations). A hit is drawn in four parts:

- **the freeze:** while a hit's hitlag holds the target (a launch is waiting), ``hurt_impact``;
- **a flinch** (knockback under the tumble threshold): ``hurt_light_*`` or ``hurt_heavy_*`` by
  the hit's knockback, ``*_front`` or ``*_back`` by the side it came from, timed by the state's
  frames, in the fighter's facing;
- **damage-fly:** a strong launch (``FLY_MIN_KNOCKBACK``) first shows ``hurt_fly``, the body
  along its trajectory, one pose per band of elevation, while the knockback is still strong;
- **the tumble:** ``tumble``'s twelve poses are a head-over-heels turn, picked by a rotation
  angle that grows each tick by a rate following the knockback's speed: fast at the start (a
  turn in about half a second), slow as it runs out (about 1.2 s). When hitstun ends the body
  turns on to upright and shows ``fall``.

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
from isofightr.sim.combat import knockback as kb
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Dir8, facing_from_move

IMPACT_ANIM: Final[str] = "hurt_impact"
FLY_ANIM: Final[str] = "hurt_fly"
TUMBLE_ANIM: Final[str] = "tumble"
SETTLED_ANIM: Final[str] = "fall"

HEAVY_FLINCH_KNOCKBACK: Final[float] = 40.0
"""A flinch from this much knockback or more is the heavy one."""
FLY_MIN_KNOCKBACK: Final[float] = 110.0
"""A launch this strong shows damage-fly before it tumbles."""
FLY_UNTIL_SHARE: Final[float] = 0.55
"""Damage-fly lasts while the knockback's speed is at least this share of its launch speed."""
FLY_ELEVATIONS: Final[tuple[float, ...]] = (90.0, 45.0, 0.0, -45.0, -90.0)
"""The elevation of the travel each ``hurt_fly`` pose is drawn for, in pose order."""
TUMBLE_POSES: Final[int] = 12
TUMBLE_STEP_DEGREES: Final[float] = 360.0 / TUMBLE_POSES
TURN_FAST_DEGREES: Final[float] = 12.0
"""Degrees a tick at launch speed: a turn in half a second."""
TURN_SLOW_DEGREES: Final[float] = 5.0
"""Degrees a tick once the knockback has run out: a turn in 1.2 seconds."""
SETTLE_DEGREES: Final[float] = 15.0
"""Degrees a tick while the body turns on to upright after hitstun."""
HEADING_MIN_SPEED: Final[float] = 0.02
"""Units a frame of sideways travel below which the heading is kept as it was."""
FULL_TURN: Final[float] = 360.0


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


def turn_rate(speed: float, launch_speed: float) -> float:
    """Return the degrees a tumbling body turns this tick: from ``TURN_FAST_DEGREES`` at its
    launch speed down to ``TURN_SLOW_DEGREES`` when the knockback has run out."""
    share = 0.0 if launch_speed <= 0.0 else min(speed / launch_speed, 1.0)
    return TURN_SLOW_DEGREES + (TURN_FAST_DEGREES - TURN_SLOW_DEGREES) * share


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
    launch_speed: float = 0.0
    heading: Dir8 | None = None
    """The sheet direction while flying or tumbling: the opposite of the travel."""
    screen_right: bool = True
    """Whether the travel goes right on screen (which way the placeholder turns)."""
    elevation: float = 0.0
    """Degrees above level of the travel."""
    angle: float = 0.0
    """The tumbling body's turn, in degrees; grows while it tumbles."""
    flying: bool = False
    tumbling: bool = False
    settled: bool = False
    """Hitstun is over and the body has turned upright: show ``fall``."""


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


def _follow(track: HurtTrack, fighter: Fighter) -> None:
    launch = fighter.launch
    if fighter.hitlag > 0 and launch is not None:
        # The freeze: remember the hit; whatever the body did before starts over.
        track.knockback = launch.knockback
        track.behind = launch.heading.dot(fighter.facing.world) > 0.0
        track.launch_speed = kb.launch_speed(launch.knockback)
        track.flying = track.tumbling = track.settled = False
        track.heading = None
        return
    if fighter.state is not StateId.TUMBLE:
        track.flying = track.tumbling = track.settled = False
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
    speed = fighter.kb_vel.length()
    first = not (track.flying or track.tumbling or track.settled)
    if first and track.knockback >= FLY_MIN_KNOCKBACK and fighter.hitstun > 0:
        track.flying = True
    if track.flying and (speed < FLY_UNTIL_SHARE * track.launch_speed or fighter.hitstun <= 0):
        track.flying = False
        track.tumbling = True
        track.angle = body_angle(FLY_ELEVATIONS[fly_pose(track.elevation)])
        return
    if track.flying:
        return
    if not track.tumbling and not track.settled:
        track.tumbling = True
        track.angle = body_angle(track.elevation)
    if track.settled:
        return
    if fighter.hitstun > 0:
        track.angle += turn_rate(speed, track.launch_speed)
        return
    # Free to act: turn on to the next upright, then fall.
    upright = math.ceil(track.angle / FULL_TURN) * FULL_TURN
    track.angle = min(track.angle + SETTLE_DEGREES, upright)
    if track.angle >= upright:
        track.settled = True
        track.tumbling = False


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
    if fighter.state is StateId.FLINCH:
        name = flinch_anim(track.knockback, track.behind)
        info = anims.get(name)
        return None if info is None else HurtChoice(name, info.pose_at(fighter.state_frame), None)
    if fighter.state is not StateId.TUMBLE:
        return None
    if track.flying and FLY_ANIM in anims:
        return HurtChoice(FLY_ANIM, fly_pose(track.elevation), track.heading)
    if track.settled and SETTLED_ANIM in anims:
        info = anims[SETTLED_ANIM]
        return HurtChoice(SETTLED_ANIM, info.pose_at(fighter.state_frame), None)
    if track.tumbling and TUMBLE_ANIM in anims and anims[TUMBLE_ANIM].poses == TUMBLE_POSES:
        return HurtChoice(TUMBLE_ANIM, tumble_pose(track.angle), track.heading)
    return None


def placeholder_spin(fighter: Fighter, track: HurtTrack | None) -> int:
    """Return the degrees (counterclockwise on screen) the placeholder capsule of a tumbling
    fighter is turned: its pitch, snapped to the tumble's steps, the top moving the way the
    fighter travels on screen."""
    if track is None or fighter.state is not StateId.TUMBLE or not track.tumbling:
        return 0
    step = tumble_pose(track.angle) * round(TUMBLE_STEP_DEGREES)
    return -step if track.screen_right else step
