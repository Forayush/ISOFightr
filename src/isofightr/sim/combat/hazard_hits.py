"""What a stage's hazards do to the fighters (decision D-063).

Plan note "11 - Stages" ("Hazards"). A ``geyser`` or ``lightning`` is a stage-owned hit: it
uses the same damage, knockback, shield and hitlag code as an attack, hits each fighter once
per time it goes off, freezes only the fighter it hits, and belongs to nobody (it changes no
KO credit: a fighter knocked out by one alone has destroyed itself). A ``wind`` hits nothing:
:func:`wind_push` says how far it carries a fighter this frame.

Everything is a function of the match frame; the only state is each fighter's record of the
activation that last hit it (``Fighter.hazard_hits``, in the state hash).
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from isofightr.sim.combat import knockback as kb_math
from isofightr.sim.combat.hit_resolution import Change, block_with_shield, strike
from isofightr.sim.combat.shield import is_shielding
from isofightr.sim.constants import HAZARD_SHIELDSTUN_MULT
from isofightr.sim.events import HazardHitEvent
from isofightr.sim.fighter import Fighter, GroundKind
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3
from isofightr.sim.stage import Hazard, Stage
from isofightr.sim.states.base import change_state

if TYPE_CHECKING:
    from isofightr.sim.match import Match

WIND: str = "wind"


def resolve_hazard_hits(match: Match) -> None:
    """Hit every fighter standing in a hazard that is active this frame (tick step 7, after
    the fighters' own hits and the projectiles')."""
    changes: list[Change] = []
    for index, hazard in enumerate(match.stage.hazards):
        if hazard.hitbox is None or not hazard.is_active(match.frame):
            continue
        activation = hazard.moment(match.frame)[2]
        for target in match.fighters:
            if _can_touch(hazard, target) and target.hazard_hits.get(index) != activation:
                target.hazard_hits[index] = activation
                _hit(match, index, hazard, target, changes)
    for change in changes:
        change()


def _can_touch(hazard: Hazard, target: Fighter) -> bool:
    body = target.character.body
    return (
        target.in_play
        and target.ground is not GroundKind.REVIVAL
        and not target.intangible
        and hazard.touches(target.pos, body.radius, body.height)
    )


def _away(hazard: Hazard, target: Fighter) -> Vec2:
    """Return the ground direction from the hazard's middle to a fighter (the way it is
    facing, turned round, if it stands dead centre)."""
    gap = target.pos.xy - Vec2(hazard.x, hazard.y)
    if gap == ZERO2:
        return target.facing.world * -1.0
    return gap.normalized()


def _hit(match: Match, index: int, hazard: Hazard, target: Fighter, changes: list[Change]) -> None:
    hitbox = hazard.hitbox
    assert hitbox is not None
    damage = hitbox.damage
    hitlag = kb_math.hitlag_frames(damage, hitbox.hitlag_mult, hitbox.effect)
    target.hitlag = max(target.hitlag, hitlag)
    heading = _away(hazard, target)
    position = Vec3(target.pos.x, target.pos.y, target.pos.z + target.character.body.height / 2)
    if is_shielding(target):
        state, taken = block_with_shield(target, damage, hitbox, heading, HAZARD_SHIELDSTUN_MULT)
        changes.append(partial(change_state, match, target, state))
        match.events.append(
            HazardHitEvent(
                index,
                hazard.kind,
                target.player_index,
                taken,
                0.0,
                position,
                hitbox.effect,
                hitlag,
                True,
            )
        )
        return
    invincible = target.invincible
    knockback = strike(
        target, damage, hitbox, heading, target.grounded, rate=match.rules.launch_rate
    )
    match.events.append(
        HazardHitEvent(
            index,
            hazard.kind,
            target.player_index,
            0.0 if invincible else damage,
            knockback,
            position,
            hitbox.effect,
            hitlag,
            False,
        )
    )


def wind_push(stage: Stage, frame: int, fighter: Fighter) -> Vec3:
    """Return how far the stage's winds carry a fighter this frame (zero outside them)."""
    push = ZERO3
    body = fighter.character.body
    for hazard in stage.hazards:
        if (
            hazard.kind == WIND
            and hazard.is_active(frame)
            and hazard.touches(fighter.pos, body.radius, body.height)
        ):
            push = push + hazard.push
    return push
