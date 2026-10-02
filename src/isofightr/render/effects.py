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
    Event,
    GrabEvent,
    HitEvent,
    KoEvent,
    LedgeGrabEvent,
    ShieldBreakEvent,
    ShieldHitEvent,
    TechEvent,
    WallBounceEvent,
)
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect

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


def _small_spark(event: Event) -> bool:
    """Return whether an event gets the smallest spark: a tech, wall bounce, ledge grab or
    grab clash."""
    if isinstance(event, GrabEvent):
        return event.clash
    return isinstance(event, TechEvent | WallBounceEvent | LedgeGrabEvent)


@dataclass(slots=True)
class BattleEffects:
    """Everything the battle scene shows in reaction to hits."""

    sparks: list[Spark] = field(default_factory=list)
    shake: ScreenShake = field(default_factory=ScreenShake)
    flash: dict[int, int] = field(default_factory=dict)
    """Ticks of white flash left, by player index."""
    hud_pop: dict[int, tuple[int, int]] = field(default_factory=dict)
    """``(ticks left, pixels)`` of damage-number pop, by player index."""

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
            elif _small_spark(event):
                self.sparks.append(Spark(event.position, SMALL_SPARK_TIER, Effect.NORMAL))
            elif isinstance(event, KoEvent):
                self.shake.start(KO_SHAKE_PIXELS)
                self.flash.pop(event.player, None)

    def tick(self) -> None:
        """Advance every effect by one sim tick."""
        for spark in self.sparks:
            spark.age += 1
        self.sparks = [spark for spark in self.sparks if spark.age < SPARK_LIFETIME]
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

    def hud_offset(self, player_index: int) -> int:
        """Return how many pixels a player's damage number is lifted right now."""
        left, pixels = self.hud_pop.get(player_index, (0, 0))
        return pixels if left > 0 and (left // SHAKE_FLIP_TICKS) % 2 == 0 else 0
