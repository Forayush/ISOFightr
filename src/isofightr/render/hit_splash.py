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
from isofightr.render.splash_art import CORE_FRAMES, FLARE_FRAMES, RING_FRAMES, SPLIT_CHANNELS
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat.knockback import launch_vector
from isofightr.sim.events import HazardHitEvent, HitEvent, LaunchEvent
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
PARTICLE_RISE: Final[dict[str, float]] = {"fire": 0.08}
"""How fast a theme's particles drift up the screen, in pixels a tick more each tick: embers
rise as they slow (themes not listed fly straight)."""
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
        return effect.value
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

    def offset(self, age: int) -> tuple[float, float]:
        """Where it is ``age`` ticks after the launch, from the contact point, in pixels."""
        reach = self.speed * (1.0 - PARTICLE_DRAG**age) / (1.0 - PARTICLE_DRAG)
        drift = self.rise * age * (age + 1) / 2.0
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

    def launch(self, event: LaunchEvent) -> None:
        """The target's freeze ended in a launch: its held splashes disperse along it."""
        turn = screen_turn(event.direction)
        for splash in self.splashes:
            if splash.target != event.target or splash.phase not in (Phase.BURST, Phase.HOLD):
                continue
            splash.launched_at = splash.age
            splash.particles = self._particles(splash, turn) if self.dispersal else ()

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

    def tick(self) -> None:
        """Advance every splash by one sim tick and drop the finished ones."""
        for splash in self.splashes:
            splash.age += 1
        self.splashes = [splash for splash in self.splashes if splash.phase is not Phase.DONE]

    def clear(self) -> None:
        """Drop every splash (a match restart)."""
        self.splashes = []

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
        return sum(len(self._sprites_of(splash)) for splash in self.splashes)

    def sprites(self) -> list[SplashSprite]:
        """Every picture to draw now, oldest splash first, at most ``MAX_LIVE``."""
        pictures = [picture for splash in self.splashes for picture in self._sprites_of(splash)]
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

    def _particles(self, splash: HitSplash, turn: float | None) -> tuple[Particle, ...]:
        room = MAX_LIVE - self.live()
        ring = RING_SPRITES if splash.tier >= HEAVY else 0
        count = max(0, min(PARTICLES[splash.tier], MAX_PER_HIT - ring, room - ring))
        cone = math.radians(CONE_DEGREES[splash.tier])
        rise = PARTICLE_RISE.get(splash.theme, 0.0)
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
            particles.append(Particle(angle, speed, life, rise))
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
                    key = ("split", theme, tier, splash.age, channel)
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
                heading = angle_step(particle.turn) or 0
                key = ("particle", theme, size, heading, look)
                pictures.append(SplashSprite(key, x + dx, y + dy))
        flaring = splash.launched_at is None and splash.age < FLARE_FRAMES * FLARE_FRAME_TICKS
        if tier == CRITICAL and flaring and phase is not Phase.DONE:
            pictures.append(SplashSprite(("flare", theme, splash.age // FLARE_FRAME_TICKS), x, y))
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
