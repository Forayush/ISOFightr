"""Match rules: the countdown, stock and time modes, sudden death, stats and the result.

Plan note "13 - Game Modes UI and Flow" ("Modes", "Results screen"). Runs as the last step of
every tick. Stock mode ends when one fighter has stocks left; time mode ends when the clock
runs out and the best score (KOs minus falls) wins. Any tie is settled by sudden death.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from isofightr.sim.constants import KO_CREDIT_FRAMES, SUDDEN_DEATH_DAMAGE
from isofightr.sim.events import HitEvent, KoEvent, MatchEndEvent, SuddenDeathEvent
from isofightr.sim.fighter import NO_PARTNER, Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Dir8, facing_from_move
from isofightr.sim.math3d import ZERO2, ZERO3
from isofightr.sim.stage import NO_PLATFORM
from isofightr.sim.states.base import change_state

if TYPE_CHECKING:
    from isofightr.sim.match import Match

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
    placements: tuple[tuple[int, ...], ...]
    """Player indices by rank, best first; players sharing a rank share a group."""


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


def step(match: Match) -> None:
    """Run the clock and decide whether the match is over (tick step 9)."""
    if match.phase is not MatchPhase.PLAYING or len(match.fighters) < 2:
        return
    if match.time_left is not None:
        match.time_left -= 1
    fallen = [
        event.player
        for event in match.events
        if isinstance(event, KoEvent) and match.fighters[event.player].eliminated
    ]
    alive = [fighter.player_index for fighter in match.fighters if not fighter.eliminated]
    if len(alive) == 1:
        _finish(match, alive[0])
    elif not alive:
        _start_sudden_death(match, fallen)  # the last fighters fell on the same tick
    elif match.time_left is not None and match.time_left <= 0:
        best = max(match.stats[index].score for index in alive)
        leaders = [index for index in alive if match.stats[index].score == best]
        if len(leaders) == 1:
            _finish(match, leaders[0])
        else:
            _start_sudden_death(match, leaders)


def _finish(match: Match, winner: int) -> None:
    match.phase = MatchPhase.OVER
    match.result = MatchResult(winner, placements(match, winner))
    match.events.append(MatchEndEvent(winner))


def placements(match: Match, winner: int) -> tuple[tuple[int, ...], ...]:
    """Rank the players: the winner, then by score in time mode or by who lasted longest."""
    others = [fighter.player_index for fighter in match.fighters if fighter.player_index != winner]
    if match.rules.time_frames is not None:
        ranked: list[tuple[int, ...]] = []
        for score in sorted({match.stats[index].score for index in others}, reverse=True):
            ranked.append(tuple(index for index in others if match.stats[index].score == score))
        return ((winner,), *ranked)
    out_order = [index for index in match.eliminated if index != winner]
    survivors = [index for index in others if index not in out_order]
    later_first = list(dict.fromkeys(reversed(out_order)))
    return ((winner,), *((index,) for index in (*survivors, *later_first)))


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
