"""Grab resolution: which grabs connect this tick, and grab clashes.

Plan note "06 - Shield Dodge Grab and Ledge" ("Grabs and throws"). Runs right after hit
resolution each tick: a grabber that was hit on the same tick does not grab (attack beats
grab).
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim.combat.grab import can_be_grabbed, grab_box, hold_frames, hold_in_front
from isofightr.sim.combat.hitbox import hurtbox
from isofightr.sim.events import GrabEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.math3d import capsules_overlap
from isofightr.sim.states.base import change_state
from isofightr.sim.states.grab import release_pair

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def resolve_grabs(match: Match) -> None:
    """Find this tick's grabs and start the holds (tick step 7, after hits)."""
    grabs: dict[int, int] = {}
    for grabber in match.fighters:
        box = grab_box(grabber)
        if box is None or grabber.launch is not None or grabber.hitlag > 0:
            continue
        for target in match.fighters:
            if target is grabber or not can_be_grabbed(target):
                continue
            if grabber.allied_with(target) and not match.rules.friendly_fire:
                continue
            if capsules_overlap(box, hurtbox(target)):
                grabs[grabber.player_index] = target.player_index
                break

    taken: set[int] = set()
    for grabber_index, target_index in sorted(grabs.items()):
        if grabber_index in taken or target_index in taken:
            continue
        grabber, target = match.fighters[grabber_index], match.fighters[target_index]
        taken.update((grabber_index, target_index))
        middle = (grabber.pos + target.pos) / 2
        clash = grabs.get(target_index) == grabber_index
        match.events.append(GrabEvent(grabber_index, target_index, middle, clash))
        if clash:
            release_pair(match, grabber, target)
        else:
            _start_hold(match, grabber, target)


def _start_hold(match: Match, grabber: Fighter, target: Fighter) -> None:
    change_state(match, target, StateId.GRABBED)
    change_state(match, grabber, StateId.GRAB_HOLD)
    grabber.grab_partner = target.player_index
    target.grab_partner = grabber.player_index
    grabber.grab_timer = hold_frames(target.damage)
    grabber.pummel_cooldown = 0
    hold_in_front(grabber, target)
