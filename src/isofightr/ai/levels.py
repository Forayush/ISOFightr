"""CPU difficulty levels 1 to 9 (plan note "15 - CPU AI", "Difficulty levels").

The plan gives values at levels 1, 3, 5, 7 and 9 (``config.CPU_*``); even levels sit halfway
between their neighbours.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from isofightr import config


@dataclass(frozen=True, slots=True)
class CpuLevel:
    """Everything that changes with a CPU's level."""

    level: int
    reaction_frames: int
    decision_frames: int
    defend_chance: float
    di_quality: float
    tech_chance: float
    aim_jitter_degrees: float
    aggression: float
    prediction: float
    edgeguard_chance: float
    recovery_mixup: float
    ledge_wait_max: int
    mash_every: int
    punish_margin: int
    tracking_frames: int = 0
    """M20: how late smooth changes are seen (``config.CPU_TRACKING_FRAMES``)."""
    temperature: float = 1.0
    edgeguard_depth: float = 0.0
    """M20: above 0 it may leave the stage to edgeguard (``CPU_EDGEGUARD_DEPTH``)."""
    adapt: float = 0.0
    """M20: how much it acts on its opponents' habits (``CPU_HABIT_ADAPT``; none below
    ``CPU_HABIT_FIRST_LEVEL``)."""
    """M20: how loosely it picks among what is worth doing (``CPU_CHOICE_TEMPERATURE``)."""


def _at(values: Sequence[float], level: int) -> float:
    """Interpolate a per-anchor table at ``level``."""
    anchors = config.CPU_LEVEL_ANCHORS
    if level <= anchors[0]:
        return values[0]
    for index in range(1, len(anchors)):
        if level <= anchors[index]:
            low, high = anchors[index - 1], anchors[index]
            share = (level - low) / (high - low)
            return values[index - 1] + (values[index] - values[index - 1]) * share
    return values[-1]


@cache
def cpu_level(level: int) -> CpuLevel:
    """Return the parameters of a CPU level (1 to 9)."""
    if not config.CPU_MIN_LEVEL <= level <= config.CPU_MAX_LEVEL:
        raise ValueError(
            f"CPU level must be {config.CPU_MIN_LEVEL} to {config.CPU_MAX_LEVEL}, got {level}"
        )
    return CpuLevel(
        level=level,
        reaction_frames=round(_at(config.CPU_REACTION_FRAMES, level)),
        decision_frames=max(1, round(_at(config.CPU_DECISION_FRAMES, level))),
        defend_chance=_at(config.CPU_DEFEND_CHANCE, level),
        di_quality=_at(config.CPU_DI_QUALITY, level),
        tech_chance=_at(config.CPU_TECH_CHANCE, level),
        aim_jitter_degrees=_at(config.CPU_AIM_JITTER_DEGREES, level),
        aggression=_at(config.CPU_AGGRESSION, level),
        prediction=_at(config.CPU_PREDICTION, level),
        edgeguard_chance=_at(config.CPU_EDGEGUARD_CHANCE, level),
        recovery_mixup=_at(config.CPU_RECOVERY_MIXUP, level),
        ledge_wait_max=round(_at(config.CPU_LEDGE_WAIT_MAX, level)),
        mash_every=max(1, round(_at(config.CPU_MASH_EVERY, level))),
        punish_margin=round(_at(config.CPU_PUNISH_MARGIN, level)),
        tracking_frames=round(_at(config.CPU_TRACKING_FRAMES, level)),
        temperature=_at(config.CPU_CHOICE_TEMPERATURE, level),
        edgeguard_depth=_at(config.CPU_EDGEGUARD_DEPTH, level),
        adapt=(
            _at(config.CPU_HABIT_ADAPT, level) if level >= config.CPU_HABIT_FIRST_LEVEL else 0.0
        ),
    )
