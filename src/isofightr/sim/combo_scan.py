"""Frame advantage on hit, from move data: the measure of what can combo.

Plan note "16 - Testing Debug and Tooling" (``combo_scan.py``, decision D-059). For a hit,

    advantage = hitstun - (faf - first active frame)

is how many frames the attacker can act before the target can, if the move connects on its
first active frame. Hitlag freezes both fighters equally, so it cancels out. Moves that hit
several times (more than one hit window, or a re-hitting hitbox) are left out: their last hit
decides, which this simple figure does not describe. Jabs are listed but are not counted as
combo starters: a jab chain links through its cancel windows, not through hitstun.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.move_def import MoveKind

DEFAULT_PERCENTS: Final[tuple[int, ...]] = (0, 30, 60)
SCANNED_KINDS: Final[tuple[MoveKind, ...]] = (
    MoveKind.JAB,
    MoveKind.TILT,
    MoveKind.DASH_ATTACK,
    MoveKind.AERIAL,
)
STARTER_ADVANTAGE: Final[int] = 3
"""A move this many frames ahead on hit can be followed up: a combo starter."""


@dataclass(frozen=True, slots=True)
class ComboRow:
    """One move's frame advantage on hit at each scanned percent."""

    move_id: str
    kind: MoveKind
    damage: float
    first_active: int
    faf: int
    advantage: tuple[int, ...]

    @property
    def starter(self) -> bool:
        """Whether the move counts as a combo starter (jabs chain by cancelling instead)."""
        return self.kind is not MoveKind.JAB


def scan(
    attacker: CharacterDef, target: CharacterDef, percents: Sequence[int] = DEFAULT_PERCENTS
) -> list[ComboRow]:
    """Return the advantage on hit of every single-hit jab, tilt, dash attack and aerial of
    ``attacker`` against ``target`` at each of ``percents`` (the target's damage before the
    hit; the move is fresh)."""
    rows = []
    for move_id in sorted(attacker.moves):
        move = attacker.moves[move_id]
        if move.kind not in SCANNED_KINDS or len(move.windows) != 1:
            continue
        window = move.windows[0]
        if any(box.rehit for box in window.hitboxes):
            continue
        box = min(window.hitboxes, key=lambda hitbox: hitbox.id)
        damage = box.damage * c.FRESH_BONUS
        end_lag = move.faf - window.frames.first
        advantage = tuple(
            kb.hitstun_frames(
                kb.knockback(percent + damage, damage, target.weight, box.bkb, box.kbg, box.fkb)
            )
            - end_lag
            for percent in percents
        )
        rows.append(
            ComboRow(move_id, move.kind, box.damage, window.frames.first, move.faf, advantage)
        )
    return rows


def starters(rows: Sequence[ComboRow], column: int, minimum: int = STARTER_ADVANTAGE) -> int:
    """Count the combo starters with at least ``minimum`` advantage in one percent column."""
    return sum(1 for row in rows if row.starter and row.advantage[column] >= minimum)


def best(rows: Sequence[ComboRow], column: int) -> int:
    """The largest advantage of any combo starter in one percent column."""
    return max(row.advantage[column] for row in rows if row.starter)


def table(rows: Sequence[ComboRow], percents: Sequence[int] = DEFAULT_PERCENTS) -> list[str]:
    """Return the scan as Markdown table lines."""
    header = "| Move | Kind | Damage | First active | FAF | " + " | ".join(
        f"On hit at {percent}%" for percent in percents
    )
    lines = [header + " |", "|" + "---|" * (5 + len(percents))]
    for row in rows:
        cells = " | ".join(f"{value:+d}" for value in row.advantage)
        lines.append(
            f"| {row.move_id} | {row.kind.value} | {row.damage:g} | {row.first_active} | "
            f"{row.faf} | {cells} |"
        )
    return lines
