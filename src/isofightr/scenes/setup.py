"""What the menus decide before a match: who plays whom, where, and under which rules.

Plan note "13 - Game Modes UI and Flow" ("Modes", "Rules settings"). Carried from character
select through stage select into the battle, and reused by "Rematch".

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

from isofightr.config import DEFAULT_CHARACTER_ID, DEFAULT_STAGE_ID, TRAINING_STAGE_ID
from isofightr.sim.constants import (
    COUNTDOWN_FRAMES,
    DEFAULT_STOCKS,
    DEFAULT_TIME_MINUTES,
    FRAMES_PER_MINUTE,
)
from isofightr.sim.match import Match, MatchRules

MIN_COUNT: Final[int] = 1
MAX_COUNT: Final[int] = 99
"""Stocks and minutes both go from 1 to 99."""
RANDOM_STAGE: Final[str] = "random"
"""Stage id that stands for "pick one at random when the match starts"."""


class Mode(Enum):
    """The versus modes."""

    STOCK = "stock"
    TIME = "time"


@dataclass(frozen=True, slots=True)
class MatchSetup:
    """Everything needed to start a match."""

    characters: tuple[str, ...] = (DEFAULT_CHARACTER_ID, DEFAULT_CHARACTER_ID)
    """Character id per player, in player order."""
    stage: str = DEFAULT_STAGE_ID
    mode: Mode = Mode.STOCK
    stocks: int = DEFAULT_STOCKS
    minutes: int = DEFAULT_TIME_MINUTES
    training: bool = False

    def rules(self) -> MatchRules:
        """Return the sim rules for this setup. Training has no stocks, clock or countdown."""
        if self.training:
            return MatchRules(stocks=None)
        if self.mode is Mode.TIME:
            return MatchRules(
                stocks=None,
                time_frames=self.minutes * FRAMES_PER_MINUTE,
                countdown_frames=COUNTDOWN_FRAMES,
            )
        return MatchRules(stocks=self.stocks, countdown_frames=COUNTDOWN_FRAMES)

    def with_count(self, step: int) -> "MatchSetup":
        """Return the setup with the current mode's count (stocks or minutes) changed."""
        if self.mode is Mode.TIME:
            return replace(self, minutes=_clamp(self.minutes + step))
        return replace(self, stocks=_clamp(self.stocks + step))

    @property
    def count_label(self) -> str:
        """The current mode's count as shown in menus: "3 stocks" or "3 minutes"."""
        if self.mode is Mode.TIME:
            return f"{self.minutes} minute{'s' if self.minutes != 1 else ''}"
        return f"{self.stocks} stock{'s' if self.stocks != 1 else ''}"


def training_setup() -> MatchSetup:
    """Return the default setup for training mode."""
    return MatchSetup(stage=TRAINING_STAGE_ID, training=True)


def _clamp(count: int) -> int:
    return min(max(count, MIN_COUNT), MAX_COUNT)


def clock_text(frames: int) -> str:
    """Return a frame count as a ``M:SS`` clock, rounding up so 0:00 only shows at the end."""
    seconds = -(-max(frames, 0) // 60)
    return f"{seconds // 60}:{seconds % 60:02d}"


def countdown_text(frames_left: int) -> str:
    """Return the big countdown text: "3", "2", "1" (one second each)."""
    return str(-(-max(frames_left, 1) // 60))


RESULT_COLUMNS = ("PLACE", "PLAYER", "KOS", "FALLS", "SDS", "DEALT", "TAKEN", "PEAK", "COMBO")
PLACE_NAMES = ("1st", "2nd", "3rd", "4th")


def results_table(match: Match) -> list[str]:
    """Return the results as fixed-width text lines: a header, then one line per player in
    placement order."""
    widths = (6, 12, 4, 6, 4, 6, 6, 5, 5)
    rows = [RESULT_COLUMNS]
    result = match.result
    groups = (
        result.placements
        if result is not None
        else (tuple(fighter.player_index for fighter in match.fighters),)
    )
    place = 0
    for group in groups:
        for player in group:
            stats = match.stats[player]
            name = match.fighters[player].character.display_name
            rows.append(
                (
                    PLACE_NAMES[place],
                    f"P{player + 1} {name}",
                    str(stats.kos),
                    str(stats.falls),
                    str(stats.self_destructs),
                    f"{stats.damage_given:.0f}%",
                    f"{stats.damage_taken:.0f}%",
                    f"{stats.peak_damage:.0f}%",
                    str(stats.longest_combo),
                )
            )
        place += len(group)
    return [
        " ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]
