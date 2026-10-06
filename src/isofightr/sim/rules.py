"""Match rules: the countdown, stock and time modes, sudden death, stats and the result.

Plan note "13 - Game Modes UI and Flow" ("Modes", "Results screen"). Runs as the last step of
every tick. Stock mode ends when one fighter has stocks left; time mode ends when the clock
runs out and the best score (KOs minus falls) wins. With both a stock count and a clock
(decision D-061) the match ends on whichever comes first, and when it is the clock the most
stocks win, then the least damage. Any tie is settled by sudden death.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from isofightr.sim.constants import KO_CREDIT_FRAMES, SUDDEN_DEATH_DAMAGE
from isofightr.sim.events import HitEvent, KoEvent, MatchEndEvent, SuddenDeathEvent
from isofightr.sim.fighter import NO_PARTNER, NO_TEAM, Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Dir8, facing_from_move
from isofightr.sim.math3d import ZERO2, ZERO3
from isofightr.sim.stage import NO_PLATFORM
from isofightr.sim.states.base import change_state

if TYPE_CHECKING:
    from isofightr.sim.match import Match

STANDING_DECIMALS = 6
"""Damage is compared at the state hash's precision when the clock decides a stock match."""
COMBO_STATES = frozenset({StateId.FLINCH, StateId.TUMBLE, StateId.GRABBED})
"""States in which a fighter cannot act, so further hits extend the combo."""


class MatchPhase(Enum):
    """Where a match is in its flow."""

    COUNTDOWN = "countdown"
    """"3, 2, 1": fighters stand ready and ignore input."""
    PLAYING = "playing"
    OVER = "over"


@dataclass(slots=True)
class PlayerStats:
    """One player's numbers for the results screen."""

    kos: int = 0
    falls: int = 0
    """Stocks lost, however it happened."""
    self_destructs: int = 0
    """Falls nobody else gets credit for."""
    damage_given: float = 0.0
    damage_taken: float = 0.0
    peak_damage: float = 0.0
    longest_combo: int = 0

    @property
    def score(self) -> int:
        """Time-mode score: +1 per KO, -1 per fall."""
        return self.kos - self.falls


@dataclass(frozen=True, slots=True)
class MatchResult:
    """How a match ended."""

    winner: int
    """Player index of the winner (the first player of the winning team in a team match)."""
    placements: tuple[tuple[int, ...], ...]
    """Player indices by rank, best first; a team, or players sharing a rank, share a group."""
    winners: tuple[int, ...] = ()
    """Every player on the winning side."""


def track_hits(match: Match) -> None:
    """Update stats, KO credit and combo counts from this tick's hits."""
    for event in match.events:
        if not isinstance(event, HitEvent) or event.damage <= 0.0:
            continue
        target = match.fighters[event.target]
        match.stats[event.attacker].damage_given += event.damage
        match.stats[event.target].damage_taken += event.damage
        target.last_hit_by = event.attacker
        target.last_hit_timer = KO_CREDIT_FRAMES
        if target.combo_by == event.attacker and target.combo_hits > 0:
            target.combo_hits += 1
        else:
            target.combo_hits = 1
            target.combo_by = event.attacker
        stats = match.stats[event.attacker]
        stats.longest_combo = max(stats.longest_combo, target.combo_hits)
    for fighter in match.fighters:
        stats = match.stats[fighter.player_index]
        stats.peak_damage = max(stats.peak_damage, fighter.damage)


def upkeep(fighter: Fighter) -> None:
    """Run a fighter's rule timers: KO credit wears off, and a combo ends once it can act."""
    if fighter.last_hit_timer > 0:
        fighter.last_hit_timer -= 1
        if fighter.last_hit_timer == 0:
            fighter.last_hit_by = NO_PARTNER
    stunned = fighter.state in COMBO_STATES and (
        fighter.state is not StateId.TUMBLE or fighter.hitstun > 0
    )
    if fighter.combo_hits > 0 and not stunned and fighter.launch is None:
        fighter.combo_hits = 0
        fighter.combo_by = NO_PARTNER


def record_knockout(match: Match, fighter: Fighter) -> int | None:
    """Count a fall, credit the KO, and note an elimination. Returns who gets the KO."""
    stats = match.stats[fighter.player_index]
    stats.falls += 1
    credited: int | None = None
    if fighter.last_hit_by != NO_PARTNER:
        credited = fighter.last_hit_by
        match.stats[credited].kos += 1
    else:
        stats.self_destructs += 1
    if fighter.eliminated:
        match.eliminated.append(fighter.player_index)
    return credited


def side_of(fighter: Fighter) -> tuple[bool, int]:
    """Return the side a fighter plays for: its team, or itself in a free-for-all."""
    if fighter.team != NO_TEAM:
        return (True, fighter.team)
    return (False, fighter.player_index)


def sides(match: Match) -> dict[tuple[bool, int], tuple[int, ...]]:
    """Return every side and the player indices on it, in player order."""
    grouped: dict[tuple[bool, int], list[int]] = {}
    for fighter in match.fighters:
        grouped.setdefault(side_of(fighter), []).append(fighter.player_index)
    return {side: tuple(players) for side, players in grouped.items()}


def side_score(match: Match, players: tuple[int, ...]) -> int:
    """Return a side's time-mode score: the sum of its players' scores."""
    return sum(match.stats[index].score for index in players)


def side_standing(match: Match, players: tuple[int, ...]) -> tuple[int, float]:
    """Return how a side stands when the clock runs out on a stock match, bigger is better:
    its stocks left, then its damage counted against it (decision D-061). A side's stocks
    and the damage of its fighters still in the match are added up."""
    fighters = [match.fighters[index] for index in players]
    stocks = sum(fighter.stocks or 0 for fighter in fighters)
    damage = sum(fighter.damage for fighter in fighters if not fighter.eliminated)
    return (stocks, -round(damage, STANDING_DECIMALS))


def step(match: Match) -> None:
    """Run the clock and decide whether the match is over (tick step 9).

    A side is a team, or a single player in a free-for-all. A side is alive while any of its
    fighters has stocks left.
    """
    if match.phase is not MatchPhase.PLAYING:
        return
    all_sides = sides(match)
    if len(all_sides) < 2:
        return
    if match.time_left is not None:
        match.time_left -= 1
    alive = {
        side: players
        for side, players in all_sides.items()
        if any(not match.fighters[index].eliminated for index in players)
    }
    if len(alive) == 1:
        _finish(match, next(iter(alive.values())))
    elif not alive:
        # The last fighters fell on the same tick: their sides settle it.
        fallen = {
            side_of(match.fighters[event.player])
            for event in match.events
            if isinstance(event, KoEvent) and match.fighters[event.player].eliminated
        }
        tied = [index for side, players in all_sides.items() if side in fallen for index in players]
        _start_sudden_death(match, tied)
    elif match.time_left is not None and match.time_left <= 0:
        leaders: list[tuple[int, ...]]
        if match.rules.stocks is not None:
            top = max(side_standing(match, players) for players in alive.values())
            leaders = [
                players for players in alive.values() if side_standing(match, players) == top
            ]
        else:
            best = max(side_score(match, players) for players in alive.values())
            leaders = [players for players in alive.values() if side_score(match, players) == best]
        if len(leaders) == 1:
            _finish(match, leaders[0])
        else:
            _start_sudden_death(match, [index for players in leaders for index in players])


def _finish(match: Match, winners: tuple[int, ...]) -> None:
    match.phase = MatchPhase.OVER
    match.result = MatchResult(winners[0], placements(match, winners), winners)
    match.events.append(MatchEndEvent(winners[0]))


def placements(match: Match, winners: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    """Rank the sides: the winners, then by score in time mode (level scores share a rank)
    or by which side lasted longest in stock mode."""
    others = [players for players in sides(match).values() if players != winners]
    timed = match.rules.time_frames is not None
    if timed and match.rules.stocks is not None:
        # Stocks and a clock: sides still in by stocks then damage (level sides share a
        # rank), then the sides that ran out, last out first.
        def is_out(players: tuple[int, ...]) -> bool:
            return all(match.fighters[index].eliminated for index in players)

        standing = [players for players in others if not is_out(players)]
        ranked_in: list[tuple[int, ...]] = []
        marks = sorted({side_standing(match, players) for players in standing}, reverse=True)
        for mark in marks:
            level_sides = [p for p in standing if side_standing(match, p) == mark]
            ranked_in.append(tuple(index for players in level_sides for index in players))
        gone = [players for players in others if is_out(players)]
        gone.sort(key=lambda players: max(match.eliminated.index(i) for i in players), reverse=True)
        return (winners, *ranked_in, *gone)
    if timed:
        ranked: list[tuple[int, ...]] = []
        scores = sorted({side_score(match, players) for players in others}, reverse=True)
        for score in scores:
            level = [players for players in others if side_score(match, players) == score]
            ranked.append(tuple(index for players in level for index in players))
        return (winners, *ranked)

    def out_at(players: tuple[int, ...]) -> int:
        """When a side's last fighter went out (sides still standing sort first)."""
        gone = [match.eliminated.index(index) for index in players if index in match.eliminated]
        return max(gone) if len(gone) == len(players) else len(match.eliminated)

    return (winners, *sorted(others, key=out_at, reverse=True))


def _start_sudden_death(match: Match, players: list[int]) -> None:
    """Settle a tie: the tied fighters restart on their spawn points at high damage with one
    stock each; everyone else is out. The clock stops and the countdown runs again."""
    match.sudden_death = True
    match.time_left = None
    match.projectiles = []
    match.countdown = match.rules.countdown_frames
    match.phase = MatchPhase.COUNTDOWN if match.countdown > 0 else MatchPhase.PLAYING
    centre = match.stage.respawn_point()
    for fighter in match.fighters:
        index = fighter.player_index
        if index not in players:
            fighter.stocks = 0
            if index not in match.eliminated:
                match.eliminated.append(index)
            if fighter.state is not StateId.KO:
                change_state(match, fighter, StateId.KO)
            continue
        match.eliminated = [out for out in match.eliminated if out != index]
        change_state(match, fighter, StateId.IDLE)
        fighter.stocks = 1
        fighter.pos = match.stage.spawn_point(index)
        fighter.facing = facing_from_move((centre - fighter.pos).xy) or Dir8.SE
        fighter.ground = GroundKind.CELL
        fighter.platform = NO_PLATFORM
        fighter.vel = ZERO3
        fighter.kb_vel = ZERO3
        fighter.drive = ZERO2
        fighter.damage = SUDDEN_DEATH_DAMAGE
        fighter.hitlag = 0
        fighter.hitstun = 0
        fighter.launch = None
        fighter.invincible_frames = 0
        fighter.intangible_frames = 0
        fighter.air_jumps_left = fighter.character.movement.air_jumps
        fighter.buffer.clear()
    match.events.append(SuddenDeathEvent(tuple(players)))
