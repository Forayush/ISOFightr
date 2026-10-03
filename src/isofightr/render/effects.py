"""Hit feedback state: hit sparks, screen shake, hit flash and HUD pops.

Plan note "03 - Isometric World and Rendering" ("Screen shake is a render-only offset driven
by hit events", "Hit sparks scale with knockback", "Hit flash"). This is presentation state
only: it is fed by ``match.events``, advanced once per sim tick, and never read by the sim.

Pure Python (no ``arcade``), so it is unit tested without a window. Drawing is in
:mod:`isofightr.render.effect_renderer`.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from isofightr.sim.events import (
    ClankEvent,
    CounterEvent,
    Event,
    GrabEvent,
    HitEvent,
    JumpEvent,
    JumpKind,
    KoEvent,
    LandEvent,
    LedgeGrabEvent,
    ProjectileEvent,
    ShieldBreakEvent,
    ShieldHitEvent,
    TechEvent,
    WallBounceEvent,
)
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect

# --- Dust, trails, rings and KO blasts (M8) --------------------------------------------------
EFFECT_FRAME_TICKS: Final[int] = 3
"""Ticks each frame of a puff, trail puff or ring is shown."""
PUFF_FRAMES: Final[int] = 4
TRAIL_FRAMES: Final[int] = 4
RING_FRAMES: Final[int] = 4
KO_BLAST_FRAME_TICKS: Final[int] = 6
KO_BLAST_FRAMES: Final[int] = 5
LAND_DUST_FALL_SPEED: Final[float] = 0.05
"""Landings faster than this (units per frame) raise dust."""
LAND_RING_FALL_SPEED: Final[float] = 0.22
"""Landings faster than this (a fast fall or a launch into the ground) send out a ring."""
TRAIL_MIN_SPEED: Final[float] = 0.12
"""A fighter in hitstun moving faster than this (units per frame) leaves a smoke trail."""
TRAIL_FIERY_KNOCKBACK: Final[float] = 150.0
"""A launch this strong leaves a fiery trail (a likely KO)."""
TRAIL_EVERY: Final[int] = 3
"""Ticks between trail puffs."""
TRAIL_BODY_HEIGHT: Final[float] = 1.2
DUST_BEHIND: Final[float] = 0.4
"""How far behind a dashing fighter's feet its dust appears, in units."""
DUST_STATES: Final[frozenset[StateId]] = frozenset({StateId.DASH, StateId.SKID, StateId.RUN_TURN})

# --- Hit sparks ----------------------------------------------------------------------------
SPARK_TIER_KNOCKBACK: Final[tuple[float, ...]] = (40.0, 80.0, 150.0)
"""Knockback at which a spark moves up a tier: light, medium, heavy, KO."""
SPARK_FRAME_TICKS: Final[int] = 3
"""Ticks each spark animation frame is shown."""
SPARK_FRAMES: Final[int] = 3
SPARK_LIFETIME: Final[int] = SPARK_FRAME_TICKS * SPARK_FRAMES
CLANK_SPARK_TIER: Final[int] = 1
SHIELD_SPARK_TIER: Final[int] = 0
PARRY_SPARK_TIER: Final[int] = 2
SHIELD_BREAK_SPARK_TIER: Final[int] = 3
SMALL_SPARK_TIER: Final[int] = 0
"""Techs, wall bounces, ledge grabs and grab clashes get the smallest spark."""

# --- Screen shake --------------------------------------------------------------------------
SHAKE_MIN_KNOCKBACK: Final[float] = 40.0
"""Hits weaker than this do not shake the screen."""
SHAKE_KNOCKBACK_PER_PIXEL: Final[float] = 50.0
SHAKE_MAX_PIXELS: Final[int] = 4
SHAKE_BASE_FRAMES: Final[int] = 6
SHAKE_FRAMES_PER_PIXEL: Final[int] = 3
SHAKE_FLIP_TICKS: Final[int] = 2
"""The shake direction flips every this many ticks."""
KO_SHAKE_PIXELS: Final[int] = 4
SHIELD_BREAK_SHAKE_PIXELS: Final[int] = 3
PARRY_SHAKE_PIXELS: Final[int] = 2

# --- Flash and HUD pop ---------------------------------------------------------------------
HIT_FLASH_FRAMES: Final[int] = 3
COUNTER_FLASH_FRAMES: Final[int] = 6
"""A fighter that was just hit is drawn white for this many ticks."""
HUD_POP_FRAMES: Final[int] = 10
"""The damage number jumps for this many ticks after a hit."""
HUD_POP_DAMAGE_PER_PIXEL: Final[float] = 4.0
HUD_POP_MAX_PIXELS: Final[int] = 4


def spark_tier(knockback: float) -> int:
    """Return the spark size tier for a hit: 0 light, 1 medium, 2 heavy, 3 KO strength."""
    return sum(knockback >= threshold for threshold in SPARK_TIER_KNOCKBACK)


@dataclass(slots=True)
class Spark:
    """One hit spark, at a fixed point in the world."""

    position: Vec3
    tier: int
    effect: Effect
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        return min(self.age // SPARK_FRAME_TICKS, SPARK_FRAMES - 1)


@dataclass(slots=True)
class Puff:
    """A dust puff on the ground (``size`` is ``"small"`` or ``"big"``)."""

    position: Vec3
    size: str
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        return min(self.age // EFFECT_FRAME_TICKS, PUFF_FRAMES - 1)


@dataclass(slots=True)
class TrailPuff:
    """One puff of a launched fighter's smoke trail."""

    position: Vec3
    fiery: bool
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        return min(self.age // EFFECT_FRAME_TICKS, TRAIL_FRAMES - 1)


@dataclass(slots=True)
class Ring:
    """A shockwave ring spreading on the ground."""

    position: Vec3
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        return min(self.age // EFFECT_FRAME_TICKS, RING_FRAMES - 1)


@dataclass(slots=True)
class KoBlast:
    """The beam where a fighter left through a blast zone, pointing back at the stage."""

    player: int
    position: Vec3
    """Where the blast zone was crossed."""
    normal: Vec3
    """Outward normal of the crossed face: the beam points the other way."""
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        return min(self.age // KO_BLAST_FRAME_TICKS, KO_BLAST_FRAMES - 1)


@dataclass(slots=True)
class ScreenShake:
    """A decaying up-and-down camera offset, in whole native pixels."""

    amplitude: int = 0
    frames: int = 0
    age: int = 0

    def start(self, pixels: int) -> None:
        """Begin a shake of ``pixels``, unless a stronger one is still running."""
        pixels = min(pixels, SHAKE_MAX_PIXELS)
        if pixels <= 0 or pixels < self.current():
            return
        self.amplitude = pixels
        self.frames = SHAKE_BASE_FRAMES + pixels * SHAKE_FRAMES_PER_PIXEL
        self.age = 0

    def tick(self) -> None:
        """Advance by one sim tick."""
        if self.age < self.frames:
            self.age += 1

    def current(self) -> int:
        """Return the size of the shake right now, in pixels (it fades out linearly)."""
        if self.age >= self.frames:
            return 0
        remaining = self.frames - self.age
        return max(1, round(self.amplitude * remaining / self.frames))

    @property
    def offset(self) -> tuple[int, int]:
        """The camera offset for this frame."""
        size = self.current()
        up = (self.age // SHAKE_FLIP_TICKS) % 2 == 0
        return (0, size if up else -size)


def shake_pixels(knockback: float) -> int:
    """Return how hard a hit of ``knockback`` shakes the screen, in pixels."""
    if knockback < SHAKE_MIN_KNOCKBACK:
        return 0
    return min(SHAKE_MAX_PIXELS, max(1, round(knockback / SHAKE_KNOCKBACK_PER_PIXEL)))


def _small_spark_at(event: Event) -> Vec3 | None:
    """Return where an event gets the smallest spark, or ``None`` if it gets none: a tech,
    wall bounce, ledge grab, grab clash, or a projectile ending."""
    if isinstance(event, GrabEvent):
        return event.position if event.clash else None
    if isinstance(event, ProjectileEvent):
        return None if event.spawned else event.position
    if isinstance(event, TechEvent | WallBounceEvent | LedgeGrabEvent):
        return event.position
    return None


@dataclass(slots=True)
class BattleEffects:
    """Everything the battle scene shows in reaction to hits."""

    sparks: list[Spark] = field(default_factory=list)
    shake: ScreenShake = field(default_factory=ScreenShake)
    flash: dict[int, int] = field(default_factory=dict)
    """Ticks of white flash left, by player index."""
    hud_pop: dict[int, tuple[int, int]] = field(default_factory=dict)
    """``(ticks left, pixels)`` of damage-number pop, by player index."""
    puffs: list[Puff] = field(default_factory=list)
    trails: list[TrailPuff] = field(default_factory=list)
    rings: list[Ring] = field(default_factory=list)
    blasts: list[KoBlast] = field(default_factory=list)
    ticks: int = 0

    def consume(self, events: Iterable[Event]) -> None:
        """React to one tick's sim events."""
        for event in events:
            if isinstance(event, HitEvent):
                self.sparks.append(Spark(event.position, spark_tier(event.knockback), event.effect))
                self.shake.start(shake_pixels(event.knockback))
                if event.damage > 0:
                    self.flash[event.target] = HIT_FLASH_FRAMES
                    pixels = 1 + round(event.damage / HUD_POP_DAMAGE_PER_PIXEL)
                    self.hud_pop[event.target] = (HUD_POP_FRAMES, min(pixels, HUD_POP_MAX_PIXELS))
            elif isinstance(event, ClankEvent):
                self.sparks.append(Spark(event.position, CLANK_SPARK_TIER, Effect.NORMAL))
            elif isinstance(event, ShieldHitEvent):
                tier = PARRY_SPARK_TIER if event.parried else SHIELD_SPARK_TIER
                self.sparks.append(Spark(event.position, tier, Effect.ICE))
                if event.parried:
                    self.shake.start(PARRY_SHAKE_PIXELS)
            elif isinstance(event, ShieldBreakEvent):
                self.sparks.append(Spark(event.position, SHIELD_BREAK_SPARK_TIER, Effect.ICE))
                self.shake.start(SHIELD_BREAK_SHAKE_PIXELS)
            elif isinstance(event, CounterEvent):
                self.flash[event.player] = COUNTER_FLASH_FRAMES
                self.shake.start(PARRY_SHAKE_PIXELS)
            elif isinstance(event, KoEvent):
                self.shake.start(KO_SHAKE_PIXELS)
                self.flash.pop(event.player, None)
                self.blasts.append(KoBlast(event.player, event.position, event.normal))
            elif isinstance(event, LandEvent):
                if event.fall_speed >= LAND_DUST_FALL_SPEED:
                    big = event.fall_speed >= LAND_RING_FALL_SPEED
                    self.puffs.append(Puff(event.position, "big" if big else "small"))
                    if big:
                        self.rings.append(Ring(event.position))
            elif isinstance(event, JumpEvent) and event.kind is not JumpKind.AIR:
                self.puffs.append(Puff(event.position, "small"))
            else:
                point = _small_spark_at(event)
                if point is not None:
                    self.sparks.append(Spark(point, SMALL_SPARK_TIER, Effect.NORMAL))
                if isinstance(event, TechEvent) and not event.wall:
                    self.rings.append(Ring(event.position))

    def observe(self, fighters: Iterable[Fighter]) -> None:
        """Add the effects that come from what fighters are doing rather than from events:
        dust when a dash, skid or run turn starts, and the smoke trail of a launch."""
        for fighter in fighters:
            if fighter.state in DUST_STATES and fighter.state_frame == 1:
                facing = fighter.facing.world
                behind = -DUST_BEHIND if fighter.state is StateId.DASH else DUST_BEHIND
                pos = fighter.pos
                at = Vec3(pos.x + facing.x * behind, pos.y + facing.y * behind, pos.z)
                self.puffs.append(Puff(at, "small"))
            launched = fighter.hitstun > 0 and fighter.kb_vel.length() >= TRAIL_MIN_SPEED
            if launched and self.ticks % TRAIL_EVERY == 0:
                pos = fighter.pos
                fiery = fighter.last_knockback >= TRAIL_FIERY_KNOCKBACK
                at = Vec3(pos.x, pos.y, pos.z + TRAIL_BODY_HEIGHT)
                self.trails.append(TrailPuff(at, fiery))

    def tick(self) -> None:
        """Advance every effect by one sim tick."""
        for spark in self.sparks:
            spark.age += 1
        self.sparks = [spark for spark in self.sparks if spark.age < SPARK_LIFETIME]
        self.ticks += 1
        for effect in (*self.puffs, *self.trails, *self.rings, *self.blasts):
            effect.age += 1
        self.puffs = [p for p in self.puffs if p.age < PUFF_FRAMES * EFFECT_FRAME_TICKS]
        self.trails = [p for p in self.trails if p.age < TRAIL_FRAMES * EFFECT_FRAME_TICKS]
        self.rings = [r for r in self.rings if r.age < RING_FRAMES * EFFECT_FRAME_TICKS]
        self.blasts = [b for b in self.blasts if b.age < KO_BLAST_FRAMES * KO_BLAST_FRAME_TICKS]
        self.shake.tick()
        self.flash = {player: left - 1 for player, left in self.flash.items() if left > 1}
        self.hud_pop = {
            player: (left - 1, pixels)
            for player, (left, pixels) in self.hud_pop.items()
            if left > 1
        }

    def clear(self) -> None:
        """Drop everything (match restart)."""
        self.sparks = []
        self.shake = ScreenShake()
        self.flash = {}
        self.hud_pop = {}
        self.puffs, self.trails, self.rings, self.blasts = [], [], [], []

    def hud_offset(self, player_index: int) -> int:
        """Return how many pixels a player's damage number is lifted right now."""
        left, pixels = self.hud_pop.get(player_index, (0, 0))
        return pixels if left > 0 and (left // SHAKE_FLIP_TICKS) % 2 == 0 else 0
