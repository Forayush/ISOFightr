"""The victory screen's model: who stands where, what the rows and awards say, and what is on
screen at each tick.

Plan note "13 - Game Modes UI and Flow" ("Results screen", decision D-061 item 10, wireframe
``m13_wf_results.png``). The banner drops in with a bounce and its letters wave; the winner
(every member of a winning team) stands on the top step of a podium under a spotlight, the
others on lower steps by placement; the stats rows slide in one after another with bars that
grow and numbers that count up; the awards appear one by one; confetti in the winner's
colour falls throughout. All of it is a function of the tick, so a test can ask what is
visible at tick N, and the screen (:mod:`isofightr.scenes.results_view`) only draws.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.scenes.setup import PLACE_NAMES, TEAM_NAMES, Award, award_items
from isofightr.sim.match import Match
from isofightr.ui import anim

# --- timeline (ticks from when the screen opens) ----------------------------------------------
BANNER_START: Final[int] = 0
BANNER_TICKS: Final[int] = 40
"""The banner drops from above the screen and bounces to rest over this many ticks."""
BANNER_DROP: Final[int] = 90
WAVE_AMPLITUDE: Final[int] = 2
WAVE_PERIOD: Final[int] = 70
WAVE_SPREAD: Final[int] = 5
BUTTONS_START: Final[int] = 0
BUTTONS_TICKS: Final[int] = 12
"""The buttons are there (and usable) from the start: nobody waits to play again."""
WINNER_START: Final[int] = 14
RISE_TICKS: Final[int] = 14
"""A podium step and whoever stands on it rise into place over this many ticks."""
RISE_PIXELS: Final[int] = 24
STEP_GAP: Final[int] = 10
"""Each lower placement rises this many ticks after the one above it."""
ROWS_START: Final[int] = 50
ROW_GAP: Final[int] = 12
ROW_SLIDE_TICKS: Final[int] = 14
ROW_SLIDE: Final[int] = 60
BAR_TICKS: Final[int] = 40
"""A row's bars grow and its numbers count up over this many ticks after it has slid in."""
AWARDS_START: Final[int] = 110
AWARD_GAP: Final[int] = 30
AWARD_TICKS: Final[int] = 10

# --- podium -------------------------------------------------------------------------------------
STEP_WIDTH: Final[int] = 64
STEP_HEIGHTS: Final[tuple[int, ...]] = (52, 34, 20, 10)
"""How tall the podium step of each placement is, first to fourth."""
PODIUM_BASE: Final[int] = 56
"""Screen y of the foot of the podium."""
PODIUM_CENTRE: Final[int] = 318
"""Screen x of the middle of the podium (between the awards and the stats panels)."""
TEAM_STEP_WIDTH: Final[int] = 84
"""Winners who share the top step each get this much room, so their art does not pile up."""

# --- confetti -----------------------------------------------------------------------------------
CONFETTI_PIECES: Final[int] = 64
CONFETTI_COLOURS: Final[int] = 4
"""A piece is one of this many colours: the winner's light, base and dark shades, or white."""


@dataclass(frozen=True, slots=True)
class Standing:
    """One player's place on the podium."""

    player: int
    place: int
    """0 for first; players of a team, or players level with each other, share a place."""
    winner: bool
    x: int
    """Screen x of the middle of the player's step."""
    height: int
    """Height of the step."""
    order: int
    """When the step rises: 0 first (the winners), then the placements below in turn."""


@dataclass(frozen=True, slots=True)
class StatRow:
    """One player's line in the stats panel."""

    player: int
    place: str
    name: str
    kos: int
    falls: int
    combo: int
    dealt: float
    taken: float
    dealt_share: float
    """Damage dealt as a share of the most anyone dealt (0 to 1): the bar's full length."""
    taken_share: float


def player_name(match: Match, player: int) -> str:
    """Return a player's name as the results show it ("P1 Rook")."""
    return f"P{player + 1} {match.fighters[player].character.display_name}"


def banner_text(match: Match) -> str:
    """Return the banner: the winning player, or the winning team."""
    result = match.result
    if result is None:
        return "NO CONTEST"
    if match.rules.teams is not None:
        team = match.fighters[result.winner].team
        return f"{TEAM_NAMES[team % len(TEAM_NAMES)].upper()} TEAM WINS!"
    return f"PLAYER {result.winner + 1} WINS!"


def sub_text(match: Match) -> str:
    """Return the line under the banner: how the match was decided, when that is worth
    saying."""
    if match.result is None:
        return ""
    if match.sudden_death:
        return "DECIDED IN SUDDEN DEATH"
    if match.rules.time_frames is not None and match.time_left is not None and match.time_left <= 0:
        return "TIME UP"
    return ""


def placement_groups(match: Match) -> tuple[tuple[int, ...], ...]:
    """Return the players by rank, best first (everyone level if there is no result)."""
    if match.result is not None:
        return match.result.placements
    return (tuple(fighter.player_index for fighter in match.fighters),)


def standings(match: Match) -> list[Standing]:
    """Return where everyone stands. Steps are laid left to right as second, first, third,
    fourth; the winners of a team match stand together with a second either side. Members
    of a group have steps of the same height, and the whole podium is centred."""
    groups = placement_groups(match)
    ordered: list[tuple[int, int]] = []  # (player, place)
    for place, group in enumerate(groups):
        ordered += [(player, place) for player in group]
    firsts = [entry for entry in ordered if entry[1] == 0]
    seconds = [entry for entry in ordered if entry[1] == 1]
    rest = [entry for entry in ordered if entry[1] > 1]
    # One of the seconds stands on the winners' left, everyone else on their right.
    row = [*seconds[:1], *firsts, *seconds[1:], *rest]
    shared = len(firsts) > 1
    widths = [TEAM_STEP_WIDTH if place == 0 and shared else STEP_WIDTH for _, place in row]
    left = PODIUM_CENTRE - sum(widths) // 2
    result = []
    for (player, place), width in zip(row, widths, strict=True):
        result.append(
            Standing(
                player=player,
                place=place,
                winner=place == 0 and match.result is not None,
                x=left + width // 2,
                height=STEP_HEIGHTS[min(place, len(STEP_HEIGHTS) - 1)],
                order=place,
            )
        )
        left += width
    return result


def stat_rows(match: Match) -> list[StatRow]:
    """Return the stats panel's rows, in placement order."""
    most_dealt = max((stats.damage_given for stats in match.stats), default=0.0)
    most_taken = max((stats.damage_taken for stats in match.stats), default=0.0)
    rows = []
    for place, group in enumerate(placement_groups(match)):
        for player in group:
            stats = match.stats[player]
            rows.append(
                StatRow(
                    player=player,
                    place=PLACE_NAMES[min(place, len(PLACE_NAMES) - 1)].upper(),
                    name=player_name(match, player).upper(),
                    kos=stats.kos,
                    falls=stats.falls,
                    combo=stats.longest_combo,
                    dealt=stats.damage_given,
                    taken=stats.damage_taken,
                    dealt_share=stats.damage_given / most_dealt if most_dealt > 0 else 0.0,
                    taken_share=stats.damage_taken / most_taken if most_taken > 0 else 0.0,
                )
            )
    return rows


def awards(match: Match) -> list[Award]:
    """Return the awards (see :func:`isofightr.scenes.setup.award_items`)."""
    return award_items(match)


def match_length(match: Match) -> str:
    """Return how long the fight lasted, as ``m:ss`` (the countdown not counted)."""
    frames = max(match.frame - match.rules.countdown_frames, 0)
    seconds = frames // 60
    return f"{seconds // 60}:{seconds % 60:02d}"


# --- what is on screen at tick N ----------------------------------------------------------------


def banner_offset(tick: int) -> int:
    """Return how far above its resting place the banner is: it drops in and bounces."""
    share = anim.bounce(anim.progress(tick, BANNER_START, BANNER_TICKS))
    return round(BANNER_DROP * (1.0 - share))


def letter_offset(tick: int, index: int) -> int:
    """Return the vertical offset of the banner's ``index``-th letter: once the banner has
    landed its letters wave, each a little after the one before."""
    if tick < BANNER_START + BANNER_TICKS:
        return 0
    return anim.wave(tick - BANNER_TICKS, index, WAVE_AMPLITUDE, WAVE_PERIOD, WAVE_SPREAD)


def step_start(order: int) -> int:
    """Return the tick a podium step of a placement starts to rise."""
    return WINNER_START + order * STEP_GAP


def step_shown(tick: int, order: int) -> bool:
    """Return whether a placement's step (and who stands on it) is on screen yet."""
    return tick >= step_start(order)


def step_offset(tick: int, order: int) -> int:
    """Return how far below its place a step still is while it rises."""
    return anim.slide(tick, step_start(order), RISE_TICKS, -RISE_PIXELS, 0, anim.ease_out_back)


def row_start(index: int) -> int:
    """Return the tick the ``index``-th stats row starts to slide in."""
    return ROWS_START + index * ROW_GAP


def row_shown(tick: int, index: int) -> bool:
    """Return whether a stats row is on screen yet."""
    return tick >= row_start(index)


def row_offset(tick: int, index: int) -> int:
    """Return how far right of its place a stats row still is."""
    return anim.slide(tick, row_start(index), ROW_SLIDE_TICKS, ROW_SLIDE, 0)


def row_fill(tick: int, index: int) -> float:
    """Return how far a row's bars have grown and its numbers counted (0 to 1)."""
    return anim.ease_out(anim.progress(tick, row_start(index) + ROW_SLIDE_TICKS, BAR_TICKS))


def counted(tick: int, index: int, value: float) -> int:
    """Return the number a row shows for ``value`` at ``tick``: counting up to it."""
    return int(value * row_fill(tick, index) + 1e-6)


def award_start(index: int) -> int:
    """Return the tick the ``index``-th award appears."""
    return AWARDS_START + index * AWARD_GAP


def award_shown(tick: int, index: int) -> bool:
    """Return whether an award is on screen yet."""
    return tick >= award_start(index)


def award_pop(tick: int, index: int) -> int:
    """Return how far left of its place an award still is as it pops in."""
    return anim.slide(tick, award_start(index), AWARD_TICKS, -16, 0, anim.ease_out_back)


def settled(tick: int, players: int, award_count: int) -> bool:
    """Return whether every animation has finished (the wave and the confetti go on)."""
    last_row = row_start(max(players - 1, 0)) + ROW_SLIDE_TICKS + BAR_TICKS
    last_award = award_start(max(award_count - 1, 0)) + AWARD_TICKS
    last_step = step_start(len(STEP_HEIGHTS) - 1) + RISE_TICKS
    return tick >= max(BANNER_TICKS, last_row, last_award, last_step)


def visible(tick: int, players: int, award_count: int) -> set[str]:
    """Return the names of what is on screen at ``tick``: ``banner``, ``buttons``,
    ``step0`` to ``stepN`` (by placement), ``row0`` to ``rowN`` and ``award0`` to
    ``awardN``."""
    shown = {"banner", "buttons", "confetti"}
    shown |= {f"step{order}" for order in range(len(STEP_HEIGHTS)) if step_shown(tick, order)}
    shown |= {f"row{index}" for index in range(players) if row_shown(tick, index)}
    shown |= {f"award{index}" for index in range(award_count) if award_shown(tick, index)}
    return shown


def _hash(value: int) -> int:
    """A small integer hash (no ``random``: the same confetti every time)."""
    value = (value ^ 61) ^ (value >> 16)
    value = (value * 9) & 0xFFFFFFFF
    value ^= value >> 4
    value = (value * 0x27D4EB2D) & 0xFFFFFFFF
    return value ^ (value >> 15)


def confetti(tick: int, pieces: int = CONFETTI_PIECES) -> list[tuple[int, int, int, bool]]:
    """Return the confetti at ``tick``: for each piece its screen x and y, its colour (0 to
    :data:`CONFETTI_COLOURS` - 1) and whether it shows its wide side (it tumbles). Pieces
    fall at their own speeds, sway, and start again from the top."""
    result = []
    for piece in range(pieces):
        seed = _hash(piece + 1)
        speed = 0.6 + (seed % 100) / 100.0
        start_x = (seed >> 8) % NATIVE_W
        phase = (seed >> 16) % 360
        fall = (tick * speed + phase * 3) % (NATIVE_H + 20)
        sway = anim.wave(tick + phase, 0, 6, 80 + seed % 40)
        wide = ((tick + phase) // 8) % 2 == 0
        result.append((int(start_x + sway) % NATIVE_W, NATIVE_H + 10 - int(fall), seed % 4, wide))
    return result
