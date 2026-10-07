"""What the menus decide before a match: who plays whom, where, and under which rules.

Plan note "13 - Game Modes UI and Flow" ("Modes", "Rules settings"). Carried from character
select through stage select into the battle, and reused by "Rematch".

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from isofightr.config import DEFAULT_CHARACTER_ID, DEFAULT_STAGE_ID, TRAINING_STAGE_ID
from isofightr.render.fighter_look import costume_index
from isofightr.settings import (
    LAUNCH_RATES,
    MAX_COUNT,
    MIN_COUNT,
    START_DAMAGE_MAX,
    START_DAMAGE_STEP,
)
from isofightr.sim.constants import (
    COUNTDOWN_FRAMES,
    DEFAULT_STOCKS,
    DEFAULT_TIME_MINUTES,
    FRAMES_PER_MINUTE,
)
from isofightr.sim.input_frame import Button, InputFrame
from isofightr.sim.match import Match, MatchRules

QUIT_BUTTONS: Final[int] = int(Button.ATTACK | Button.SPECIAL)
"""Held with the quit control (Backspace, or a gamepad's Start), these quit a match."""
QUIT_HINT: Final[str] = "pausing is off: BACKSPACE (pad: START) + attack + special quits"

RANDOM_STAGE: Final[str] = "random"
"""Stage id that stands for "pick one at random when the match starts"."""


@dataclass(frozen=True, slots=True)
class MatchSetup:
    """Everything needed to start a match."""

    characters: tuple[str, ...] = (DEFAULT_CHARACTER_ID, DEFAULT_CHARACTER_ID)
    """Character id per player, in player order."""
    stage: str = DEFAULT_STAGE_ID
    stock_on: bool = True
    """Whether fighters have a stock count. Off with the clock on is the old time mode:
    endless stocks, best score wins."""
    stocks: int = DEFAULT_STOCKS
    time_on: bool = False
    """Whether there is a clock. On with stocks as well, the match ends on whichever comes
    first (decision D-061). At least one of the two is always on."""
    minutes: int = DEFAULT_TIME_MINUTES
    training: bool = False
    devices: tuple[str, ...] = ()
    """Device id per player ("" = none); empty means the default device assignment."""
    cpus: tuple[int, ...] = ()
    """CPU level per player (0 = a person); missing entries are people."""
    team_play: bool = False
    teams: tuple[int, ...] = ()
    """Team number per player, used when ``team_play`` is on."""
    friendly_fire: bool = False
    launch_rate: float = 1.0
    parry: bool = False
    air_dodge_helpless: bool = False
    short_hop_macro: bool = True
    start_damage: int = 0
    """Percent every fighter starts and respawns with (0 to 300 in steps of 10)."""
    hud_display: bool = True
    """Whether the battle shows the players' damage, stocks and names. The countdown and
    the clock are always shown."""
    score_display: bool = False
    """Whether the HUD shows each player's score (KOs minus falls)."""
    player_tags: bool = False
    """Whether a coloured name tag floats over each fighter."""
    pausing: bool = True
    """Whether a versus match can be paused. Training always can."""
    random_pool: tuple[str, ...] = ()
    """Stage ids "Random" may pick; empty means every stage."""
    costumes: tuple[int, ...] = ()
    """The costume each player picked on character select, in player order; a player past
    the end wears the costume of their player colour. Presentation only, and ignored in a
    team match, where everyone wears their team's colour."""

    def costume_of(self, player: int, count: int) -> int:
        """Return the costume a player wears in the match this setup starts, for a character
        with ``count`` costumes."""
        team_play = self.team_play and bool(self.teams) and not self.training
        if team_play:
            team = self.teams[player] if player < len(self.teams) else player
            return costume_index(team, True, count)
        if player < len(self.costumes):
            return self.costumes[player] % max(count, 1)
        return costume_index(player, False, count)

    def rules(self) -> MatchRules:
        """Return the sim rules for this setup. Training has no stocks, clock or countdown."""
        if self.training:
            return MatchRules(stocks=None)
        stock_on = self.stock_on or not self.time_on
        return MatchRules(
            stocks=self.stocks if stock_on else None,
            time_frames=self.minutes * FRAMES_PER_MINUTE if self.time_on else None,
            countdown_frames=COUNTDOWN_FRAMES,
            launch_rate=self.launch_rate,
            teams=self.teams[: len(self.characters)] if self.team_play and self.teams else None,
            friendly_fire=self.friendly_fire,
            parry=self.parry,
            air_dodge_helpless=self.air_dodge_helpless,
            short_hop_macro=self.short_hop_macro,
            start_damage=float(self.start_damage),
        )

    def with_stocks(self, step: int) -> "MatchSetup":
        """Return the setup with the stock count changed, kept between 1 and 99."""
        return replace(self, stocks=_clamp(self.stocks + step))

    def with_minutes(self, step: int) -> "MatchSetup":
        """Return the setup with the time limit changed, kept between 1 and 99 minutes."""
        return replace(self, minutes=_clamp(self.minutes + step))

    def with_start_damage(self, steps: int) -> "MatchSetup":
        """Return the setup with the starting damage moved by whole steps of 10%."""
        damage = self.start_damage + steps * START_DAMAGE_STEP
        return replace(self, start_damage=min(max(damage, 0), START_DAMAGE_MAX))

    def with_launch_rate(self, step: int) -> "MatchSetup":
        """Return the setup with the launch rate moved along :data:`LAUNCH_RATES`."""
        rates = LAUNCH_RATES
        index = rates.index(self.launch_rate) if self.launch_rate in rates else rates.index(1.0)
        return replace(self, launch_rate=rates[min(max(index + step, 0), len(rates) - 1)])

    def with_stock_on(self, on: bool) -> "MatchSetup":
        """Return the setup with stocks on or off. Switching them off switches the clock on:
        a match needs a way to end."""
        return replace(self, stock_on=on, time_on=self.time_on or not on)

    def with_time_on(self, on: bool) -> "MatchSetup":
        """Return the setup with the clock on or off. Switching it off switches stocks on."""
        return replace(self, time_on=on, stock_on=self.stock_on or not on)

    @property
    def time_label(self) -> str:
        """The time limit as shown in menus: ``3:00``."""
        return f"{self.minutes}:00"

    def pool(self, stages: Sequence[str]) -> list[str]:
        """Return the stages "Random" may pick from ``stages``: the pool's, or all of them
        when the pool is empty or names none that exist."""
        chosen = [stage for stage in stages if stage in self.random_pool]
        return chosen or list(stages)


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
    by_team = match.rules.teams is not None
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
        place += 1 if by_team else len(group)  # a team shares one place
    return [
        " ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]


def result_awards(match: Match) -> list[str]:
    """Return the award lines under the results table: who dealt the most damage, who had
    the longest combo and who took the hardest beating before falling (plan note 13,
    "Results screen"). An award nobody earned is left out."""

    def name(player: int) -> str:
        return f"P{player + 1} {match.fighters[player].character.display_name}"

    players = range(len(match.stats))
    awards = []
    dealer = max(players, key=lambda player: match.stats[player].damage_given)
    if match.stats[dealer].damage_given > 0.0:
        awards.append(f"Most damage: {name(dealer)} ({match.stats[dealer].damage_given:.0f}%)")
    combo = max(players, key=lambda player: match.stats[player].longest_combo)
    if match.stats[combo].longest_combo > 1:
        awards.append(f"Longest combo: {name(combo)} ({match.stats[combo].longest_combo} hits)")
    tough = max(players, key=lambda player: match.stats[player].peak_damage)
    if match.stats[tough].peak_damage > 0.0:
        awards.append(
            f"Toughest: {name(tough)} (survived to {match.stats[tough].peak_damage:.0f}%)"
        )
    return awards


TEAM_NAMES: Final[tuple[str, ...]] = ("Red", "Blue", "Yellow", "Green")
"""Team names, in the order of the player colors."""
MIN_VERSUS_PLAYERS: Final[int] = 2


def can_start(setup: MatchSetup, joined: int) -> str:
    """Return why a match cannot start with ``joined`` players, or "" if it can."""
    if setup.training:
        return "" if joined >= 1 else "press ATTACK to join"
    if joined < MIN_VERSUS_PLAYERS:
        return "two players are needed: join on another device, or add a CPU with GRAB"
    if setup.team_play and len(set(setup.teams[:joined])) < 2:
        return "everyone is on one team: change a team"
    return ""


def quit_chord(frames: Sequence[InputFrame], quit_held: Sequence[bool]) -> bool:
    """Return whether a player asks to leave a match that cannot be paused: their device's
    quit control (``quit_held``, per player: Backspace on a keyboard, Start on a gamepad)
    held together with attack and special (plan note 13, decision D-061)."""
    return any(
        held and frame.held & QUIT_BUTTONS == QUIT_BUTTONS
        for frame, held in zip(frames, quit_held, strict=False)
    )
