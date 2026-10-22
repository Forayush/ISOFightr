"""The hit splash: a three-phase, directional, tiered, themed hit effect (decision D-068).

Plan note "09 - Art Direction" (VFX style) and D-068 in "19 - Decision Log". One
:class:`HitSplash` per hit, in three phases tied to the hit's freeze (its hitlag):

- **burst** (``BURST_TICKS``: the contact tick and the next): a flash at the contact point;
- **hold** (the rest of the freeze): the core splash holds, its frames spread across the
  freeze (``ceil(hold / HOLD_FRAMES)`` ticks each), vibrating by a pixel, pointing along the
  pending launch before DI: what the defender can read while it can still DI;
- **dispersal** (from the tick the launch starts, the sim's ``LaunchEvent``): particles burst
  in a cone around where the target really flies, after DI, slowing and fading over the
  tier's ``DISPERSAL_TICKS``.

Its **tier** is the knockback band (``TIER_KNOCKBACK``), one up for a sweetspot (to heavy at
most), one down for a multi-hit sub-hit, and critical only for a hit forecast to KO
(:mod:`isofightr.render.ko_forecast`). Heavy and critical hits add a chromatic split under the
burst (two palette-coloured copies, ``SPLIT_OFFSET`` pixels to either side) and a shockwave ring
at the launch; a critical hit adds a flare and a two-tick screen flash. "Reduce flashing"
(``calm``) drops the split and the screen flash.

Its **theme** is the hit's effect, or for a normal hit the attacker's ``hit_theme``.
Particles move by a fixed hash of the hit's match frame, the target's player index and the
particle's number: the same on every run, nothing drawn from the sim. Everything is placed in
world pixels (as :func:`isofightr.render.iso.project` gives them), so the effect renderer
draws :meth:`HitSplashes.sprites` as they come; :mod:`isofightr.render.splash_art` draws
their keys.

A blocked hit gets a :class:`GuardSplash` instead (decision D-068, group 3): the splash
flattens into an arc of sparks along the shield bubble where the blow met it, held for the
defender's freeze, then sparks skitter off along the bubble; a parried hit gets a golden-white
shockwave ring that bursts out over ``PARRY_RING_TICKS``, pulses for as long as the attacker
stays frozen (its own hitlag, read from the fighter), and fades.

Presentation only: fed with ``match.events`` and the fighters, never writing to them. Pure
Python (no ``arcade``).
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from isofightr.render.hurt_motion import MASK64, mix64
from isofightr.render.iso import project
from isofightr.render.ko_forecast import will_ko
from isofightr.render.placeholder_art import sphere_screen_size
from isofightr.render.splash_art import (
    CORE_FRAMES,
    FLARE_FRAMES,
    PARRY_FRAME_COUNT,
    RING_FRAMES,
    SPLIT_CHANNELS,
)
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat.knockback import launch_vector
from isofightr.sim.combat.shield import shield_centre, shield_radius
from isofightr.sim.events import HazardHitEvent, HitEvent, LaunchEvent, ShieldHitEvent
from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.stage import Stage

LIGHT: Final[int] = 0
MEDIUM: Final[int] = 1
HEAVY: Final[int] = 2
CRITICAL: Final[int] = 3
TIER_KNOCKBACK: Final[tuple[float, ...]] = (40.0, 80.0)
"""Knockback at which a hit moves up from light to medium, and from medium to heavy. Only a
forecast KO is critical (decision D-068, agreed: KB 150 is a forward smash at 60%)."""
BURST_TICKS: Final[int] = 2
"""The burst: the contact tick and the next."""
HOLD_FRAMES: Final[int] = CORE_FRAMES
"""Frames of the held core, spread across the rest of the freeze."""
DISPERSAL_TICKS: Final[tuple[int, ...]] = (8, 10, 12, 14)
"""How long the dispersal lasts, by tier."""
PARTICLES: Final[tuple[int, ...]] = (2, 4, 8, 10)
"""Particles the dispersal throws, by tier."""
PARTICLE_SPEED: Final[tuple[float, ...]] = (1.2, 1.6, 2.2, 2.8)
"""A particle's starting speed by tier, in pixels a tick (each varies from 0.6 to 1.4 times)."""
PARTICLE_DRAG: Final[float] = 0.82
"""A particle keeps this share of its speed from one tick to the next."""
PARTICLE_FRAMES: Final[int] = 3
"""A particle's look steps through this many frames over its life."""
SPLIT_OFFSET: Final[int] = 2
"""How far to either side of the burst its chromatic split's copies are drawn, in pixels."""
RING_FRAME_TICKS: Final[int] = 2
"""Ticks each frame of the shockwave ring shows (it starts with the launch)."""
FLARE_FRAME_TICKS: Final[int] = 2
"""Ticks each frame of the critical flare shows (it starts on the contact tick)."""
SCREEN_FLASH_TICKS: Final[int] = 2
"""A critical hit flashes the screen for this many ticks from the contact."""
CONE_DEGREES: Final[tuple[float, ...]] = (30.0, 40.0, 50.0, 60.0)
"""Half the cone the particles fly in around the launch, by tier."""
PARTICLE_RISE: Final[dict[str, float]] = {"fire": 0.08, "earth": -0.14, "ice": -0.05}
"""How fast a theme's particles drift up the screen, in pixels a tick more each tick: embers
rise as they slow, rock chips and leaves fall, flecks of ice settle slowly (themes not
listed fly straight)."""
PARTICLE_CURL: Final[dict[str, float]] = {"wind": 0.16}
"""How fast a theme's particles turn as they fly, in radians a tick (every other one the
other way): wind's wisps curl."""
PARTICLE_ZAG: Final[dict[str, float]] = {"electric": 0.7}
"""How far a theme's particles swerve to one side and then the other on alternate ticks, in
radians: electric sparks fly a zigzag."""
PARTICLE_PULL: Final[dict[str, float]] = {"darkness": 0.07}
"""How fast a theme's particles are drawn back to the contact point, as a share of their
reach lost each tick: darkness's motes fly out and are pulled back in (an implosion)."""
RADIAL_BELOW: Final[float] = 6.0
"""A direction drawn shorter than this many pixels per world unit points (nearly) at the
camera or away from it: such a splash has no direction and spreads all round. A unit across
the screen is 17.9 pixels, straight up 16."""
ANGLES: Final[int] = 16
"""Screen directions the splash is drawn in (22.5 degrees apart, counter-clockwise from right)."""
VIBRATION_PIXELS: Final[int] = 1
"""The held core shakes by this much, every other tick."""
MAX_PER_HIT: Final[int] = 12
"""Sprites one splash may show at once."""
MAX_LIVE: Final[int] = 160
"""Splash sprites that may be on screen at once."""
RING_SPRITES: Final[int] = 1
"""Sprites a heavy splash's dispersal takes besides its particles: the ring."""
GUARD_DAMAGE: Final[tuple[float, ...]] = (5.0, 10.0)
"""Shield damage at which a block's arc grows a size (three sizes)."""
GUARD_SPARKS: Final[tuple[int, ...]] = (2, 3, 4)
"""Sparks a block's arc throws off along the bubble when the freeze ends, by size."""
GUARD_SKITTER_TICKS: Final[int] = 8
"""How long they skitter."""
GUARD_SKITTER_SPEED: Final[float] = 1.6
"""Their starting speed, in pixels a tick (each varies from 0.7 to 1.3 times)."""
GUARD_FADE_TICKS: Final[int] = 4
"""How long the arc's fading frame shows once the freeze is over."""
PARRY_RING_TICKS: Final[int] = 4
"""A parry's ring bursts out over this many ticks, a frame each."""
PARRY_PULSE_TICKS: Final[int] = 4
"""Then it pulses between two frames, this many ticks each, while the attacker is frozen."""
PARRY_FADE_TICKS: Final[int] = 3
"""Then it fades over this many ticks."""
PARRY_LIMIT_TICKS: Final[int] = 40
"""A safety: a parry ring whose attacker is never seen to thaw ends this long after the
parrier's own freeze would have."""
LINGER_TICKS: Final[int] = 4
"""A hold whose freeze is over without a launch being seen ends this many ticks late at most
(a safety: normally the target's own hitlag ends it)."""


class Phase(Enum):
    """Where a splash is in its life."""

    BURST = "burst"
    HOLD = "hold"
    DISPERSAL = "dispersal"
    DONE = "done"


def tier_of(knockback: float, sweet: bool, multi: bool, kills: bool) -> int:
    """Return a hit's tier: the knockback band, one up for a sweetspot (to heavy at most),
    one down for a multi-hit sub-hit (to light at least); critical when it is forecast to KO."""
    if kills:
        return CRITICAL
    tier = sum(knockback >= threshold for threshold in TIER_KNOCKBACK)
    if sweet:
        tier = min(tier + 1, HEAVY)
    if multi:
        tier = max(tier - 1, LIGHT)
    return tier


def theme_of(effect: Effect, hit_theme: str) -> str:
    """Return a hit's theme: its effect, or for a normal hit the attacker's ``hit_theme``
    (``"normal"`` when it has none)."""
    if effect is not Effect.NORMAL:
        return str(effect.value)
    return hit_theme or Effect.NORMAL.value


def screen_turn(direction: Vec3) -> float | None:
    """Return the angle on screen (radians, counter-clockwise from right, y up) of a world
    direction, or ``None`` when it is drawn too short to point anywhere (``RADIAL_BELOW``)."""
    screen_x, screen_y = project(direction.x, direction.y, direction.z)
    if math.hypot(screen_x, screen_y) < RADIAL_BELOW * direction.length():
        return None
    return math.atan2(screen_y, screen_x)


def angle_step(turn: float | None) -> int | None:
    """Return the nearest of the ``ANGLES`` screen directions to ``turn`` (``None`` stays)."""
    if turn is None:
        return None
    return round(turn / (2.0 * math.pi) * ANGLES) % ANGLES


def unit(frame: int, player: int, number: int, salt: int) -> float:
    """Return a fixed number in [0, 1) for a particle: a hash of the hit's match frame, the
    target's player index, the particle's number and what it is for."""
    mixed = mix64(frame & MASK64)
    for part in (player, number, salt):
        mixed = mix64(mixed ^ (part & MASK64))
    return mixed / float(1 << 64)


@dataclass(frozen=True, slots=True)
class Particle:
    """One particle of a dispersal, on screen."""

    turn: float
    """Its direction (radians, counter-clockwise from right, y up)."""
    speed: float
    """Pixels a tick at the start."""
    life: int
    """Ticks it shows."""
    rise: float = 0.0
    """How fast it drifts up the screen (``PARTICLE_RISE``)."""
    pull: float = 0.0
    """How fast it is drawn back to where it started (``PARTICLE_PULL``)."""
    curl: float = 0.0
    """How fast it turns as it flies, in radians a tick (``PARTICLE_CURL``)."""
    zag: float = 0.0
    """How far it swerves either way on alternate ticks, in radians (``PARTICLE_ZAG``)."""

    def heading(self, age: int) -> float:
        """Which way it flies ``age`` ticks after the launch."""
        swerve = self.zag if age % 2 else -self.zag
        return self.turn + self.curl * age + (swerve if self.zag else 0.0)

    def offset(self, age: int) -> tuple[float, float]:
        """Where it is ``age`` ticks after the launch, from the contact point, in pixels."""
        pulled = max(0.0, 1.0 - self.pull * age)
        drift = self.rise * age * (age + 1) / 2.0
        if self.curl or self.zag:
            x = y = 0.0
            step = self.speed
            for tick in range(age):
                x += math.cos(self.heading(tick)) * step
                y += math.sin(self.heading(tick)) * step
                step *= PARTICLE_DRAG
            return x * pulled, y * pulled + drift
        reach = self.speed * (1.0 - PARTICLE_DRAG**age) / (1.0 - PARTICLE_DRAG) * pulled
        return math.cos(self.turn) * reach, math.sin(self.turn) * reach + drift


@dataclass(slots=True)
class HitSplash:
    """One hit's splash."""

    target: int
    attacker: int | None
    contact: Vec3
    hitlag: int
    knockback: float
    effect: Effect
    sweet: bool = False
    multi: bool = False
    theme: str = Effect.NORMAL.value
    tier: int = LIGHT
    angle: int | None = None
    """The pending launch's screen direction (of ``ANGLES``), or ``None``: no direction."""
    frame: int = 0
    """The match frame of the hit (the particles hash it)."""
    resolved: bool = False
    """Whether ``observe`` has read the fighters for it (theme, tier, direction, frame)."""
    age: int = 0
    launched_at: int | None = None
    """Its age when the launch started, if it has."""
    ended_at: int | None = None
    """Its age when the freeze ended without a launch, if it did."""
    particles: tuple[Particle, ...] = ()

    @property
    def phase(self) -> Phase:
        """Where the splash is now."""
        if self.launched_at is not None:
            if self.age - self.launched_at < DISPERSAL_TICKS[self.tier] and self.particles:
                return Phase.DISPERSAL
            return Phase.DONE
        if self.ended_at is not None or self.age >= self.hitlag + LINGER_TICKS:
            return Phase.DONE
        return Phase.BURST if self.age < BURST_TICKS else Phase.HOLD

    @property
    def hold_frame(self) -> int:
        """The held core's frame: its ``HOLD_FRAMES`` spread across the freeze after the burst,
        ``ceil(hold / HOLD_FRAMES)`` ticks each."""
        hold = max(1, self.hitlag - BURST_TICKS)
        step = max(1, -(-hold // HOLD_FRAMES))
        return min(max(0, self.age - BURST_TICKS) // step, HOLD_FRAMES - 1)


@dataclass(slots=True)
class GuardSplash:
    """A blocked or parried hit's splash (decision D-068, group 3)."""

    target: int
    """The defender."""
    attacker: int | None
    position: Vec3
    """Where the blow was: the hitbox's (or the projectile's) centre."""
    hitlag: int
    damage: float
    """Shield damage taken (0 for a parry)."""
    parried: bool
    effect: Effect = Effect.NORMAL
    theme: str = Effect.NORMAL.value
    size: int = 0
    angle: int = 0
    """The screen direction from the bubble's centre out to where the blow met it."""
    screen: tuple[float, float] = (0.0, 0.0)
    """Where the blow met the bubble's outline on screen, in world pixels."""
    surface: Vec3 | None = None
    """The point of the shield sphere facing the blow, in world space (the bubble's ripple
    shows there), once resolved."""
    turn: float = 0.0
    frame: int = 0
    resolved: bool = False
    age: int = 0
    ended_at: int | None = None
    """Its age when the freeze ended (the defender's for a block, the attacker's for a
    parry)."""
    particles: tuple[Particle, ...] = ()

    @property
    def phase(self) -> Phase:
        """Where it is now: burst, hold, then dispersal (the sparks skittering off, or the
        parry ring fading), then done."""
        if self.ended_at is not None:
            if self.parried:
                fade = PARRY_FADE_TICKS
            else:
                fade = (
                    max(GUARD_SKITTER_TICKS, GUARD_FADE_TICKS)
                    if self.particles
                    else GUARD_FADE_TICKS
                )
            return Phase.DISPERSAL if self.age - self.ended_at < fade else Phase.DONE
        if self.age >= self.hitlag + LINGER_TICKS + (PARRY_LIMIT_TICKS if self.parried else 0):
            return Phase.DONE
        burst = PARRY_RING_TICKS if self.parried else BURST_TICKS
        return Phase.BURST if self.age < burst else Phase.HOLD


@dataclass(frozen=True, slots=True)
class SplashSprite:
    """One picture of a splash to draw: its art key and where, in world pixels."""

    key: tuple[str | int, ...]
    x: float
    y: float


@dataclass(slots=True)
class HitSplashes:
    """Every live hit splash, advanced with the battle's effects (:class:`BattleEffects`)."""

    splashes: list[HitSplash] = field(default_factory=list)
    guards: list[GuardSplash] = field(default_factory=list)
    """Blocked and parried hits' splashes."""
    dispersal: bool = True
    """Whether launches throw particles ("Hit effects: Minimal" has none)."""
    forecast: Callable[[Stage, Fighter], bool] = will_ko
    """Whether a fighter's pending launch will KO it (tests and the splash sheet replace it)."""
    calm: bool = False
    """"Reduce flashing": no chromatic split and no screen flash (the battle sets it)."""

    def hit(self, event: HitEvent | HazardHitEvent) -> None:
        """Start a splash for a hit; ``observe`` completes it on the same tick."""
        contact = event.position
        attacker = None
        sweet = multi = False
        if isinstance(event, HitEvent):
            contact = event.contact or event.position
            attacker = event.attacker
            sweet, multi = event.sweet, event.multi
        self.splashes.append(
            HitSplash(
                target=event.target,
                attacker=attacker,
                contact=contact,
                hitlag=event.hitlag,
                knockback=event.knockback,
                effect=event.effect,
                sweet=sweet,
                multi=multi,
            )
        )

    def guard(self, event: ShieldHitEvent | HazardHitEvent) -> GuardSplash:
        """Start the splash of a hit a shield blocked or parried; ``observe`` completes it."""
        if isinstance(event, ShieldHitEvent):
            guard = GuardSplash(
                event.target,
                event.attacker,
                event.position,
                event.hitlag,
                event.damage,
                event.parried,
            )
        else:
            guard = GuardSplash(
                event.target, None, event.position, event.hitlag, event.damage, False, event.effect
            )
        self.guards.append(guard)
        return guard

    def launch(self, event: LaunchEvent) -> list[HitSplash]:
        """The target's freeze ended in a launch: its held splashes disperse along it.
        Returns those splashes."""
        turn = screen_turn(event.direction)
        launched = []
        for splash in self.splashes:
            if splash.target != event.target or splash.phase not in (Phase.BURST, Phase.HOLD):
                continue
            splash.launched_at = splash.age
            splash.particles = self._particles(splash, turn) if self.dispersal else ()
            launched.append(splash)
        return launched

    def observe(self, fighters: Iterable[Fighter], stage: Stage | None, frame: int) -> None:
        """Complete the splashes of this tick's hits from the fighters (the attacker's theme,
        the target's pending launch), and end the holds whose freeze is over without a
        launch. Call once a tick, after the events."""
        by_player = {fighter.player_index: fighter for fighter in fighters}
        for splash in self.splashes:
            target = by_player.get(splash.target)
            if not splash.resolved:
                self._resolve(splash, target, by_player, stage, frame)
            elif splash.phase is Phase.HOLD and (target is None or target.hitlag == 0):
                splash.ended_at = splash.age
        for guard in self.guards:
            if not guard.resolved:
                self._resolve_guard(guard, by_player, frame)
                continue
            watched = guard.attacker if guard.parried else guard.target
            frozen = None if watched is None else by_player.get(watched)
            if guard.phase is Phase.HOLD and (frozen is None or frozen.hitlag == 0):
                guard.ended_at = guard.age
                if not guard.parried and self.dispersal:
                    guard.particles = self._skitter(guard)

    def tick(self) -> None:
        """Advance every splash by one sim tick and drop the finished ones."""
        for splash in self.splashes:
            splash.age += 1
        self.splashes = [splash for splash in self.splashes if splash.phase is not Phase.DONE]
        for guard in self.guards:
            guard.age += 1
        self.guards = [guard for guard in self.guards if guard.phase is not Phase.DONE]

    def clear(self) -> None:
        """Drop every splash (a match restart)."""
        self.splashes = []
        self.guards = []

    def screen_flash(self) -> int:
        """How strong the screen flash is now: 0 none, up to ``SCREEN_FLASH_TICKS`` on a
        critical hit's contact tick, one less each tick after (never with ``calm``)."""
        if self.calm:
            return 0
        flashes = [
            SCREEN_FLASH_TICKS - splash.age
            for splash in self.splashes
            if splash.tier == CRITICAL and splash.launched_at is None and splash.resolved
        ]
        return max([flash for flash in flashes if flash > 0], default=0)

    def live(self) -> int:
        """How many sprites the splashes show now."""
        hits = sum(len(self._sprites_of(splash)) for splash in self.splashes)
        return hits + sum(len(self._guard_sprites(guard)) for guard in self.guards)

    def sprites(self) -> list[SplashSprite]:
        """Every picture to draw now, oldest splash first, at most ``MAX_LIVE``."""
        pictures = [picture for splash in self.splashes for picture in self._sprites_of(splash)]
        pictures += [picture for guard in self.guards for picture in self._guard_sprites(guard)]
        return pictures[-MAX_LIVE:]

    def _resolve(
        self,
        splash: HitSplash,
        target: Fighter | None,
        fighters: dict[int, Fighter],
        stage: Stage | None,
        frame: int,
    ) -> None:
        splash.resolved = True
        splash.frame = frame
        attacker = None if splash.attacker is None else fighters.get(splash.attacker)
        hit_theme = "" if attacker is None else attacker.character.hit_theme
        splash.theme = theme_of(splash.effect, hit_theme)
        launch = None if target is None else target.launch
        kills = False
        if launch is not None and target is not None and stage is not None:
            kills = self.forecast(stage, target)
        splash.tier = tier_of(splash.knockback, splash.sweet, splash.multi, kills)
        if launch is not None:
            splash.angle = angle_step(screen_turn(launch_vector(launch.heading, launch.elevation)))

    def _resolve_guard(self, guard: GuardSplash, fighters: dict[int, Fighter], frame: int) -> None:
        """Find where the blow met the defender's shield bubble on screen: on the outline of
        the bubble as it is drawn, toward where the blow came from (the attacker's side for
        its own swing, the projectile or hazard otherwise)."""
        guard.resolved = True
        guard.frame = frame
        attacker = None if guard.attacker is None else fighters.get(guard.attacker)
        hit_theme = "" if attacker is None else attacker.character.hit_theme
        guard.theme = theme_of(guard.effect, hit_theme)
        guard.size = sum(guard.damage >= threshold for threshold in GUARD_DAMAGE)
        target = fighters.get(guard.target)
        if target is None:
            guard.screen = project(guard.position.x, guard.position.y, guard.position.z)
            return
        centre = shield_centre(target)
        radius = shield_radius(target)
        towards = guard.position - centre
        if attacker is not None and attacker.hitlag > 0:
            # The attacker's own swing (a blocked projectile does not freeze its owner): its
            # hitbox often reaches past the bubble's centre, so the blow came from the
            # attacker's side, at the hitbox's height.
            flat = (attacker.pos - target.pos).xy
            if flat.length() > 1e-9:
                side = flat.normalized()
                rise = max(-1.0, min(1.0, towards.z / max(radius, 1e-9)))
                towards = Vec3(side.x, side.y, rise)
        if towards.length() > 1e-9:
            guard.surface = centre + towards.normalized() * radius
        screen_x, screen_y = project(towards.x, towards.y, towards.z)
        if math.hypot(screen_x, screen_y) < 1e-9:
            screen_x = 1.0
        guard.turn = math.atan2(screen_y, screen_x)
        guard.angle = angle_step(guard.turn) or 0
        centre_x, centre_y = project(centre.x, centre.y, centre.z)
        width, height = sphere_screen_size(radius)
        guard.screen = (
            centre_x + math.cos(guard.turn) * width / 2.0,
            centre_y + math.sin(guard.turn) * height / 2.0,
        )

    def _skitter(self, guard: GuardSplash) -> tuple[Particle, ...]:
        """The sparks a block throws off along the bubble: half each way along it."""
        count = max(0, min(GUARD_SPARKS[guard.size], MAX_LIVE - self.live()))
        sparks = []
        for number in range(count):
            spread, pace = (unit(guard.frame, guard.target, number, salt) for salt in (5, 6))
            side = math.pi / 2.0 if number % 2 else -math.pi / 2.0
            turn = guard.turn + side + (spread - 0.5) * 0.5
            speed = GUARD_SKITTER_SPEED * (0.7 + 0.6 * pace)
            sparks.append(Particle(turn, speed, GUARD_SKITTER_TICKS))
        return tuple(sparks)

    def _particles(self, splash: HitSplash, turn: float | None) -> tuple[Particle, ...]:
        room = MAX_LIVE - self.live()
        ring = RING_SPRITES if splash.tier >= HEAVY else 0
        count = max(0, min(PARTICLES[splash.tier], MAX_PER_HIT - ring, room - ring))
        cone = math.radians(CONE_DEGREES[splash.tier])
        rise = PARTICLE_RISE.get(splash.theme, 0.0)
        pull = PARTICLE_PULL.get(splash.theme, 0.0)
        curl = PARTICLE_CURL.get(splash.theme, 0.0)
        zag = PARTICLE_ZAG.get(splash.theme, 0.0)
        particles = []
        for number in range(count):
            spread, pace, fade = (
                unit(splash.frame, splash.target, number, salt) for salt in range(3)
            )
            if turn is None:
                angle = 2.0 * math.pi * (number + spread) / max(count, 1)
            else:
                angle = turn + (2.0 * spread - 1.0) * cone
            speed = PARTICLE_SPEED[splash.tier] * (0.6 + 0.8 * pace)
            life = DISPERSAL_TICKS[splash.tier] - round(fade * 3.0)
            twist = curl if number % 2 else -curl
            particles.append(Particle(angle, speed, life, rise, pull, twist, zag))
        return tuple(particles)

    def _sprites_of(self, splash: HitSplash) -> list[SplashSprite]:
        """A splash's pictures now, the ones to be drawn underneath first."""
        x, y = project(splash.contact.x, splash.contact.y, splash.contact.z)
        phase = splash.phase
        theme, tier = splash.theme, splash.tier
        pictures: list[SplashSprite] = []
        if phase is Phase.BURST:
            if tier >= HEAVY and not self.calm:
                for channel in range(SPLIT_CHANNELS):
                    shift = SPLIT_OFFSET * (2 * channel - 1)
                    key: tuple[str | int, ...] = ("split", theme, tier, splash.age, channel)
                    pictures.append(SplashSprite(key, x + shift, y))
            pictures.append(SplashSprite(("burst", theme, tier, splash.age), x, y))
        elif phase is Phase.HOLD:
            held = x + VIBRATION_PIXELS * (splash.age % 2)
            angle = -1 if splash.angle is None else splash.angle
            pictures.append(SplashSprite(("core", theme, tier, angle, splash.hold_frame), held, y))
            if splash.angle is not None:
                pictures.append(SplashSprite(("lines", theme, tier, splash.angle), held, y))
        elif phase is Phase.DISPERSAL and splash.launched_at is not None:
            since = splash.age - splash.launched_at
            if tier >= HEAVY and since < RING_FRAMES * RING_FRAME_TICKS:
                key = ("ring", theme, tier, since // RING_FRAME_TICKS)
                pictures.append(SplashSprite(key, x, y))
            size = 1 if tier >= HEAVY else 0
            for particle in splash.particles:
                if since >= particle.life:
                    continue
                dx, dy = particle.offset(since)
                look = min(since * PARTICLE_FRAMES // particle.life, PARTICLE_FRAMES - 1)
                heading = angle_step(particle.heading(since)) or 0
                key = ("particle", theme, size, heading, look)
                pictures.append(SplashSprite(key, x + dx, y + dy))
        flaring = splash.launched_at is None and splash.age < FLARE_FRAMES * FLARE_FRAME_TICKS
        if tier == CRITICAL and flaring and phase is not Phase.DONE:
            pictures.append(SplashSprite(("flare", theme, splash.age // FLARE_FRAME_TICKS), x, y))
        return pictures

    def _guard_sprites(self, guard: GuardSplash) -> list[SplashSprite]:
        """A blocked or parried hit's pictures now."""
        if not guard.resolved:
            return []
        x, y = guard.screen
        phase = guard.phase
        if guard.parried:
            if phase is Phase.BURST:
                frame = guard.age
            elif phase is Phase.HOLD:  # pulsing, unless "reduce flashing" holds it still
                pulse = 0 if self.calm else (guard.age // PARRY_PULSE_TICKS) % 2
                frame = PARRY_RING_TICKS + pulse
            elif phase is Phase.DISPERSAL:
                frame = PARRY_FRAME_COUNT - 1
            else:
                return []
            return [SplashSprite(("parry", "gold", frame), x, y)]
        key = ("guard", guard.theme, guard.size, guard.angle)
        if phase is Phase.BURST:
            return [SplashSprite((*key, guard.age), x, y)]
        if phase is Phase.HOLD:
            return [SplashSprite((*key, 2), x, y)]
        if phase is not Phase.DISPERSAL or guard.ended_at is None:
            return []
        since = guard.age - guard.ended_at
        pictures = [SplashSprite((*key, 3), x, y)] if since < GUARD_FADE_TICKS else []
        for spark in guard.particles:
            if since >= spark.life:
                continue
            dx, dy = spark.offset(since)
            look = min(since * PARTICLE_FRAMES // spark.life, PARTICLE_FRAMES - 1)
            heading = angle_step(spark.heading(since)) or 0
            pictures.append(
                SplashSprite(("particle", guard.theme, 0, heading, look), x + dx, y + dy)
            )
        return pictures


def match_themes(
    characters: Iterable[CharacterDef], hazard_effects: Iterable[Effect] = ()
) -> tuple[str, ...]:
    """Return the themes a match's hits can have, each once, the characters' own first: their
    hit themes, the effects their moves and projectiles carry, and the stage's hazards'."""
    themes: list[str] = []

    def add(theme: str) -> None:
        if theme not in themes:
            themes.append(theme)

    for character in characters:
        add(theme_of(Effect.NORMAL, character.hit_theme))
    for character in characters:
        for move in character.moves.values():
            boxes = [box for window in move.windows for box in window.hitboxes]
            for projectile in move.projectiles:
                boxes.append(projectile.hitbox)
                if projectile.burst is not None:
                    boxes.append(projectile.burst)
            for box in boxes:
                add(theme_of(box.effect, character.hit_theme))
    for effect in hazard_effects:
        add(theme_of(effect, ""))
    return tuple(themes)
