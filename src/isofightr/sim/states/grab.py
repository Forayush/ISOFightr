"""Grab states: Grab, DashGrab, GrabHold, Grabbed, Throw and GrabRelease.

Plan note "06 - Shield Dodge Grab and Ledge" ("Grabs and throws"). Who gets grabbed is
decided in :mod:`isofightr.sim.combat.grab`. While holding, the stick picks where the victim
is thrown (the iso twist) and the up/down modifiers pick the up and down throws.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.character_def import ThrowDef
from isofightr.sim.combat import constants as c
from isofightr.sim.combat.grab import apply_throw, grab_def, hold_in_front, unlink
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import NO_PARTNER, Fighter, StateId
from isofightr.sim.input_frame import Press
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import GroundState, State, change_state, register
from isofightr.sim.states.dodge import snapped_direction

if TYPE_CHECKING:
    from isofightr.sim.match import Match

PUMMEL_ID = "pummel"
BACK_THROW_DOT = math.cos(math.radians(c.THROW_BACK_DEGREES))


def partner_of(match: Match, fighter: Fighter) -> Fighter | None:
    """Return the fighter this one holds or is held by, if the link is still intact."""
    if fighter.grab_partner == NO_PARTNER:
        return None
    partner = match.fighters[fighter.grab_partner]
    return partner if partner.grab_partner == fighter.player_index else None


def release_pair(match: Match, first: Fighter, second: Fighter) -> None:
    """Let go: both fighters are pushed apart and lag for a moment (release, or a clash)."""
    unlink(match, first)
    unlink(match, second)
    away = (second.pos - first.pos).xy.normalized()
    if away == Vec2():
        away = first.facing.world
    for fighter, direction in ((first, away * -1.0), (second, away)):
        change_state(match, fighter, StateId.GRAB_RELEASE)
        push = direction * c.GRAB_RELEASE_SPEED
        fighter.vel = Vec3(push.x, push.y, 0.0)


def _free_victim(match: Match, grabber: Fighter) -> None:
    """The grabber was knocked out of the hold: its victim simply stands (or falls) free."""
    victim = unlink(match, grabber)
    if victim is not None and victim.state is StateId.GRABBED:
        change_state(match, victim, StateId.IDLE if victim.grounded else StateId.FALL)


class _Grabbing(GroundState):
    """Reaching out to grab. Whiffing leaves the fighter open until the grab ends."""

    stops_at_edges = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Use up the press that started the grab."""
        fighter.buffer.consume(Press.GRAB)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Recover after the whiff."""
        definition = grab_def(fighter)
        assert definition is not None
        if fighter.state_frame > definition.total:
            interrupts.become_ground_neutral(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """A dash grab slides forward until its grab box is gone; then traction."""
        definition = grab_def(fighter)
        assert definition is not None
        if definition.slide > 0.0 and fighter.state_frame <= definition.frames.last:
            physics.set_ground_velocity(fighter, fighter.facing.world * definition.slide)
        else:
            physics.apply_traction(fighter)


@register
class Grab(_Grabbing):
    """Standing grab (also the grab out of shield)."""

    id = StateId.GRAB


@register
class DashGrab(_Grabbing):
    """Grab out of a dash or run: slides forward, with more lag on a whiff."""

    id = StateId.DASH_GRAB


@register
class GrabHold(GroundState):
    """Holding a grabbed fighter: pummel, throw, or lose it when the timer runs out."""

    id = StateId.GRAB_HOLD
    stops_at_edges = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Stand still with the victim."""
        fighter.vel = ZERO3
        fighter.throw_id = ""

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Leaving for anything but a throw (being hit, say) frees the victim."""
        if fighter.throw_id == "":
            _free_victim(match, fighter)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Run the hold timer and mashing, then act on the grabber's input."""
        victim = partner_of(match, fighter)
        if victim is None:
            interrupts.become_ground_neutral(match, fighter)
            return
        if fighter.pummel_cooldown > 0:
            fighter.pummel_cooldown -= 1
        fighter.grab_timer -= 1
        mashed = victim.buffer.pressed != 0 or victim.buffer.consume(Press.FLICK)
        if mashed:
            fighter.grab_timer -= c.GRAB_MASH_FRAMES
        if fighter.grab_timer <= 0:
            release_pair(match, fighter, victim)
            return
        throw = self._chosen_throw(fighter)
        if throw is not None:
            fighter.throw_id = throw.id
            change_state(match, fighter, StateId.THROW)
        elif fighter.pummel_cooldown == 0 and fighter.buffer.consume(Press.ATTACK):
            self._pummel(match, fighter, victim)

    @staticmethod
    def _chosen_throw(fighter: Fighter) -> ThrowDef | None:
        """Read the throw input. Sets ``fighter.drive`` to the launch heading."""
        buffer = fighter.buffer
        grabs = fighter.character.grabs
        fighter.drive = fighter.facing.world
        if buffer.consume(Press.UP):
            return grabs.up
        if buffer.consume(Press.DOWN):
            return grabs.down
        if not (buffer.stick_active and buffer.consume(Press.FLICK)):
            return None
        direction = snapped_direction(interrupts.stick_direction(fighter))
        if direction == ZERO2:
            return None
        fighter.drive = direction
        if fighter.facing.world.dot(direction) < BACK_THROW_DOT:
            return grabs.back
        interrupts.snap_facing(fighter, direction)
        return grabs.forward

    @staticmethod
    def _pummel(match: Match, fighter: Fighter, victim: Fighter) -> None:
        pummel = fighter.character.grabs.pummel
        victim.damage = min(victim.damage + pummel.damage, c.MAX_DAMAGE)
        fighter.pummel_cooldown = pummel.cooldown
        fighter.hitlag = victim.hitlag = c.PUMMEL_HITLAG
        match.events.append(
            HitEvent(
                attacker=fighter.player_index,
                target=victim.player_index,
                move_id=PUMMEL_ID,
                damage=pummel.damage,
                knockback=0.0,
                position=victim.pos + Vec3(0.0, 0.0, c.SHIELD_CENTRE_HEIGHT),
                effect=Effect.NORMAL,
                hitlag=c.PUMMEL_HITLAG,
            )
        )

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Keep the victim in front."""
        victim = partner_of(match, fighter)
        if victim is not None:
            hold_in_front(fighter, victim)


@register
class Grabbed(State):
    """Held by another fighter, who decides where this one is."""

    id = StateId.GRABBED
    uses_physics = False

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Stop everything: being grabbed ends hitstun and any motion."""
        fighter.vel = ZERO3
        fighter.kb_vel = ZERO3
        fighter.hitstun = 0
        fighter.fast_falling = False

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Whatever ends the hold (a throw, a hit, a release) breaks the link."""
        unlink(match, fighter)

    def step(self, match: Match, fighter: Fighter) -> None:
        """If the grabber is gone for any reason, stand free."""
        if partner_of(match, fighter) is None:
            change_state(match, fighter, StateId.IDLE if fighter.grounded else StateId.FALL)


@register
class Throw(GroundState):
    """Throwing the held fighter. The victim is launched on the throw's release frame."""

    id = StateId.THROW
    stops_at_edges = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """A release on frame 1 happens straight away."""
        self._maybe_release(match, fighter)

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Interrupted before the release: the victim goes free."""
        fighter.throw_id = ""
        _free_victim(match, fighter)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Release on time; recover after the throw."""
        self._maybe_release(match, fighter)
        if fighter.state_frame > self._throw(fighter).total:
            interrupts.become_ground_neutral(match, fighter)

    @staticmethod
    def _throw(fighter: Fighter) -> ThrowDef:
        grabs = fighter.character.grabs
        throws = {throw.id: throw for throw in (grabs.forward, grabs.back, grabs.up, grabs.down)}
        return throws[fighter.throw_id]

    def _maybe_release(self, match: Match, fighter: Fighter) -> None:
        throw = self._throw(fighter)
        victim = partner_of(match, fighter)
        if victim is not None and fighter.state_frame == throw.release:
            apply_throw(match, fighter, victim, throw)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Keep the victim in front until it is launched."""
        physics.apply_traction(fighter)
        victim = partner_of(match, fighter)
        if victim is not None and victim.launch is None:
            hold_in_front(fighter, victim)


@register
class GrabRelease(GroundState):
    """Pushed apart after a grab release or a grab clash."""

    id = StateId.GRAB_RELEASE

    def step(self, match: Match, fighter: Fighter) -> None:
        """Recover after the lag."""
        if fighter.state_frame > c.GRAB_RELEASE_FRAMES:
            if fighter.grounded:
                interrupts.become_ground_neutral(match, fighter)
            else:
                change_state(match, fighter, StateId.FALL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Slide on the ground; fall if released over the edge."""
        if fighter.grounded:
            physics.apply_traction(fighter)
        else:
            physics.apply_gravity(fighter)

    def on_leave_ground(self, match: Match, fighter: Fighter) -> None:
        """Released past an edge: keep lagging while falling (an air release)."""

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Landing does not cut the lag short."""
