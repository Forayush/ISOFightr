"""Which of the three situations of a fight is the CPU in? (decision D-071)

Plan note "15 - CPU AI" ("Situations and their tactics"). Fighting-game players split a match
into **neutral** (both can act: the contest is for the first clean hit), **advantage** (the
opponent cannot act freely: it is being hit, is landing, lying down, on the ledge or off the
stage) and **disadvantage** (the same, the other way round). What is sensible differs
completely between them, so the CPU names its situation before it decides anything.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from isofightr.ai.predict import Track
from isofightr.ai.view import FighterView
from isofightr.sim.fighter import StateId

OPENING_FRAMES: Final[int] = 6
"""An opponent locked for at least this long is an opening, not a contest."""
PRONE: Final[frozenset[StateId]] = frozenset(
    {StateId.KNOCKDOWN, StateId.LEDGE_HANG, StateId.HELPLESS, StateId.DIZZY, StateId.SHIELD_BREAK}
)
"""States that put a fighter at a disadvantage even while it can still choose something."""


class Situation(Enum):
    """The three situations of a fight."""

    NEUTRAL = "neutral"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"


@dataclass(frozen=True, slots=True)
class Standing:
    """The situation and, in a word or two, why."""

    situation: Situation
    why: str = ""


def _in_trouble(view: FighterView, off_stage: bool) -> str:
    """Why a fighter is not free to contest neutral ("" if it is)."""
    if view.hitlag > 0 and view.launch is not None:
        return "hit"
    if view.hitstun > 0:
        return "in hitstun"
    if view.state in PRONE:
        return view.state.value.replace("_", " ")
    if view.state is StateId.GRABBED:
        return "grabbed"
    if off_stage:
        return "off the stage"
    return ""


def classify(
    me: FighterView,
    target: FighterView | None,
    track: Track | None,
    me_off_stage: bool = False,
    target_off_stage: bool = False,
) -> Standing:
    """Name the CPU's situation against its target. Its own trouble comes first: a fighter
    in hitstun is at a disadvantage whatever the opponent is doing."""
    mine = _in_trouble(me, me_off_stage)
    if mine:
        return Standing(Situation.DISADVANTAGE, mine)
    if target is None:
        return Standing(Situation.NEUTRAL, "nobody to fight")
    theirs = _in_trouble(target, target_off_stage)
    if theirs:
        return Standing(Situation.ADVANTAGE, theirs)
    if track is not None and track.locked >= OPENING_FRAMES:
        return Standing(Situation.ADVANTAGE, "an opening")
    return Standing(Situation.NEUTRAL)
