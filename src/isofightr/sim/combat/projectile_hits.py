"""What projectiles hit: fighters, shields, counters, reflectors, attacks and each other.

Plan note "05 - Combat Core" ("Projectiles"). Runs each tick after the fighters' own hits.
A projectile is destroyed by whatever it hits unless it still has pierces left; attacks with
clank-enabled hitboxes can swat it out of the air; a move with a ``reflect`` window sends it
back to its owner.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb_math
from isofightr.sim.combat.hit_resolution import (
    Change,
    block_with_shield,
    counter_reply,
    counter_window_open,
    strike,
    team_multiplier,
)
from isofightr.sim.combat.hitbox import active_hitboxes, hit_damage, hurtbox
from isofightr.sim.combat.shield import is_shielding, shield_volume
from isofightr.sim.combat.staling import push_stale
from isofightr.sim.events import ClankEvent, HitEvent, ShieldHitEvent
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.math3d import ZERO2, capsules_overlap
from isofightr.sim.projectile import Projectile, reflect
from isofightr.sim.states.base import change_state

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def resolve_projectile_hits(match: Match) -> None:
    """Resolve everything this tick's projectiles touch (tick step 7)."""
    _clash_with_each_other(match.projectiles)
    changes: list[Change] = []
    for projectile in match.projectiles:
        if projectile.alive:
            _clash_with_attacks(match, projectile, changes)
        if projectile.alive:
            _hit_fighters(match, projectile, changes)
    for change in changes:
        change()


def _clash_with_each_other(projectiles: list[Projectile]) -> None:
    """Two clank-enabled projectiles of different owners that touch destroy each other."""
    for index, first in enumerate(projectiles):
        for second in projectiles[index + 1 :]:
            if not (first.alive and second.alive) or first.owner == second.owner:
                continue
            if not (first.hitbox.clank and second.hitbox.clank):
                continue
            if capsules_overlap(first.volume, second.volume):
                first.alive = second.alive = False


def _clash_with_attacks(match: Match, projectile: Projectile, changes: list[Change]) -> None:
    """An attack's clank-enabled hitbox destroys a clank-enabled projectile it touches. If
    the projectile was much the stronger, the attacker rebounds as well."""
    if not projectile.hitbox.clank:
        return
    for fighter in match.fighters:
        if fighter.player_index == projectile.owner or not fighter.in_play:
            continue
        for box in active_hitboxes(fighter):
            if not box.definition.clank or not capsules_overlap(box.volume, projectile.volume):
                continue
            projectile.alive = False
            match.events.append(ClankEvent(fighter.player_index, projectile.pos))
            if projectile.damage - hit_damage(fighter, box.definition) >= c.CLANK_DAMAGE_WINDOW:
                changes.append(partial(change_state, match, fighter, StateId.REBOUND))
            return


def _hit_fighters(match: Match, projectile: Projectile, changes: list[Change]) -> None:
    for target in match.fighters:
        if not projectile.alive:
            return
        if not _can_touch(match, projectile, target):
            continue
        move = target.move
        reflecting = move is not None and move.reflect is not None
        if reflecting and move is not None and move.reflect is not None:
            in_window = target.state_frame in move.reflect
            if (
                in_window
                and projectile.definition.reflectable
                and _touches_body(projectile, target)
            ):
                reflect(projectile, target.player_index)
                return
        if is_shielding(target) and capsules_overlap(projectile.volume, shield_volume(target)):
            _blocked(match, projectile, target, changes)
        elif _touches_body(projectile, target):
            if counter_window_open(target):
                changes.append(partial(counter_reply, match, target, None, projectile.damage))
                target.hitlag = max(target.hitlag, _hitlag(projectile))
                projectile.hit.append(target.player_index)
            else:
                _struck(match, projectile, target)
        else:
            continue
        if projectile.pierce_left > 0:
            projectile.pierce_left -= 1
        else:
            projectile.alive = False


def _can_touch(match: Match, projectile: Projectile, target: Fighter) -> bool:
    definition = projectile.hitbox
    owner = match.fighters[projectile.owner]
    if owner.allied_with(target) and not match.rules.friendly_fire:
        return False
    return (
        target.player_index != projectile.owner
        and target.in_play
        and target.ground is not GroundKind.REVIVAL
        and not target.intangible
        and target.player_index not in projectile.hit
        and (definition.hits_ground if target.grounded else definition.hits_air)
    )


def _touches_body(projectile: Projectile, target: Fighter) -> bool:
    return capsules_overlap(projectile.volume, hurtbox(target))


def _hitlag(projectile: Projectile) -> int:
    definition = projectile.hitbox
    return kb_math.hitlag_frames(projectile.damage, definition.hitlag_mult, definition.effect)


def _struck(match: Match, projectile: Projectile, target: Fighter) -> None:
    """The projectile hits a fighter: only the target freezes, the owner is far away."""
    owner = match.fighters[projectile.owner]
    if not projectile.hit:
        push_stale(owner.stale_queue, projectile.move_id)
        owner.dodge_stale = 0
    projectile.hit.append(target.player_index)
    heading = projectile.heading if projectile.heading != ZERO2 else owner.facing.world
    hitlag = _hitlag(projectile)
    target.hitlag = max(target.hitlag, hitlag)
    invincible = target.invincible
    team = team_multiplier(owner, target)
    damage = projectile.damage * team
    knockback = strike(
        target,
        damage,
        projectile.hitbox,
        heading,
        target.grounded,
        rate=match.rules.launch_rate * team,
    )
    match.events.append(
        HitEvent(
            attacker=projectile.owner,
            target=target.player_index,
            move_id=projectile.move_id,
            damage=0.0 if invincible else damage,
            knockback=knockback,
            position=projectile.pos,
            effect=projectile.hitbox.effect,
            hitlag=hitlag,
        )
    )


def _blocked(match: Match, projectile: Projectile, target: Fighter, changes: list[Change]) -> None:
    """The projectile hits a shield: less shieldstun than a direct attack."""
    projectile.hit.append(target.player_index)
    heading = projectile.heading
    if heading == ZERO2:
        heading = match.fighters[projectile.owner].facing.world
    hitlag = _hitlag(projectile)
    target.hitlag = max(target.hitlag, hitlag)
    state, taken = block_with_shield(
        target, projectile.damage, projectile.hitbox, heading, c.PROJECTILE_SHIELDSTUN_MULT
    )
    changes.append(partial(change_state, match, target, state))
    match.events.append(
        ShieldHitEvent(projectile.owner, target.player_index, taken, projectile.pos, hitlag, False)
    )
