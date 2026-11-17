"""The disadvantage state: getting out of trouble (decision D-071).

Plan note "15 - CPU AI" ("Situations and their tactics", disadvantage). The M10 CPU met every
moment of trouble with one fixed answer on a dice roll: DI across the launch toward the middle,
a tech in place or a roll in a random direction, getup and ledge options from fixed shares.
Here each choice is made from what can actually happen:

- :func:`di_choice`: every DI the victim can hold is flown by :mod:`isofightr.ai.forecast`;
  survive if any choice survives, and among those end over the stage and far from whoever
  hit it (away from the follow-up).
- :func:`tech_choice`: tech in place, or roll away from an opponent that waits where the
  tumble comes down.
- :func:`option_risk`: how likely an opponent is to punish where a getup or ledge option
  leaves the CPU, from its distance, reach and speed; :func:`pick` chooses among options by
  value at the level's temperature, so the CPU is not predictable.
- :func:`defence_options`: what a CPU on the ground can do about a hit or a grab on its way:
  shield (never against a grab), spot dodge or roll when its intangible frames cover the hit,
  jump away; each with a value.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from isofightr import config
from isofightr.ai import forecast, predict
from isofightr.ai.knowledge import CharacterKnowledge
from isofightr.ai.terrain import over_ground
from isofightr.ai.view import FighterView
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.fighter import Launch
from isofightr.sim.math3d import ZERO2, Vec2, Vec3
from isofightr.sim.stage import Stage

TECH_IN_PLACE: Final[str] = "tech"
TECH_AWAY: Final[str] = "tech away"


def di_choice(
    stage: Stage,
    launch: Launch,
    pos: Vec3,
    grounded: bool,
    character: CharacterDef,
    attacker: Vec3 | None,
) -> tuple[Vec2, int]:
    """The stick and modifier to hold through a launch: survive if anything survives; then
    end over the stage, or else as near its middle as can be (an easier way back); then far
    from the attacker (who wants to follow up)."""
    best: tuple[float, Vec2, int] | None = None
    for stick, vertical, flown in forecast.di_flights(stage, launch, pos, grounded, character):
        end = flown.end
        score = 0.0 if flown.ko else config.CPU_DI_SURVIVE
        if not flown.ko and over_ground(stage, Vec3(end.x, end.y, end.z + 1.0)):
            score += config.CPU_DI_ON_STAGE
        else:
            score -= (end.xy - stage.respawn).length()
        if attacker is not None:
            score += config.CPU_DI_AWAY_SHARE * (end.xy - attacker.xy).length()
        if best is None or score > best[0]:
            best = (score, stick, vertical)
    assert best is not None
    return best[1], best[2]


def tech_choice(landing: Vec3, opponent: FighterView | None, reach: float) -> str:
    """Tech in place, or away from an opponent close enough to strike where it lands."""
    if opponent is None:
        return TECH_IN_PLACE
    if (opponent.pos.xy - landing.xy).length() <= reach + config.CPU_TECH_AWAY_MARGIN:
        return TECH_AWAY
    return TECH_IN_PLACE


def away_from(here: Vec3, other: Vec3 | None, fallback: Vec2) -> Vec2:
    """The unit direction from ``other`` to ``here`` (``fallback`` if there is none)."""
    if other is None:
        return fallback
    away = here.xy - other.xy
    return away.normalized() if away.length() > 0.0 else fallback


def option_risk(
    end: Vec3,
    free: int,
    safe_until: int,
    opponent: FighterView | None,
    theirs: CharacterKnowledge | None,
    run_speed: float,
) -> float:
    """0 to 1: how likely an opponent is to hit the CPU where an option leaves it. It has
    until the option is over (``free``), less the frames the CPU cannot be hit
    (``safe_until``), to get within its striking reach."""
    if opponent is None or theirs is None or not opponent.in_play:
        return 0.0
    exposed = max(free - safe_until, 0) + config.CPU_EXPOSED_SLACK
    distance = (opponent.pos.xy - end.xy).length()
    covered = theirs.strike_reach + run_speed * exposed
    if distance <= theirs.strike_reach:
        return 1.0
    if distance >= covered:
        return 0.0
    return 1.0 - (distance - theirs.strike_reach) / max(covered - theirs.strike_reach, 1e-6)


OPTION_BASE: Final[dict[str, float]] = {
    "stand": 1.0,
    "getup": 1.0,
    "roll in": 0.5,
    "roll out": 0.0,
    "roll": 0.5,
    "jump": 0.5,
}
"""A small preference among options that are all safe (so the CPU still mixes them up)."""
JUMP_EXPOSED: Final[int] = 20
"""A ledge jump leaves the fighter in the air near the ledge this long."""
ATTACK_HITS: Final[float] = 10.0
"""What a getup or ledge attack is worth when the opponent stands where it strikes."""
ATTACK_WHIFFS: Final[float] = -4.0
"""And what it costs when nobody is there (end lag for nothing)."""


def option_values(
    options: Sequence[predict.Option],
    opponent: FighterView | None,
    theirs: CharacterKnowledge | None,
    run_speed: float,
) -> list[tuple[str, float]]:
    """Each getup or ledge option with its value: a little preference, an attack's worth
    if the opponent is in front of it, less ``CPU_OPTION_PUNISHED`` times the chance the
    opponent punishes where it leaves the CPU. ``drop`` (let go) is left out."""
    valued = []
    for option in options:
        if option.name in ("drop", "miss"):
            continue
        free = JUMP_EXPOSED if option.name == "jump" else option.free
        points = option.track.points
        end = points[min(max(free, 1), len(points)) - 1]
        value = OPTION_BASE.get(option.name, 0.0)
        if option.name == "attack":
            near = (
                opponent is not None
                and opponent.in_play
                and (opponent.pos.xy - end.xy).length() <= config.CPU_CLOSE_RANGE
            )
            if near:
                valued.append((option.name, value + ATTACK_HITS))  # it strikes them first
                continue
            value += ATTACK_WHIFFS
        risk = option_risk(end, free, option.intangible, opponent, theirs, run_speed)
        valued.append((option.name, value - config.CPU_OPTION_PUNISHED * risk))
    return valued


def pick(names: Sequence[str], values: Sequence[float], temperature: float, roll: float) -> str:
    """Choose among options by value at ``temperature`` (best first on a tie)."""
    order = sorted(range(len(names)), key=lambda index: -values[index])
    top = values[order[0]]
    scale = max(temperature, 1e-6)
    weights = [math.exp((values[index] - top) / scale) for index in order]
    mark = roll * sum(weights)
    for index, weight in zip(order, weights, strict=True):
        if mark < weight:
            return names[index]
        mark -= weight
    return names[order[0]]


@dataclass(frozen=True, slots=True)
class Defence:
    """One way of dealing with a hit on its way, and what it is worth."""

    name: str
    value: float


def covers(window: tuple[int, int] | None, lead: int, hit_in: int) -> bool:
    """Whether intangible frames ``window`` (counted from the option's first input, which
    comes after ``lead`` frames of release) cover a hit landing in ``hit_in`` frames and
    lasting ``CPU_HIT_ACTIVE_GUESS`` frames."""
    if window is None:
        return False
    first, last = window
    return first + lead <= hit_in and hit_in + config.CPU_HIT_ACTIVE_GUESS <= last + lead


def defence_options(
    knowledge: CharacterKnowledge,
    hit_in: int,
    grab: bool,
    shield_hp: float,
    lead: int,
) -> list[Defence]:
    """What a grounded CPU can do about a hit (or grab) landing in ``hit_in`` frames, best
    first. ``lead`` is the release frame a fresh press may need first."""
    used = knowledge.utilities
    found: list[Defence] = []
    if not grab:
        worn = shield_hp <= config.CPU_LOW_SHIELD
        found.append(Defence("shield", config.CPU_SHIELD_VALUE - (20.0 if worn else 0.0)))
    spot = used.get("spot_dodge")
    if spot is not None and covers(spot.intangible, lead, hit_in):
        found.append(Defence("spot dodge", config.CPU_DODGE_VALUE + (6.0 if grab else 0.0)))
    roll = used.get("roll_back")
    if roll is not None and covers(roll.intangible, lead, hit_in):
        found.append(Defence("roll away", config.CPU_ROLL_VALUE))
    if grab:
        found.append(Defence("jump", config.CPU_JUMP_AWAY_VALUE))
    found.sort(key=lambda option: -option.value)
    return found


ZERO_STICK: Final[Vec2] = ZERO2
