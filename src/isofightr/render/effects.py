"""Hit feedback state: hit sparks, screen shake, hit flash and HUD pops.

Plan note "03 - Isometric World and Rendering" ("Screen shake is a render-only offset driven
by hit events", "Hit sparks scale with knockback", "Hit flash"). This is presentation state
only: it is fed by ``match.events``, advanced once per sim tick, and never read by the sim.

Pure Python (no ``arcade``), so it is unit tested without a window. Drawing is in
:mod:`isofightr.render.effect_renderer`.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from isofightr.render.ground_items import ProjectileLooks
from isofightr.render.iso import project
from isofightr.render.vfx_art import CRACK_ALPHAS, FX_KINDS, WHIRL_FRAMES, fx_lifetime
from isofightr.sim.combat.knockback import launch_vector
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
    ShieldBreakEvent,
    ShieldHitEvent,
    ShockwaveEvent,
    TechEvent,
    WallBounceEvent,
)
from isofightr.sim.fighter import NO_LEDGE, Fighter, Launch, StateId
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.move_def import Effect, MoveKind
from isofightr.sim.projectile import Projectile
from isofightr.sim.stage import Stage

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
SPARK_HITLAG_EXTRA: Final[int] = 3
"""A hit's spark outlives its hitlag by this many ticks (it holds its last, hollow frame, so
the solid frames never cover the victim for longer than before)."""

# --- Launch streaks ------------------------------------------------------------------------
STREAK_MIN_KNOCKBACK: Final[float] = 40.0
"""Launches at least this strong throw speed lines along the launch direction."""
STREAK_FRAME_TICKS: Final[int] = 4
STREAK_FRAMES: Final[int] = 2
STREAK_ANGLES: Final[int] = 16
"""Speed lines are drawn for this many screen directions."""
CLANK_SPARK_TIER: Final[int] = 1
SHIELD_SPARK_TIER: Final[int] = 0
PARRY_SPARK_TIER: Final[int] = 2
SHIELD_BREAK_SPARK_TIER: Final[int] = 3
SMALL_SPARK_TIER: Final[int] = 0
"""Techs, wall bounces, ledge grabs and grab clashes get the smallest spark."""

# --- Screen shake --------------------------------------------------------------------------
SHAKE_MIN_KNOCKBACK: Final[float] = 40.0
"""Hits weaker than this shake the screen by ``SHAKE_LIGHT_PIXELS`` only."""
SHAKE_LIGHT_PIXELS: Final[int] = 1
SHAKE_KNOCKBACK_PER_PIXEL: Final[float] = 50.0
SHAKE_MAX_PIXELS: Final[int] = 4
SHAKE_BASE_FRAMES: Final[int] = 6
SHAKE_FRAMES_PER_PIXEL: Final[int] = 3
SHAKE_FLIP_TICKS: Final[int] = 2
"""The shake direction flips every this many ticks."""
KO_SHAKE_PIXELS: Final[int] = 4
SHOCKWAVE_SHAKE_PIXELS: Final[int] = 2
SHIELD_BREAK_SHAKE_PIXELS: Final[int] = 3
PARRY_SHAKE_PIXELS: Final[int] = 2

# --- Flash and HUD pop ---------------------------------------------------------------------
HIT_FLASH_FRAMES: Final[int] = 3
HIT_FLASH_HITLAG_SHARE: Final[int] = 3
"""The hit flash lasts the first 1/N of the hitlag (at least ``HIT_FLASH_FRAMES``)..."""
HIT_FLASH_MAX_FRAMES: Final[int] = 8
"""...and never longer than this, however long the freeze."""
COUNTER_FLASH_FRAMES: Final[int] = 6
"""A fighter that was just hit is drawn white for this many ticks."""
HUD_POP_FRAMES: Final[int] = 10
"""The damage number jumps for this many ticks after a hit."""
HUD_POP_DAMAGE_PER_PIXEL: Final[float] = 4.0
HUD_POP_MAX_PIXELS: Final[int] = 4
COMBO_LINGER_TICKS: Final[int] = 60

# --- Move effects (decision D-060) ---------------------------------------------------------
PROJECTILE_HIT_RADIUS: Final[float] = 1.5
"""A projectile that ends this close to a hit or a block this tick ended on that hit."""
EMBER_RISE: Final[float] = 0.01
"""Embers shed by a fire projectile drift up this fast, in units per tick."""
CHARGE_GLOW_FORWARD: Final[float] = 0.55
CHARGE_GLOW_HEIGHT: Final[float] = 1.35
"""Where a charge glows: in front of the fighter, about hand height."""
CHARGE_GLOW_LEVELS: Final[int] = 4
CHARGE_PULSE_TICKS: Final[int] = 3
CHARACTER_FAMILIES: Final[dict[str, str]] = {
    "rook": "pale",
    "bramble": "stone",
    "zephyr": "wind",
    "mote": "rune",
}
"""Colour family of each character's own move effects (others get the default)."""
DEFAULT_FAMILY: Final[str] = "pale"
SPECIAL_TRAIL_SPEED: Final[float] = 0.16
"""A special that moves its fighter at least this far per tick leaves a trail."""
SPECIAL_TRAIL_EVERY: Final[int] = 2
SPECIAL_DUST_EVERY: Final[int] = 6
"""A grounded dash kicks up dust this often."""
BODY_CENTRE_HEIGHT: Final[float] = 1.2
"""Where effects around a fighter's body are centred, in units above its feet."""
WHIRL_SPIN_TICKS: Final[int] = 2
GLINT_PULSE_TICKS: Final[int] = 4
VINE_LINK_SPACING: Final[float] = 0.22
"""Distance between the links of a tether vine, in units."""
VINE_MAX_LINKS: Final[int] = 40
DIVE_STREAK_SPEED: Final[float] = 0.12
"""A fighter diving at least this fast in a down special trails streaks above it."""
DIVE_STREAK_EVERY: Final[int] = 3
ELEMENT_EXTRAS: Final[dict[Effect, tuple[str, str]]] = {
    Effect.SLASH: ("slash", "pale"),
    Effect.FIRE: ("ember", "fire"),
    Effect.DARKNESS: ("implode", "rune"),
}
"""An extra effect on top of the spark for hits of an element: ``(kind, family)``."""
EMBER_SPRAY: Final[tuple[tuple[float, float], ...]] = ((0.02, 0.03), (-0.02, 0.035), (0.0, 0.045))
"""Sideways and upward drift of the embers a fire hit throws, in units per tick."""
CRACK_TICKS: Final[int] = 96
"""How long a ground crack stays, fading out."""
CRACK_MOVES: Final[frozenset[str]] = frozenset({"quake_land"})
"""Moves whose first frame cracks the ground under the fighter."""
"""A finished string's count stays on the HUD this long."""


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
    lifetime: int = SPARK_LIFETIME

    @property
    def frame(self) -> int:
        """Which animation frame to show (a long-lived spark holds its last one)."""
        return min(self.age // SPARK_FRAME_TICKS, SPARK_FRAMES - 1)


@dataclass(slots=True)
class Fx:
    """A small move effect (decision D-060): a burst, a glow, a particle. ``kind`` is its
    shape and ``family`` its colours (see ``vfx_art.build_fx``); it may drift."""

    kind: str
    position: Vec3
    family: str = "pale"
    variant: int = 0
    velocity: Vec3 = ZERO3
    """World units per tick."""
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        frames, ticks = FX_KINDS[self.kind]
        return min(self.age // ticks, frames - 1)

    @property
    def at(self) -> Vec3:
        """Where it is now."""
        return self.position + self.velocity * float(self.age)


@dataclass(slots=True)
class Decal:
    """A mark left on the ground (a crack). Drawn in the world's depth order."""

    decal_id: int
    position: Vec3
    """On the surface it lies on."""
    age: int = 0

    @property
    def fade(self) -> int:
        """How far it has faded: 0 fresh, up to ``len(CRACK_ALPHAS) - 1``."""
        return min(self.age * len(CRACK_ALPHAS) // CRACK_TICKS, len(CRACK_ALPHAS) - 1)


@dataclass(slots=True)
class _Seen:
    """What a projectile looked like when last observed."""

    position: Vec3
    age: int
    lifetime: int
    family: str
    styled: bool
    decal: bool
    owner: int = 0


@dataclass(slots=True)
class ComboReadout:
    """The string of hits a player is taking (or just took), for the HUD's combo counter."""

    hits: int
    damage: float
    linger: int = COMBO_LINGER_TICKS
    """Ticks left to show it; refreshed every tick while the string is live."""


@dataclass(slots=True)
class Streak:
    """Speed lines thrown along a launch, as seen on screen."""

    position: Vec3
    angle: int
    """Screen direction index, 0 to ``STREAK_ANGLES`` - 1, counter-clockwise from right."""
    age: int = 0

    @property
    def frame(self) -> int:
        """Which animation frame to show."""
        return min(self.age // STREAK_FRAME_TICKS, STREAK_FRAMES - 1)


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
        return SHAKE_LIGHT_PIXELS
    return min(SHAKE_MAX_PIXELS, max(1, round(knockback / SHAKE_KNOCKBACK_PER_PIXEL)))


def hit_flash_ticks(hitlag: int) -> int:
    """Return how long a hit with this hitlag flashes its target white."""
    return min(max(HIT_FLASH_FRAMES, hitlag // HIT_FLASH_HITLAG_SHARE), HIT_FLASH_MAX_FRAMES)


def spark_lifetime(hitlag: int) -> int:
    """Return how many ticks a hit's spark lives: at least as long as the freeze."""
    return max(SPARK_LIFETIME, hitlag + SPARK_HITLAG_EXTRA)


def streak_angle(launch: Launch) -> int:
    """Return the screen direction index of a launch (before DI)."""
    direction = launch_vector(launch.heading, launch.elevation)
    screen_x, screen_y = project(direction.x, direction.y, direction.z)
    turn = math.atan2(screen_y, screen_x) / (2.0 * math.pi)
    return round(turn * STREAK_ANGLES) % STREAK_ANGLES


def _small_spark_at(event: Event) -> Vec3 | None:
    """Return where an event gets the smallest spark, or ``None`` if it gets none: a tech,
    wall bounce, ledge grab, grab clash, or a projectile ending."""
    if isinstance(event, GrabEvent):
        return event.position if event.clash else None
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
    streaks: list[Streak] = field(default_factory=list)
    fx: list[Fx] = field(default_factory=list)
    """Move effects: bursts, glows and particles (decision D-060)."""
    _projectiles: dict[int, _Seen] = field(default_factory=dict)
    _hit_points: list[Vec3] = field(default_factory=list)
    """Where hits and blocks landed this tick: a projectile that ends there ended on a hit."""
    _charged: dict[int, bool] = field(default_factory=dict)
    """Whether each player's charge was already full, to pop once when it fills."""
    decals: list[Decal] = field(default_factory=list)
    """Ground marks (cracks), given to the world renderer as ground items."""
    _next_decal: int = 0
    _last_pos: dict[int, Vec3] = field(default_factory=dict)
    _dashing: dict[int, bool] = field(default_factory=dict)
    """Whether each player's special was already moving it fast last tick."""
    _struck: set[int] = field(default_factory=set)
    """Players that took a hit this tick (to glint armour that absorbed it)."""
    combos: dict[int, ComboReadout] = field(default_factory=dict)
    """The string each player is taking, by the victim's player index (plan note 13)."""
    _hit_damage: dict[int, float] = field(default_factory=dict)
    """Damage of this tick's hits by target, until ``observe`` adds it to a string."""
    hit_hitlag: dict[int, int] = field(default_factory=dict)
    """The hitlag of the last hit each player took: sizes the victim's shake."""
    ticks: int = 0
    _launches: dict[int, Launch] = field(default_factory=dict)
    """The pending launch last seen on each player, to notice a new one."""

    def consume(self, events: Iterable[Event]) -> None:
        """React to one tick's sim events."""
        for event in events:
            if isinstance(event, HitEvent | ShieldHitEvent):
                self._hit_points.append(event.position)
                self._struck.add(event.target)
            if isinstance(event, HitEvent):
                self.sparks.append(
                    Spark(
                        event.position,
                        spark_tier(event.knockback),
                        event.effect,
                        lifetime=spark_lifetime(event.hitlag),
                    )
                )
                extra = ELEMENT_EXTRAS.get(event.effect)
                if extra is not None:
                    kind, family = extra
                    self.fx.append(Fx(kind, event.position, family))
                    if kind == "ember":
                        for index, (dx, dz) in enumerate(EMBER_SPRAY):
                            drift = Vec3(dx, -dx, dz)
                            self.fx.append(Fx(kind, event.position, family, index, drift))
                if event.damage > 0:
                    taken = self._hit_damage.get(event.target, 0.0)
                    self._hit_damage[event.target] = taken + event.damage
                    self.shake.start(shake_pixels(event.knockback))
                    self.hit_hitlag[event.target] = event.hitlag
                    self.flash[event.target] = hit_flash_ticks(event.hitlag)
                    pixels = 1 + round(event.damage / HUD_POP_DAMAGE_PER_PIXEL)
                    self.hud_pop[event.target] = (HUD_POP_FRAMES, min(pixels, HUD_POP_MAX_PIXELS))
            elif isinstance(event, ClankEvent):
                self.sparks.append(Spark(event.position, CLANK_SPARK_TIER, Effect.NORMAL))
            elif isinstance(event, ShieldHitEvent):
                tier = PARRY_SPARK_TIER if event.parried else SHIELD_SPARK_TIER
                self.sparks.append(Spark(event.position, tier, Effect.ICE))
                self.fx.append(Fx("ripple", event.position, "pale"))
                if event.parried:
                    self.shake.start(PARRY_SHAKE_PIXELS)
            elif isinstance(event, ShieldBreakEvent):
                self.sparks.append(Spark(event.position, SHIELD_BREAK_SPARK_TIER, Effect.ICE))
                self.shake.start(SHIELD_BREAK_SHAKE_PIXELS)
            elif isinstance(event, CounterEvent):
                self.flash[event.player] = COUNTER_FLASH_FRAMES
                self.shake.start(PARRY_SHAKE_PIXELS)
                self.sparks.append(Spark(event.position, PARRY_SPARK_TIER, Effect.NORMAL))
                self.fx.append(Fx("pop", event.position, "gold"))
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
            elif isinstance(event, JumpEvent):
                self.fx.append(Fx("air_ring", event.position, "wind"))
            elif isinstance(event, ShockwaveEvent):
                self.rings.append(Ring(event.position))
                self.puffs.append(Puff(event.position, "big"))
                self.shake.start(SHOCKWAVE_SHAKE_PIXELS)
            else:
                point = _small_spark_at(event)
                if point is not None:
                    self.sparks.append(Spark(point, SMALL_SPARK_TIER, Effect.NORMAL))
                if isinstance(event, TechEvent) and not event.wall:
                    self.rings.append(Ring(event.position))

    def observe(self, fighters: Iterable[Fighter], stage: Stage | None = None) -> None:
        """Add the effects that come from what fighters are doing rather than from events:
        dust when a dash, skid or run turn starts, and the smoke trail of a launch."""
        for fighter in fighters:
            self._observe_launch(fighter)
            self._observe_combo(fighter)
            self._observe_charge(fighter)
            self._observe_special(fighter, stage)
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

    def observe_projectiles(
        self, projectiles: Iterable[Projectile], looks: ProjectileLooks
    ) -> None:
        """Follow the projectiles in flight: a burst where one appears, whatever it sheds as
        it flies, and a burst where it ends, by cause. The cause is read from what was seen
        (its lifetime ran out, a hit landed next to it, or else it struck the ground), so the
        sim's events need no extra fields. Call once per tick, after ``consume``."""
        alive: dict[int, _Seen] = {}
        for projectile in projectiles:
            if not projectile.alive or projectile.bursting:
                continue
            style = looks.style(projectile)
            family = "pale" if style is None else style.family
            seen = _Seen(
                projectile.pos,
                projectile.age,
                projectile.lifetime,
                family,
                style is not None,
                style is not None and style.decal,
            )
            alive[projectile.id] = seen
            seen.owner = projectile.owner
            before = self._projectiles.get(projectile.id)
            if before is not None and before.owner != projectile.owner:
                self.fx.append(Fx("burst_hit", projectile.pos, "wind"))  # it was reflected
            if before is None:
                if style is not None and not style.decal:
                    self.fx.append(Fx("muzzle", projectile.pos, family))
            elif style is not None and style.sheds and projectile.age % style.shed_every == 0:
                drift = ZERO3
                if style.sheds == "ember":
                    drift = Vec3(0.0, 0.0, EMBER_RISE)
                self.fx.append(Fx(style.sheds, projectile.previous, family, velocity=drift))
        for projectile_id, seen in self._projectiles.items():
            if projectile_id in alive:
                continue
            if not seen.styled:
                self.sparks.append(Spark(seen.position, SMALL_SPARK_TIER, Effect.NORMAL))
                continue
            self.fx.append(Fx(self._end_kind(seen), seen.position, seen.family))
        self._projectiles = alive

    def _end_kind(self, seen: _Seen) -> str:
        """Return the burst for a projectile that just ended, by what ended it."""
        near = PROJECTILE_HIT_RADIUS
        if any((point - seen.position).length() <= near for point in self._hit_points):
            return "burst_hit"
        if seen.age + 1 >= seen.lifetime:
            return "burst_fade"
        return "burst_hit" if seen.decal else "burst_ground"

    def _observe_charge(self, fighter: Fighter) -> None:
        """A glow at the hands while a move charges (growing with it), a ring pop when the
        charge fills, and a steady glow while a charge is stored for later."""
        player = fighter.player_index
        move = fighter.move
        charging = move is not None and move.charge is not None and fighter.charge_frames > 0
        if not charging and fighter.stored_charge <= 0:
            self._charged.pop(player, None)
            return
        facing = fighter.facing.world
        pos = fighter.pos
        hand = Vec3(
            pos.x + facing.x * CHARGE_GLOW_FORWARD,
            pos.y + facing.y * CHARGE_GLOW_FORWARD,
            pos.z + CHARGE_GLOW_HEIGHT,
        )
        pulse = (self.ticks // CHARGE_PULSE_TICKS) % 2
        if not charging or move is None or move.charge is None:
            self.fx.append(Fx("glow", hand, "fire", variant=pulse))
            return
        family = "fire" if move.projectiles and move.kind is MoveKind.SPECIAL else "gold"
        if fighter.character.id == "rook" and move.kind is MoveKind.SPECIAL:
            family = "pale"
        share = min(fighter.charge_frames / move.charge.max_frames, 1.0)
        level = min(CHARGE_GLOW_LEVELS - 1, int(share * CHARGE_GLOW_LEVELS))
        self.fx.append(Fx("glow", hand, family, variant=level * 2 + pulse))
        full = share >= 1.0
        if full and not self._charged.get(player, False):
            self.fx.append(Fx("pop", hand, family))
        self._charged[player] = full

    def _observe_special(self, fighter: Fighter, stage: Stage | None) -> None:
        """The effects of a special move itself (decision D-060): a trail and bursts for any
        special that moves its fighter fast, a wind ring while a move reflects, a glint
        while it counters or its armour absorbs a hit, the vine of a tether, streaks above a
        dive, and a crack where a slam lands."""
        player = fighter.player_index
        pos = fighter.pos
        last = self._last_pos.get(player, pos)
        self._last_pos[player] = pos
        struck = player in self._struck
        move = fighter.move
        family = CHARACTER_FAMILIES.get(fighter.character.id, DEFAULT_FAMILY)
        centre = Vec3(pos.x, pos.y, pos.z + BODY_CENTRE_HEIGHT)
        special = move is not None and move.kind is MoveKind.SPECIAL and fighter.hitlag == 0
        fast = special and (pos - last).length() >= SPECIAL_TRAIL_SPEED
        was_fast = self._dashing.get(player, False)
        if fast:
            start = Vec3(last.x, last.y, last.z + BODY_CENTRE_HEIGHT)
            if not was_fast:
                self.fx.append(Fx("burst_fade", start, family))
                if fighter.grounded or pos.z > last.z:
                    self.puffs.append(Puff(last, "small"))
            if self.ticks % SPECIAL_TRAIL_EVERY == 0:
                self.fx.append(Fx("ribbon", start, family))
            if fighter.grounded and self.ticks % SPECIAL_DUST_EVERY == 0:
                self.puffs.append(Puff(last, "small"))
        elif was_fast:
            self.fx.append(Fx("burst_fade", centre, family))
        self._dashing[player] = fast
        if fighter.tether_ledge != NO_LEDGE and stage is not None:
            self._vine(fighter, stage)
        if move is None or (fighter.hitlag > 0 and not struck):
            return
        frame = fighter.state_frame
        if move.reflect is not None and frame in move.reflect:
            spin = (self.ticks // WHIRL_SPIN_TICKS) % WHIRL_FRAMES
            self.fx.append(Fx("whirl", centre, family, variant=spin))
        pulse = (self.ticks // GLINT_PULSE_TICKS) % 2
        if move.counter is not None and frame in move.counter.frames:
            facing = fighter.facing.world
            chest = Vec3(pos.x + facing.x * 0.4, pos.y + facing.y * 0.4, centre.z + 0.3)
            self.fx.append(Fx("glint", chest, "gold", variant=pulse))
        if struck and move.armor_threshold(frame) is not None and fighter.launch is None:
            self.fx.append(Fx("glint", centre, "gold", variant=1))
        diving = special and not fighter.grounded and last.z - pos.z >= DIVE_STREAK_SPEED
        down_special = fighter.move_id.startswith("dspecial")
        if diving and down_special and self.ticks % DIVE_STREAK_EVERY == 0:
            above = Vec3(pos.x, pos.y, pos.z + 2 * BODY_CENTRE_HEIGHT)
            self.fx.append(Fx("streak_down", above, family))
        if fighter.move_id in CRACK_MOVES and frame == 1 and fighter.hitlag == 0:
            self.decals.append(Decal(self._next_decal, pos))
            self._next_decal += 1
            self.fx.append(Fx("burst_ground", pos, "stone"))

    def _vine(self, fighter: Fighter, stage: Stage) -> None:
        """Draw the tether from the fighter's hands to the ledge point it caught."""
        if fighter.tether_ledge >= len(stage.ledges):
            return
        ledge = stage.ledges[fighter.tether_ledge]
        end = Vec3(fighter.tether_point.x, fighter.tether_point.y, ledge.z)
        start = Vec3(fighter.pos.x, fighter.pos.y, fighter.pos.z + BODY_CENTRE_HEIGHT)
        span = end - start
        links = min(VINE_MAX_LINKS, max(1, int(span.length() / VINE_LINK_SPACING)))
        for index in range(links + 1):
            at = start + span * (index / links)
            self.fx.append(Fx("vine", at, "vine", variant=index % 2))

    def _observe_combo(self, fighter: Fighter) -> None:
        """Follow the sim's own combo count (``Fighter.combo_hits``, D-040) and total the
        string's damage from this tick's hits. Read-only: the sim decides what a string is."""
        player = fighter.player_index
        dealt = self._hit_damage.pop(player, 0.0)
        hits = fighter.combo_hits
        if hits <= 0:
            return
        readout = self.combos.get(player)
        fresh = readout is None or hits < readout.hits or (hits == 1 and dealt > 0.0)
        if fresh or readout is None:
            self.combos[player] = ComboReadout(hits, dealt)
        else:
            readout.hits = hits
            readout.damage += dealt
            readout.linger = COMBO_LINGER_TICKS

    def _observe_launch(self, fighter: Fighter) -> None:
        """Throw speed lines when a fighter is first seen with a new, strong launch waiting."""
        player = fighter.player_index
        launch = fighter.launch
        if launch is None:
            self._launches.pop(player, None)
            return
        if self._launches.get(player) is launch:
            return
        self._launches[player] = launch
        if launch.knockback >= STREAK_MIN_KNOCKBACK:
            pos = fighter.pos
            at = Vec3(pos.x, pos.y, pos.z + TRAIL_BODY_HEIGHT)
            self.streaks.append(Streak(at, streak_angle(launch)))

    def tick(self) -> None:
        """Advance every effect by one sim tick."""
        for spark in self.sparks:
            spark.age += 1
        self.sparks = [spark for spark in self.sparks if spark.age < spark.lifetime]
        self.ticks += 1
        for effect in (*self.puffs, *self.trails, *self.rings, *self.blasts, *self.streaks):
            effect.age += 1
        for effect in self.fx:
            effect.age += 1
        self.fx = [effect for effect in self.fx if effect.age < fx_lifetime(effect.kind)]
        self._hit_points = []
        self._struck = set()
        for decal in self.decals:
            decal.age += 1
        self.decals = [decal for decal in self.decals if decal.age < CRACK_TICKS]
        self.streaks = [s for s in self.streaks if s.age < STREAK_FRAMES * STREAK_FRAME_TICKS]
        for readout in self.combos.values():
            readout.linger -= 1
        self.combos = {player: r for player, r in self.combos.items() if r.linger > 0}
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
        self.streaks = []
        self.hit_hitlag = {}
        self._launches = {}
        self.combos = {}
        self._hit_damage = {}
        self.fx = []
        self._projectiles = {}
        self._hit_points = []
        self._charged = {}
        self.decals = []
        self._last_pos = {}
        self._dashing = {}
        self._struck = set()

    def hud_offset(self, player_index: int) -> int:
        """Return how many pixels a player's damage number is lifted right now."""
        left, pixels = self.hud_pop.get(player_index, (0, 0))
        return pixels if left > 0 and (left // SHAKE_FLIP_TICKS) % 2 == 0 else 0
