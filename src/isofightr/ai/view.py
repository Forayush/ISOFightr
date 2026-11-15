"""What a CPU perceives: a read-only copy of the match taken once per tick.

Plan note "15 - CPU AI" ("Perception"). A CPU never holds on to the live ``Match``: each tick
it copies the few values it reasons about into these frozen views and keeps a short history
of them, so it can look at its opponents as they were ``reaction_frames`` ago while it knows
its own state as it is now. Building a view only reads the match, so a CPU cannot change the
simulation except through the ``InputFrame``s it returns.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from dataclasses import dataclass

from isofightr.sim.character_def import HurtboxDef
from isofightr.sim.combat.hitbox import hurtbox_shape
from isofightr.sim.fighter import NO_PARTNER, NO_TEAM, Fighter, GroundKind, Launch, StateId
from isofightr.sim.input_frame import Dir8
from isofightr.sim.match import Match
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.rules import MatchPhase, PlayerStats

FREE_GROUND_STATES = frozenset(
    {StateId.IDLE, StateId.WALK, StateId.DASH, StateId.RUN, StateId.REVIVAL, StateId.CROUCH}
)
"""Grounded states in which a fresh press starts something at once."""
FREE_AIR_STATES = frozenset({StateId.FALL, StateId.JUMP, StateId.DOUBLE_JUMP})
"""Airborne states in which a fresh press starts an aerial, special, dodge or jump."""


@dataclass(frozen=True, slots=True)
class FighterView:
    """One fighter as a CPU sees it."""

    index: int
    character_id: str
    pos: Vec3
    vel: Vec3
    """Total velocity: self motion plus knockback."""
    facing: Dir8
    state: StateId
    state_frame: int
    move_id: str
    """The move being performed (only meaningful in ``ATTACK``)."""
    grounded: bool
    on_platform: bool
    """Standing on a soft platform (it can drop through)."""
    in_play: bool
    damage: float
    weight: float
    team: int
    air_jumps_left: int
    hitlag: int
    hitstun: int
    land_lag: int
    launch: Launch | None
    intangible: bool
    invincible: bool
    air_dodge_used: bool
    tech_window: int
    tech_lockout: int
    grab_partner: int
    ledge_cooldown: int
    stun_frames: int
    move_faf: int
    """First actionable frame of the current move, 0 outside an attack."""
    hurtbox: HurtboxDef
    """The capsule it is hit with now (lower while crouching or in a down tilt, D-069)."""
    # --- added in M20 (decision D-071); nothing the M10 decisions read ---
    kb_vel: Vec3 = ZERO3
    """The knockback part of ``vel``: what a launch is still carrying it with."""
    shield_hp: float = 0.0
    stocks: int | None = None
    """Stocks left, or ``None`` when they are infinite."""
    score: int = 0
    """KOs minus falls so far (what a timed match is decided by)."""
    charge_frames: int = 0
    """How long the smash it is performing has been charged."""
    stored_charge: int = 0
    """Charge kept for later (Mote's Ember Orb)."""
    armored: bool = False
    """Its move has armor on this frame: a weak hit will not stop it."""
    countering: bool = False
    """It is inside a counter window: hitting it now gets answered."""
    reflecting: bool = False
    """It sends reflectable projectiles back on this frame."""

    @property
    def free(self) -> bool:
        """Whether a fresh press would start something right now."""
        if self.hitlag > 0:
            return False
        if self.state is StateId.ATTACK:
            return self.move_faf > 0 and self.state_frame >= self.move_faf
        if self.state is StateId.TUMBLE:
            return self.hitstun <= 0 and not self.grounded
        if self.state in FREE_AIR_STATES:
            return self.state is not StateId.JUMP or self.state_frame > 1
        return self.state in FREE_GROUND_STATES

    @property
    def holding(self) -> bool:
        """Whether this fighter is holding someone in a grab."""
        return self.state is StateId.GRAB_HOLD and self.grab_partner != NO_PARTNER


@dataclass(frozen=True, slots=True)
class ProjectileView:
    """A projectile in flight."""

    owner: int
    pos: Vec3
    vel: Vec3
    radius: float
    # --- added in M20 ---
    damage: float = 0.0
    team: int = NO_TEAM
    """Its owner's team (``NO_TEAM`` in a free-for-all)."""
    move_id: str = ""
    reflectable: bool = False
    trap: bool = False
    """It does not fly: it waits where it was put."""


@dataclass(frozen=True, slots=True)
class HazardView:
    """A stage hazard on this tick (decision D-063): where it is and what it is doing."""

    index: int
    kind: str
    pos: Vec3
    radius: float
    height: float
    phase: str
    """``"rest"``, ``"warn"`` or ``"active"``."""
    frames_to_active: int
    """Frames until it next turns active (0 while it is)."""
    frames_left: int
    """While active: frames until it rests again (0 otherwise)."""
    hits: bool
    """It damages and launches (a geyser, lightning); otherwise it only pushes (wind)."""
    push: Vec3


@dataclass(frozen=True, slots=True)
class PlatformView:
    """A soft platform that moves, where it is on this tick."""

    x0: float
    y0: float
    x1: float
    y1: float
    z: float
    step: Vec3
    """How far it moved since the tick before."""


@dataclass(frozen=True, slots=True)
class WorldView:
    """The match on one tick."""

    frame: int
    playing: bool
    """False during the countdown (input is ignored) and after the match is over."""
    fighters: tuple[FighterView, ...]
    projectiles: tuple[ProjectileView, ...]
    # --- added in M20 ---
    hazards: tuple[HazardView, ...] = ()
    """The stage's hazards, empty when the match has its mechanics off."""
    platforms: tuple[PlatformView, ...] = ()
    """The soft platforms that move (the ones at rest are in the stage)."""
    time_left: int | None = None
    """Frames left on the clock, or ``None`` without one."""
    sudden_death: bool = False


def view_fighter(fighter: Fighter, stats: PlayerStats | None = None) -> FighterView:
    """Copy what a CPU reasons about from one fighter (``stats`` gives its score)."""
    move = fighter.move
    frame = fighter.state_frame
    attacking = move is not None and fighter.state is StateId.ATTACK
    return FighterView(
        index=fighter.player_index,
        character_id=fighter.character.id,
        pos=fighter.pos,
        vel=fighter.vel + fighter.kb_vel,
        facing=fighter.facing,
        state=fighter.state,
        state_frame=fighter.state_frame,
        move_id=fighter.move_id if fighter.state is StateId.ATTACK else "",
        grounded=fighter.grounded,
        on_platform=fighter.ground is GroundKind.PLATFORM,
        in_play=fighter.in_play,
        damage=fighter.damage,
        weight=fighter.character.weight,
        team=fighter.team,
        air_jumps_left=fighter.air_jumps_left,
        hitlag=fighter.hitlag,
        hitstun=fighter.hitstun,
        land_lag=fighter.land_lag,
        launch=fighter.launch,
        intangible=fighter.intangible,
        invincible=fighter.invincible,
        air_dodge_used=fighter.air_dodge_used,
        tech_window=fighter.tech_window,
        tech_lockout=fighter.tech_lockout,
        grab_partner=fighter.grab_partner,
        ledge_cooldown=fighter.ledge_cooldown,
        stun_frames=fighter.stun_frames,
        move_faf=move.faf if move is not None else 0,
        hurtbox=hurtbox_shape(fighter),
        kb_vel=fighter.kb_vel,
        shield_hp=fighter.shield_hp,
        stocks=fighter.stocks,
        score=stats.score if stats is not None else 0,
        charge_frames=fighter.charge_frames,
        stored_charge=fighter.stored_charge,
        armored=attacking and move is not None and move.armor_threshold(frame) is not None,
        countering=attacking
        and move is not None
        and move.counter is not None
        and frame in move.counter.frames,
        reflecting=attacking
        and move is not None
        and move.reflect is not None
        and frame in move.reflect,
    )


def _hazards(match: Match) -> tuple[HazardView, ...]:
    if not match.rules.stage_hazards or not match.stage.hazards:
        return ()
    out = []
    for index, hazard in enumerate(match.stage.hazards):
        phase, inside, _turn = hazard.moment(match.frame)
        if phase == "active":
            to_active, left = 0, hazard.active - inside
        elif phase == "warn":
            to_active, left = hazard.warn - inside, 0
        else:
            to_active, left = hazard.rest - inside + hazard.warn, 0
        out.append(
            HazardView(
                index=index,
                kind=hazard.kind,
                pos=Vec3(hazard.x, hazard.y, hazard.z),
                radius=hazard.radius,
                height=hazard.height,
                phase=phase,
                frames_to_active=to_active,
                frames_left=left,
                hits=hazard.hitbox is not None,
                push=hazard.push,
            )
        )
    return tuple(out)


def _platforms(match: Match) -> tuple[PlatformView, ...]:
    if not match.rules.stage_hazards:
        return ()
    return tuple(
        PlatformView(p.x0, p.y0, p.x1, p.y1, p.z, p.step)
        for p in match.stage.soft_platforms
        if p.motion is not None
    )


def observe(match: Match) -> WorldView:
    """Take a read-only snapshot of the match."""
    fighters = match.fighters
    return WorldView(
        frame=match.frame,
        playing=match.phase is MatchPhase.PLAYING,
        fighters=tuple(
            view_fighter(fighter, match.stats[fighter.player_index]) for fighter in fighters
        ),
        projectiles=tuple(
            ProjectileView(
                owner=projectile.owner,
                pos=projectile.pos,
                vel=projectile.vel,
                radius=projectile.hitbox.radius,
                damage=projectile.damage,
                team=fighters[projectile.owner].team,
                move_id=projectile.move_id,
                reflectable=projectile.definition.reflectable,
                trap=projectile.definition.speed == 0.0 and projectile.definition.rise == 0.0,
            )
            for projectile in match.projectiles
            if projectile.alive
        ),
        hazards=_hazards(match),
        platforms=_platforms(match),
        time_left=match.time_left,
        sudden_death=match.sudden_death,
    )
