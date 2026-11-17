"""Style: each character plays like itself, and no two CPUs exactly alike (decision D-071).

Plan note "15 - CPU AI" ("Style: each character plays like itself"). :func:`style_for`
resolves a :class:`Style` from three layers:

1. **Defaults from what the CPU knows of the character**, so a character with no ``[cpu]``
   table still plays sensibly: a long projectile makes it a zoner (it stands far and likes
   its projectiles); weight makes it braver about trading; a fast runner is more aggressive.
2. **The optional ``[cpu]`` table** in ``fighter.toml``
   (:class:`~isofightr.sim.character_def.CpuStyleDef`): any value it gives replaces the
   default.
3. **Temperament:** a small seeded offset (``CPU_TEMPERAMENT``) on every number, so four
   level 9 CPUs of one character do not play alike.

How the controller uses it: ``aggression`` scales the chance of acting on a free opponent,
``patience`` how long it waits before closing in, ``range`` where it stands, ``grab_rate``,
``zoning`` and ``air_bias`` add value to grabs, projectiles and aerials, ``risk`` divides its
caution, ``edgeguard_depth`` below ``CPU_STYLE_STAY`` keeps it on the stage, and favourite or
avoided moves gain or lose a little value.

Pure Python (no ``arcade``).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Final

from isofightr import config
from isofightr.ai.knowledge import CharacterKnowledge
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.rng import Rng

RANGE_OFFSET: Final[dict[str, float]] = {"close": -0.3, "mid": 0.0, "far": 0.0}
"""Units added to where the CPU stands in neutral (``far`` is the zoner's range instead)."""
TEMPERED: Final[tuple[str, ...]] = (
    "aggression",
    "patience",
    "grab_rate",
    "zoning",
    "air_bias",
    "edgeguard_depth",
    "risk",
)


@dataclass(frozen=True, slots=True)
class Style:
    """A CPU's resolved style. Numbers are multipliers around 1."""

    aggression: float = 1.0
    patience: float = 1.0
    range: str = "mid"
    grab_rate: float = 1.0
    zoning: float = 1.0
    air_bias: float = 1.0
    edgeguard_depth: float = 1.0
    risk: float = 1.0
    favourites: frozenset[str] = frozenset()
    avoid: frozenset[str] = frozenset()

    @property
    def far(self) -> bool:
        """Whether it keeps a zoner's distance."""
        return self.range == "far"

    @property
    def stays_on_stage(self) -> bool:
        """Whether it never follows an opponent off the stage."""
        return self.edgeguard_depth < config.CPU_STYLE_STAY


def default_style(character: CharacterDef, knowledge: CharacterKnowledge) -> Style:
    """What the character's own data suggests, before its ``[cpu]`` table."""
    zoner = knowledge.projectile_reach >= config.CPU_ZONER_REACH
    movement = character.movement
    quick = movement.run_speed / config.CPU_STYLE_RUN_SPEED
    heavy = character.weight / config.CPU_STYLE_WEIGHT
    return Style(
        aggression=_clamp(quick),
        range="far" if zoner else "mid",
        zoning=1.3 if zoner else 1.0,
        risk=_clamp(heavy),
    )


def style_for(character: CharacterDef, knowledge: CharacterKnowledge, seed: int) -> Style:
    """The style a CPU playing ``character`` uses: defaults, then ``[cpu]``, then a seeded
    temperament."""
    style = default_style(character, knowledge)
    table = character.cpu
    given = {
        name: getattr(table, name)
        for name in (*TEMPERED, "range")
        if getattr(table, name) is not None
    }
    style = replace(
        style, **given, favourites=frozenset(table.favourites), avoid=frozenset(table.avoid)
    )
    dice = Rng.seeded(seed)
    spread = config.CPU_TEMPERAMENT
    tempered = {
        name: getattr(style, name) * (1.0 + (dice.random() * 2.0 - 1.0) * spread)
        for name in TEMPERED
    }
    return replace(style, **tempered)


def _clamp(value: float) -> float:
    low, high = config.CPU_STYLE_DEFAULT_BOUNDS
    return min(max(value, low), high)


def describe(style: Style) -> str:
    """One line for the trace and tests."""
    parts = []
    for item in fields(style):
        value = getattr(style, item.name)
        if isinstance(value, float):
            parts.append(f"{item.name} {value:.2f}")
        elif isinstance(value, str):
            parts.append(f"{item.name} {value}")
    return ", ".join(parts)
