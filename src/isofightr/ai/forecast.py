"""What a hit or a block leads to, worked out with the sim's own formulas (decision D-071).

Plan note "15 - CPU AI" ("Forecast: pure arithmetic, no rollouts"). A CPU must know more
than "this move reaches": how hard it launches, where the victim flies, whether that is a
KO, and who can act first afterwards, on hit and on shield. Nothing here steps or copies a
match. Each function repeats arithmetic the sim does (``sim/combat/knockback.py``, the launch
in ``hit_resolution._launch``, knockback decay and hitstun gravity in ``physics``), the way
``render/ko_forecast.py`` does for the hit splash, and ``tests/test_cpu_forecast.py`` holds
them to the real sim: flights frame by frame, KO percents against ``sim/kill_calc.py``, and
advantage against ``sim/combo_scan.py``.

What it leaves out, knowingly: the victim's air drift and SDI, walls (a flight that would
bounce off one is flown straight on), stage mechanics, and anything hitting the victim on the
way.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import constants as combat
from isofightr.sim.combat.knockback import (
    apply_di,
    hitstun_frames,
    is_tumble,
    knockback,
    launch_speed,
    launch_vector,
    meteor_tumbles,
    resolve_elevation,
)
from isofightr.sim.combat.shield import shieldstun_frames
from isofightr.sim.fighter import Launch
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_NONE, VERTICAL_UP
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3
from isofightr.sim.move_def import DirectionMode, HitboxDef
from isofightr.sim.stage import Stage

FLIGHT_FRAMES: Final[int] = 240
"""The longest flight forecast: a launch still airborne by then does not count as a KO."""
SETTLED_SPEED: Final[float] = 0.05
"""Out of hitstun with its knockback slower than this, a fighter has stopped being carried."""
GROUND_GRACE_FRAMES: Final[int] = 1
"""A launch from the ground starts on it: it only counts as coming down after this frame."""
FRESH: Final[float] = combat.FRESH_BONUS
"""Damage multiplier of a move that is not stale: what a forecast assumes."""


@dataclass(frozen=True, slots=True)
class Flight:
    """Where a launched fighter goes, frame by frame, until it is free, lands or is gone."""

    path: tuple[Vec3, ...]
    """Its position after each frame (index 0 = the first frame after the launch)."""
    hitstun: int
    """Frames it cannot act for."""
    ko_frame: int
    """The frame it leaves the blast zone in a way that counts as a KO, or 0."""
    land_frame: int
    """The frame it comes down onto ground, or 0 if it does not within the path."""

    @property
    def ko(self) -> bool:
        """Whether the launch KOs."""
        return self.ko_frame > 0

    def at(self, frame: int) -> Vec3:
        """Its position ``frame`` frames after the launch (clamped to the path)."""
        return self.path[min(max(frame, 1), len(self.path)) - 1]

    @property
    def end(self) -> Vec3:
        """Where the path stops."""
        return self.path[-1]


# --- a hit's numbers -------------------------------------------------------------------------


def hit_knockback(
    box: HitboxDef, damage: float, percent_before: float, weight: float, rate: float = 1.0
) -> float:
    """The knockback of ``box`` dealing ``damage`` to a fighter at ``percent_before``."""
    after = min(percent_before + damage, combat.MAX_DAMAGE)
    return knockback(after, damage, weight, box.bkb, box.kbg, box.fkb, rate)


def hit_heading(box: HitboxDef, facing: Vec2, centre: Vec3, target: Vec3) -> Vec2:
    """The horizontal launch direction of a hit, before DI (``hit_resolution._heading``).
    ``centre`` is the hitbox's centre and ``target`` the victim's feet, in world space."""
    if box.direction_mode is DirectionMode.RADIAL:
        away = (target - centre).xy.normalized()
        return facing if away == ZERO2 else away
    if box.direction_mode is DirectionMode.AUTOLINK:
        toward = (centre.xy - target.xy).normalized()
        return facing if toward == ZERO2 else toward
    return facing.rotated(box.yaw)


def hit_launch(
    box: HitboxDef,
    damage: float,
    percent_before: float,
    weight: float,
    grounded: bool,
    heading: Vec2,
    rate: float = 1.0,
) -> Launch:
    """The launch a hit queues on its victim (``hit_resolution.strike``)."""
    kb = hit_knockback(box, damage, percent_before, weight, rate)
    return Launch(
        knockback=kb,
        heading=heading,
        elevation=resolve_elevation(box.angle, kb, grounded),
        tumble=is_tumble(kb) or meteor_tumbles(box.angle, kb, grounded),
    )


def advantage_on_hit(kb: float, remaining: int) -> int:
    """Frames the attacker can act before its victim can, after a hit of knockback ``kb``
    with ``remaining`` frames of its move left once the hit lands (hitlag freezes both, so
    it cancels out). Positive: a follow-up is possible."""
    return hitstun_frames(kb) - remaining


def advantage_on_shield(damage: float, remaining: int, projectile: bool = False) -> int:
    """The same after a blocked hit: shieldstun against what is left of the move. The
    defender then still has to drop its shield (``SHIELD_DROP_FRAMES``) unless it acts out of
    it, so compare this with the start-up of what it can do out of shield. Negative: the
    defender moves first."""
    stun = shieldstun_frames(damage)
    if projectile:
        stun = int(stun * combat.PROJECTILE_SHIELDSTUN_MULT)
    return stun - remaining


# --- the flight ------------------------------------------------------------------------------


def flight(
    stage: Stage,
    launch: Launch,
    start: Vec3,
    grounded: bool,
    character: CharacterDef,
    stick: Vec2 = ZERO2,
    vertical: int = VERTICAL_NONE,
) -> Flight:
    """Fly a launch the way the sim will: DI applied at the launch, gravity times
    ``HITSTUN_GRAVITY_MULT`` while stunned, the knockback losing ``KB_DECAY`` a frame (and the
    victim's traction on the ground), until it leaves the blast zone, comes down, or is free
    and no longer carried. ``stage`` is the stage as it is now."""
    heading, elevation = apply_di(launch.heading, launch.elevation, stick, vertical)
    if grounded and elevation < 0.0:
        elevation = 0.0
    carried = launch_vector(heading, elevation) * launch_speed(launch.knockback) + launch.carry
    return coast(stage, start, carried, 0.0, hitstun_frames(launch.knockback), grounded, character)


def coast(
    stage: Stage,
    start: Vec3,
    carried: Vec3,
    fall: float,
    stunned_for: int,
    grounded: bool,
    character: CharacterDef,
) -> Flight:
    """Carry on a flight already under way: ``carried`` is the knockback velocity it has
    now, ``fall`` its own vertical speed (negative going down), ``stunned_for`` the hitstun it
    has left. :func:`flight` is this from the moment of the launch."""
    movement = character.movement
    sliding = grounded and carried.z <= 0.0
    zone = stage.blast_zone
    position = start
    path: list[Vec3] = []
    ko_frame = land_frame = 0
    for frame in range(1, FLIGHT_FRAMES + 1):
        stunned = frame <= stunned_for
        speed = carried.length()
        if sliding:
            loss = combat.KB_DECAY + movement.traction * combat.KB_TRACTION_MULT
            carried = ZERO3 if speed <= loss else carried * ((speed - loss) / speed)
            step = Vec3(carried.x, carried.y, 0.0)
            ahead = position + step
            if stage.surface_top(ahead.x, ahead.y) is not None:
                position = ahead
                path.append(position)
                if not stunned or carried == ZERO3:
                    break
                continue
            sliding = False  # slid off the edge: it falls from here
        elif speed > 0.0:
            carried = (
                ZERO3 if speed <= combat.KB_DECAY else carried * ((speed - combat.KB_DECAY) / speed)
            )
        scale = combat.HITSTUN_GRAVITY_MULT if stunned else 1.0
        fall = max(fall - movement.gravity * scale, -movement.max_fall * scale)
        position = position + carried + Vec3(0.0, 0.0, fall)
        path.append(position)
        if not zone.contains(position):
            if stunned or position.z >= zone.z_min:
                ko_frame = frame
            break
        top = stage.surface_top(position.x, position.y)
        coming_down = carried.z + fall < 0.0
        past_start = frame > GROUND_GRACE_FRAMES + 1
        if past_start and coming_down and top is not None and position.z <= top:
            path[-1] = Vec3(position.x, position.y, top)
            land_frame = frame
            break
        if not stunned and carried.length() < SETTLED_SPEED:
            break
    return Flight(tuple(path), stunned_for, ko_frame, land_frame)


def kills(
    stage: Stage, launch: Launch, start: Vec3, grounded: bool, character: CharacterDef
) -> bool:
    """Whether a launch KOs with no DI."""
    if launch.knockback < combat.TUMBLE_KB:
        return False
    return flight(stage, launch, start, grounded, character).ko


DI_CHOICES: Final[tuple[tuple[float, int], ...]] = (
    (0.0, VERTICAL_NONE),
    (1.0, VERTICAL_NONE),
    (-1.0, VERTICAL_NONE),
    (0.0, VERTICAL_DOWN),
    (0.0, VERTICAL_UP),
    (1.0, VERTICAL_DOWN),
    (-1.0, VERTICAL_DOWN),
    (1.0, VERTICAL_UP),
    (-1.0, VERTICAL_UP),
)
"""The DI a victim can hold: the stick across the launch to either side, and a modifier."""


def di_flights(
    stage: Stage, launch: Launch, start: Vec3, grounded: bool, character: CharacterDef
) -> list[tuple[Vec2, int, Flight]]:
    """The flight for each DI choice: (stick, modifier, flight)."""
    across = launch.heading.perpendicular_left()
    out = []
    for side, vertical in DI_CHOICES:
        stick = across * side
        out.append(
            (stick, vertical, flight(stage, launch, start, grounded, character, stick, vertical))
        )
    return out


def kills_through_di(
    stage: Stage, launch: Launch, start: Vec3, grounded: bool, character: CharacterDef
) -> bool:
    """Whether a launch KOs whatever the victim holds."""
    if launch.knockback < combat.TUMBLE_KB:
        return False
    return all(flown.ko for _, _, flown in di_flights(stage, launch, start, grounded, character))


def kill_percent(
    stage: Stage,
    box: HitboxDef,
    heading: Vec2,
    start: Vec3,
    character: CharacterDef,
    grounded: bool = True,
    charge: float = 1.0,
    limit: int = 300,
) -> int | None:
    """The lowest whole percent at which a fresh hit of ``box`` KOs a fighter standing (or
    hanging in the air) at ``start`` with no DI, or ``None`` if it never does up to
    ``limit``. Knockback grows with percent, so this is a bisection of a few flights."""
    damage = box.damage * FRESH * charge

    def at(percent: int) -> bool:
        launch = hit_launch(box, damage, float(percent), character.weight, grounded, heading)
        return kills(stage, launch, start, grounded, character)

    if not at(limit):
        return None
    low, high = 0, limit
    while low < high:
        middle = (low + high) // 2
        if at(middle):
            high = middle
        else:
            low = middle + 1
    return low
