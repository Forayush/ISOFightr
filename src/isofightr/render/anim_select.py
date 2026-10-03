"""Picks which animation pose a fighter shows this frame, from sim state.

Plan note "07 - Fighter State Machine and Move Data" ("Animation binding", D-047): the
renderer maps ``(state, move, frame, facing)`` to ``(animation, pose, direction)``. An attack
shows the animation named after its move, timed by the pose start frames in the animation data;
every other state has a named animation. An animation that is not drawn yet falls back along
:data:`FALLBACKS` and finally to ``idle``, so a character is playable while its art is partial.

Pure Python (no ``arcade``), so it is unit tested without a window. Reads the fighter; never
changes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from isofightr.data.sprite_sheet import AnimInfo
from isofightr.sim.fighter import Fighter, StateId

IDLE_ANIM: Final[str] = "idle"

STATE_ANIMS: Final[Mapping[StateId, str]] = {
    StateId.IDLE: "idle",
    StateId.WALK: "walk",
    StateId.DASH: "dash",
    StateId.RUN: "run",
    StateId.RUN_TURN: "run_turn",
    StateId.SKID: "skid",
    StateId.TURN: "turn",
    StateId.JUMP_SQUAT: "jumpsquat",
    StateId.LAND: "land",
    StateId.PLATFORM_DROP: "platform_drop",
    StateId.JUMP: "jump",
    StateId.DOUBLE_JUMP: "double_jump",
    StateId.FALL: "fall",
    StateId.REBOUND: "rebound",
    StateId.FLINCH: "hurt",
    StateId.TUMBLE: "tumble",
    StateId.KNOCKDOWN: "knockdown",
    StateId.GETUP: "getup",
    StateId.SHIELD: "shield",
    StateId.SHIELD_STUN: "shield",
    StateId.SHIELD_DROP: "shield_drop",
    StateId.SHIELD_BREAK: "shield_break",
    StateId.DIZZY: "dizzy",
    StateId.SPOT_DODGE: "spot_dodge",
    StateId.ROLL: "roll",
    StateId.AIR_DODGE: "air_dodge",
    StateId.HELPLESS: "helpless",
    StateId.GRAB: "grab",
    StateId.DASH_GRAB: "dash_grab",
    StateId.GRAB_HOLD: "grab_hold",
    StateId.GRABBED: "grabbed",
    StateId.GRAB_RELEASE: "grab_release",
    StateId.LEDGE_HANG: "ledge_hang",
    StateId.LEDGE_GETUP: "ledge_getup",
    StateId.LEDGE_ATTACK: "ledge_attack",
    StateId.LEDGE_ROLL: "ledge_roll",
    StateId.LEDGE_TRUMPED: "ledge_trumped",
    StateId.TECH: "tech",
    StateId.TECH_ROLL: "tech_roll",
    StateId.WALL_TECH: "wall_tech",
    StateId.GETUP_ROLL: "getup_roll",
    StateId.REVIVAL: "revival",
}
"""The animation each non-attack state shows. Attacks are named by their move id and throws by
their throw id (``fthrow``, ``bthrow``, ``uthrow``, ``dthrow``)."""

FALLBACKS: Final[Mapping[str, str]] = {
    "walk": "run",
    "dash": "run",
    "run_turn": "turn",
    "skid": "idle",
    "jumpsquat": "land",
    "platform_drop": "fall",
    "double_jump": "jump",
    "jump": "fall",
    "rebound": "hurt",
    "tumble": "hurt",
    "knockdown": "hurt",
    "shield_drop": "shield",
    "shield_break": "dizzy",
    "dizzy": "hurt",
    "air_dodge": "spot_dodge",
    "helpless": "fall",
    "dash_grab": "grab",
    "grab_release": "grab_hold",
    "fthrow": "grab_hold",
    "bthrow": "grab_hold",
    "uthrow": "grab_hold",
    "dthrow": "grab_hold",
    "grabbed": "hurt",
    "ledge_trumped": "fall",
    "tech_roll": "roll",
    "getup_roll": "roll",
    "ledge_roll": "roll",
    "wall_tech": "tech",
    "revival": "idle",
    "riposte_hit": "dspecial",
}
"""What to show while an animation is not drawn yet."""


@dataclass(frozen=True, slots=True)
class AnimChoice:
    """The pose to draw."""

    anim: str
    pose: int
    exact: bool
    """Whether this is the animation the state asked for (not a fallback)."""


def wanted_anim(fighter: Fighter) -> str:
    """Return the animation a fighter's state calls for, before any fallback."""
    if fighter.state is StateId.ATTACK and fighter.move_id:
        return fighter.move_id
    if fighter.state is StateId.THROW:
        return fighter.throw_id or "grab_hold"
    return STATE_ANIMS.get(fighter.state, IDLE_ANIM)


def select_anim(fighter: Fighter, anims: Mapping[str, AnimInfo]) -> AnimChoice | None:
    """Return the pose a fighter shows, or ``None`` if the character has no ``idle`` either."""
    wanted = wanted_anim(fighter)
    name = wanted
    seen = {name}
    while name not in anims:
        name = FALLBACKS.get(name, IDLE_ANIM)
        if name in seen:
            name = IDLE_ANIM
            if name not in anims:
                return None
            break
        seen.add(name)
    info = anims[name]
    frame = fighter.state_frame if name == wanted else max(fighter.state_frame, 1)
    return AnimChoice(name, info.pose_at(frame), exact=name == wanted)
