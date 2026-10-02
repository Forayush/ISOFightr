"""Grab helpers: grab boxes, who may be grabbed, holding, and applying throws.

Plan note "06 - Shield Dodge Grab and Ledge" ("Grabs and throws"). Grab boxes ignore shields
and only take grounded targets that can be touched. Which grabs connect each tick is decided
in :mod:`isofightr.sim.combat.grab_resolution`; the states are in
:mod:`isofightr.sim.states.grab`. Nothing here changes a fighter's state, so the state
modules can import it freely.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from isofightr.sim.character_def import GrabDef, ThrowDef
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb_math
from isofightr.sim.combat.hitbox import local_to_world
from isofightr.sim.combat.staling import push_stale, stale_multiplier
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import NO_PARTNER, Fighter, GroundKind, Launch, StateId
from isofightr.sim.math3d import ZERO3, Capsule, Vec2, Vec3
from isofightr.sim.move_def import Effect

if TYPE_CHECKING:
    from isofightr.sim.match import Match

GRABBING_STATES = {StateId.GRAB: False, StateId.DASH_GRAB: True}
"""States with a grab box, and whether each uses the dash grab."""
UNGRABBABLE_STATES = frozenset(
    {StateId.GRAB_HOLD, StateId.GRABBED, StateId.THROW, StateId.GRAB_RELEASE}
)
STANDING_KINDS = (GroundKind.CELL, GroundKind.PLATFORM)
THROW_HITLAG = 1
"""A thrown fighter is frozen for one frame, so its DI is read like after any other hit."""


def grab_def(fighter: Fighter) -> GrabDef | None:
    """Return the grab a fighter is performing, or ``None``."""
    dash = GRABBING_STATES.get(fighter.state)
    if dash is None:
        return None
    grabs = fighter.character.grabs
    return grabs.dash if dash else grabs.standing


def grab_box(fighter: Fighter) -> Capsule | None:
    """Return the fighter's grab sphere if it is out this tick."""
    definition = grab_def(fighter)
    if definition is None or fighter.state_frame not in definition.frames:
        return None
    centre = local_to_world(fighter.pos, fighter.facing.world, definition.offset)
    return Capsule(centre, centre, definition.radius)


def can_be_grabbed(target: Fighter) -> bool:
    """Return whether a grab box may take this fighter."""
    return (
        target.in_play
        and target.ground in STANDING_KINDS
        and not target.intangible
        and not target.invincible
        and target.launch is None
        and target.state not in UNGRABBABLE_STATES
    )


def hold_frames(target_damage: float) -> int:
    """Return how long a grab holds a target before it breaks free by itself."""
    return math.floor(c.GRAB_HOLD_BASE_FRAMES + target_damage * c.GRAB_HOLD_PER_DAMAGE)


def hold_in_front(grabber: Fighter, target: Fighter) -> None:
    """Place the held fighter in front of the grabber, on the same ground."""
    offset = grabber.facing.world * c.GRAB_HOLD_DISTANCE
    target.pos = Vec3(grabber.pos.x + offset.x, grabber.pos.y + offset.y, grabber.pos.z)
    target.ground = grabber.ground
    target.platform = grabber.platform
    target.vel = ZERO3
    target.kb_vel = ZERO3


def unlink(match: Match, fighter: Fighter) -> Fighter | None:
    """Break a grab pair's link without changing anyone's state. Returns the partner."""
    if fighter.grab_partner == NO_PARTNER:
        return None
    partner = match.fighters[fighter.grab_partner]
    fighter.grab_partner = NO_PARTNER
    if partner.grab_partner == fighter.player_index:
        partner.grab_partner = NO_PARTNER
        return partner
    return None


def apply_throw(match: Match, grabber: Fighter, target: Fighter, throw: ThrowDef) -> None:
    """Damage and launch a held fighter (the throw's release frame).

    The launch goes through the usual knockback formula and waits one frame of hitlag, so
    the thrown fighter can DI it.
    """
    damage = throw.damage * stale_multiplier(grabber.stale_queue, throw.id)
    push_stale(grabber.stale_queue, throw.id)
    target.damage = min(target.damage + damage, c.MAX_DAMAGE)
    knockback = kb_math.knockback(
        target.damage, damage, target.character.weight, throw.bkb, throw.kbg
    )
    heading = grabber.drive if grabber.drive != Vec2() else grabber.facing.world
    target.launch = Launch(
        knockback=knockback,
        heading=heading,
        elevation=kb_math.resolve_elevation(throw.angle, knockback, target_grounded=True),
        tumble=kb_math.is_tumble(knockback),
    )
    target.sdi_mult = 0.0
    target.hitlag = THROW_HITLAG
    target.last_knockback = knockback
    grabber.dodge_stale = 0
    match.events.append(
        HitEvent(
            attacker=grabber.player_index,
            target=target.player_index,
            move_id=throw.id,
            damage=damage,
            knockback=knockback,
            position=target.pos + Vec3(0.0, 0.0, c.SHIELD_CENTRE_HEIGHT),
            effect=Effect.NORMAL,
            hitlag=THROW_HITLAG,
        )
    )
