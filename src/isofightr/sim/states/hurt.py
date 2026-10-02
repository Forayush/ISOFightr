"""Hurt and recovery states: Flinch, Tumble, teching, Knockdown and the getup options.

Plan notes "05 - Combat Core" (hitstun, tumble at 80 knockback) and "06 - Shield Dodge Grab
and Ledge" ("Teching and knockdown"). A tumbling fighter that presses shield shortly before
touching the ground or a wall techs; otherwise it is knocked down, or bounces off the wall.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.events import TechEvent, WallBounceEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_NONE, Button, Press
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import GroundState, State, change_state, register
from isofightr.sim.states.dodge import roll_velocity, snapped_direction

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def _refill(fighter: Fighter) -> None:
    fighter.air_jumps_left = fighter.character.movement.air_jumps
    fighter.fast_falling = False


@register
class Flinch(State):
    """Hitstun from a hit below tumble knockback: stunned, then free to act."""

    id = StateId.FLINCH

    def step(self, match: Match, fighter: Fighter) -> None:
        """Count down hitstun, then hand control back."""
        fighter.hitstun -= 1
        if fighter.hitstun > 0:
            return
        fighter.hitstun = 0
        if fighter.grounded:
            interrupts.become_ground_neutral(match, fighter)
        else:
            change_state(match, fighter, StateId.FALL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Slide on the ground; in the air, fall with reduced drift."""
        if fighter.grounded:
            physics.apply_traction(fighter)
        else:
            physics.apply_gravity(fighter, c.HITSTUN_GRAVITY_MULT)
            physics.apply_air_drift(fighter, c.HITSTUN_DRIFT_MULT)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Landing does not end hitstun: keep flinching on the ground."""
        _refill(fighter)

    def on_leave_ground(self, match: Match, fighter: Fighter) -> None:
        """Sliding off an edge does not end hitstun either."""


@register
class Tumble(State):
    """Launched hard enough to tumble: helpless during hitstun, and landing needs a tech."""

    id = StateId.TUMBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """During hitstun a shield press opens the tech window; afterwards an air jump,
        an aerial or an air dodge escapes the tumble."""
        if fighter.hitstun > 0:
            fighter.hitstun -= 1
            buffer = fighter.buffer
            if buffer.pressed & Button.SHIELD:
                buffer.consume(Press.SHIELD)  # a tech attempt, never a late air dodge
                if fighter.tech_lockout == 0:
                    fighter.tech_window = c.TECH_WINDOW
                    fighter.tech_lockout = c.TECH_LOCKOUT
            return
        interrupts.run_interrupts(match, fighter, interrupts.AIR_NEUTRAL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Fall; gravity and drift are reduced while still in hitstun."""
        stunned = fighter.hitstun > 0
        physics.apply_gravity(fighter, c.HITSTUN_GRAVITY_MULT if stunned else 1.0)
        physics.apply_air_drift(fighter, c.HITSTUN_DRIFT_MULT if stunned else 1.0)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Hit the ground: tech (in place, or rolling with the stick), or be knocked down."""
        if fighter.tech_window <= 0:
            change_state(match, fighter, StateId.KNOCKDOWN)
            return
        fighter.tech_window = 0
        match.events.append(TechEvent(fighter.player_index, fighter.pos, wall=False))
        rolling = fighter.buffer.stick_active
        change_state(match, fighter, StateId.TECH_ROLL if rolling else StateId.TECH)

    def on_wall(self, match: Match, fighter: Fighter, normal: Vec2, knockback: Vec3) -> None:
        """Hit a wall while in hitstun: tech it, or bounce off and take a little damage."""
        if fighter.hitstun <= 0:
            return
        if fighter.tech_window > 0:
            fighter.tech_window = 0
            match.events.append(TechEvent(fighter.player_index, fighter.pos, wall=True))
            change_state(match, fighter, StateId.WALL_TECH)
            return
        into_wall = -knockback.xy.dot(normal)
        if into_wall < c.WALL_BOUNCE_MIN_SPEED:
            return
        bounce = normal * (into_wall * c.WALL_BOUNCE_KEEP)
        fighter.kb_vel = fighter.kb_vel + Vec3(bounce.x, bounce.y, 0.0)
        fighter.damage = min(fighter.damage + c.WALL_BOUNCE_DAMAGE, c.MAX_DAMAGE)
        match.events.append(WallBounceEvent(fighter.player_index, fighter.pos))


def _begin_tech(fighter: Fighter, intangible: int) -> None:
    fighter.hitstun = 0
    fighter.vel = ZERO3
    fighter.kb_vel = ZERO3
    fighter.intangible_frames = intangible
    _refill(fighter)


@register
class Tech(GroundState):
    """Teched the ground in place: back on its feet almost at once."""

    id = StateId.TECH
    stops_at_edges = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Stop dead, intangible."""
        _begin_tech(fighter, c.TECH_INTANGIBLE)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Recover."""
        if fighter.state_frame > c.TECH_FRAMES:
            interrupts.become_ground_neutral(match, fighter)


class _GroundRoll(GroundState):
    """A roll along the ground in the stick's direction (tech roll, getup roll)."""

    stops_at_edges = True
    frames = 0
    distance = 0.0
    intangible = 0
    first_moving_frame = 1

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Lock the direction to the stick, snapped to eight ways; intangible."""
        _begin_tech(fighter, self.intangible)
        fighter.drive = snapped_direction(interrupts.stick_direction(fighter))
        fighter.buffer.consume(Press.FLICK)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Recover."""
        if fighter.state_frame > self.frames:
            interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Travel over the whole intangible part of the roll."""
        first = self.first_moving_frame
        window = (first, first + self.intangible - 1)
        velocity = roll_velocity(fighter.state_frame, window, fighter.drive, self.distance)
        physics.set_ground_velocity(fighter, velocity)


@register
class TechRoll(_GroundRoll):
    """Teched the ground and rolled away."""

    id = StateId.TECH_ROLL
    frames = c.TECH_ROLL_FRAMES
    distance = c.TECH_ROLL_DISTANCE
    intangible = c.TECH_INTANGIBLE
    first_moving_frame = 2  # entered on landing, after that tick's motion


@register
class GetupRoll(_GroundRoll):
    """Rolling away while getting up from a knockdown."""

    id = StateId.GETUP_ROLL
    frames = c.GETUP_ROLL_FRAMES
    distance = c.GETUP_ROLL_DISTANCE
    intangible = c.GETUP_ROLL_INTANGIBLE


@register
class WallTech(State):
    """Teched a wall: stuck to it for a moment, then falling free."""

    id = StateId.WALL_TECH

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Stop dead against the wall, intangible."""
        fighter.hitstun = 0
        fighter.vel = ZERO3
        fighter.kb_vel = ZERO3
        fighter.intangible_frames = c.WALL_TECH_INTANGIBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Let go of the wall."""
        if fighter.state_frame > c.WALL_TECH_FRAMES:
            change_state(match, fighter, StateId.FALL)


@register
class Knockdown(GroundState):
    """Lying on the ground after a missed tech."""

    id = StateId.KNOCKDOWN

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Hitstun is over once the fighter is down."""
        fighter.hitstun = 0
        _refill(fighter)

    def step(self, match: Match, fighter: Fighter) -> None:
        """After the lock: attack gets up attacking, a stick flick rolls, anything else
        stands up. Gets up by itself after the maximum."""
        frame = fighter.state_frame
        if frame <= c.KNOCKDOWN_LOCK_FRAMES:
            return
        buffer = fighter.buffer
        if buffer.consume(Press.ATTACK):
            interrupts.start_move(match, fighter, fighter.character.moveset.getup_attack)
        elif buffer.stick_active and buffer.has(Press.FLICK):
            change_state(match, fighter, StateId.GETUP_ROLL)
        elif (
            frame > c.KNOCKDOWN_MAX_FRAMES
            or buffer.stick_active
            or buffer.frame.held != 0
            or buffer.vertical != VERTICAL_NONE
        ):
            change_state(match, fighter, StateId.GETUP)


@register
class Getup(GroundState):
    """Standing back up from a knockdown."""

    id = StateId.GETUP

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Intangible at first."""
        fighter.intangible_frames = c.GETUP_INTANGIBLE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Back to neutral once up."""
        if fighter.state_frame > c.GETUP_FRAMES:
            interrupts.become_ground_neutral(match, fighter)
