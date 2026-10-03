"""What a CPU perceives: a read-only copy of the match taken once per tick.

Plan note "15 - CPU AI" ("Perception"). A CPU never holds on to the live ``Match``: each tick
it copies the few values it reasons about into these frozen views and keeps a short history
of them, so it can look at its opponents as they were ``reaction_frames`` ago while it knows
its own state as it is now. Building a view only reads the match, so a CPU cannot change the
simulation except through the ``InputFrame``s it returns.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from dataclasses import dataclass

from isofightr.sim.fighter import NO_PARTNER, Fighter, GroundKind, Launch, StateId
from isofightr.sim.input_frame import Dir8
from isofightr.sim.match import Match
from isofightr.sim.math3d import Vec3
from isofightr.sim.rules import MatchPhase

FREE_GROUND_STATES = frozenset(
    {StateId.IDLE, StateId.WALK, StateId.DASH, StateId.RUN, StateId.REVIVAL}
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


@dataclass(frozen=True, slots=True)
class WorldView:
    """The match on one tick."""

    frame: int
    playing: bool
    """False during the countdown (input is ignored) and after the match is over."""
    fighters: tuple[FighterView, ...]
    projectiles: tuple[ProjectileView, ...]


def view_fighter(fighter: Fighter) -> FighterView:
    """Copy what a CPU reasons about from one fighter."""
    move = fighter.move
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
    )


def observe(match: Match) -> WorldView:
    """Take a read-only snapshot of the match."""
    return WorldView(
        frame=match.frame,
        playing=match.phase is MatchPhase.PLAYING,
        fighters=tuple(view_fighter(fighter) for fighter in match.fighters),
        projectiles=tuple(
            ProjectileView(
                owner=projectile.owner,
                pos=projectile.pos,
                vel=projectile.vel,
                radius=projectile.hitbox.radius,
            )
            for projectile in match.projectiles
            if projectile.alive
        ),
    )
