"""Tests for match rules: countdown, stock and time modes, sudden death, stats and results.

Plan note "13 - Game Modes UI and Flow" ("Modes", "Results screen").
"""

import copy

import pytest

from helpers import hold, make_match, neutral, place, run
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.constants import KO_CREDIT_FRAMES, SUDDEN_DEATH_DAMAGE
from isofightr.sim.events import KoEvent, MatchEndEvent, SuddenDeathEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.rules import MatchPhase, MatchResult, PlayerStats

ROOK = load_character("rook")
FAR_BELOW = Vec3(5.5, 5.5, -9.0)
"""Past the bottom blast zone of the Training Grid: a fighter put here is KO'd next tick."""


def new_match(players: int = 2, **rules: object) -> Match:
    stage = load_stage("training_grid")
    return Match.create(stage, [ROOK] * players, seed=1, rules=MatchRules(**rules))  # type: ignore[arg-type]


def tick(match: Match, frames: int = 1) -> None:
    for _ in range(frames):
        match.tick([InputFrame()] * len(match.fighters))


def knock_out(match: Match, player: int) -> None:
    """Drop a fighter through the bottom blast zone."""
    fighter = match.fighters[player]
    place(match, fighter, FAR_BELOW.x, FAR_BELOW.y, z=FAR_BELOW.z)
    tick(match)
    assert any(isinstance(e, KoEvent) and e.player == player for e in match.events)


def knock_out_until_gone(match: Match, player: int) -> None:
    """Take every stock a fighter has."""
    fighter = match.fighters[player]
    while not fighter.eliminated:
        knock_out(match, player)
        if not fighter.eliminated:
            for _ in range(200):
                if fighter.state is StateId.REVIVAL:
                    break
                tick(match)


# --- countdown ----------------------------------------------------------------------------


def test_matches_start_at_once_unless_the_rules_ask_for_a_countdown() -> None:
    match = new_match()
    assert match.phase is MatchPhase.PLAYING and match.countdown == 0
    assert match.result is None and match.time_left is None


def test_fighters_ignore_input_during_the_countdown() -> None:
    match = new_match(countdown_frames=30)
    fighter = match.fighters[0]
    start = fighter.pos
    assert match.phase is MatchPhase.COUNTDOWN
    run(match, hold(Dir8.SE, Button.JUMP, frames=29))
    assert match.phase is MatchPhase.COUNTDOWN and match.countdown == 1
    assert fighter.pos == start and fighter.state is StateId.IDLE
    run(match, hold(Dir8.SE, frames=1))
    assert match.phase is MatchPhase.PLAYING
    run(match, hold(Dir8.SE, frames=5))
    assert fighter.pos.x > start.x, "free to move once it says GO"


def test_the_clock_waits_for_the_countdown() -> None:
    match = new_match(countdown_frames=10, time_frames=600, stocks=None)
    tick(match, 10)
    assert match.time_left == 600
    tick(match, 5)
    assert match.time_left == 595


# --- stock mode ---------------------------------------------------------------------------


def test_stock_match_ends_when_one_fighter_is_left() -> None:
    match = new_match(stocks=2)
    knock_out(match, 1)
    assert match.phase is MatchPhase.PLAYING and match.fighters[1].stocks == 1
    knock_out_until_gone(match, 1)
    assert match.phase is MatchPhase.OVER
    assert match.result == MatchResult(winner=0, placements=((0,), (1,)))
    assert [e for e in match.events if isinstance(e, MatchEndEvent)] == [MatchEndEvent(0)]
    assert match.eliminated == [1]


def test_the_sim_keeps_running_after_the_match_is_over() -> None:
    match = new_match(stocks=1)
    knock_out(match, 1)
    result = match.result
    start = match.fighters[0].pos
    run(match, hold(Dir8.SE, frames=20))
    assert match.result is result and match.phase is MatchPhase.OVER
    assert match.fighters[0].pos.x > start.x
    assert not [e for e in match.events if isinstance(e, MatchEndEvent)], "announced once"


def test_four_player_placements_follow_the_order_of_elimination() -> None:
    match = new_match(players=4, stocks=1)
    for player in (2, 0, 3):
        assert match.phase is MatchPhase.PLAYING
        knock_out(match, player)
    assert match.result == MatchResult(winner=1, placements=((1,), (3,), (0,), (2,)))


def test_infinite_stocks_never_end() -> None:
    match = new_match(stocks=None)
    for _ in range(5):
        knock_out(match, 1)
        tick(match, 150)
    assert match.phase is MatchPhase.PLAYING and match.stats[1].falls == 5


def test_a_single_fighter_match_never_ends() -> None:
    match = new_match(players=1, stocks=1)
    knock_out(match, 0)
    tick(match, 10)
    assert match.phase is MatchPhase.PLAYING and match.result is None


# --- KO credit and stats ------------------------------------------------------------------


def test_a_ko_goes_to_the_last_attacker_and_a_lone_fall_is_a_self_destruct() -> None:
    match = new_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0)
    run(match, hold(buttons=Button.ATTACK, frames=1) + neutral(20))
    assert (target.last_hit_by, target.last_hit_timer > 0) == (0, True)
    knock_out(match, 1)
    [event] = [e for e in match.events if isinstance(e, KoEvent)]
    assert event.credited_to == 0
    assert (match.stats[0].kos, match.stats[1].falls, match.stats[1].self_destructs) == (1, 1, 0)

    knock_out(match, 0)
    [event] = [e for e in match.events if isinstance(e, KoEvent)]
    assert event.credited_to is None
    assert (match.stats[0].falls, match.stats[0].self_destructs, match.stats[1].kos) == (1, 1, 0)


def test_ko_credit_wears_off() -> None:
    match = new_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0)
    run(match, hold(buttons=Button.ATTACK, frames=1) + neutral(KO_CREDIT_FRAMES + 30))
    assert target.last_hit_by == -1
    knock_out(match, 1)
    assert match.stats[0].kos == 0 and match.stats[1].self_destructs == 1


def test_damage_and_combo_stats() -> None:
    match = new_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0)
    jab = hold(buttons=Button.ATTACK, frames=1)
    run(match, jab + neutral(8) + jab + neutral(10) + jab + neutral(60))
    given = match.stats[0].damage_given
    assert given == pytest.approx(target.damage) and given > 10
    assert match.stats[1].damage_taken == pytest.approx(given)
    assert match.stats[1].peak_damage == pytest.approx(target.damage)
    assert match.stats[0].longest_combo >= 2, "the jab chain connects while the target is stunned"
    assert target.combo_hits == 0, "the combo ended when the target could act again"
    run(match, neutral(60) + jab + neutral(40))
    assert match.stats[0].longest_combo >= 2 and match.stats[1].longest_combo == 0


def test_score_is_kos_minus_falls() -> None:
    assert PlayerStats(kos=3, falls=1, self_destructs=1).score == 2


# --- time mode ----------------------------------------------------------------------------


def test_time_match_goes_to_the_best_score() -> None:
    match = new_match(stocks=None, time_frames=400)
    assert match.time_left == 400
    knock_out(match, 1)  # a self-destruct: P2 is on -1
    tick(match, 397)
    assert match.phase is MatchPhase.PLAYING and match.time_left == 2
    tick(match, 2)
    assert match.phase is MatchPhase.OVER
    assert match.result == MatchResult(winner=0, placements=((0,), (1,)))


def test_time_mode_ranks_by_score_and_ties_share_a_rank() -> None:
    match = new_match(players=4, stocks=None, time_frames=600)
    for player in (1, 2, 1, 3):
        knock_out(match, player)
        tick(match, 100)
    tick(match, 600)
    assert match.result is not None
    assert match.result.placements == ((0,), (2, 3), (1,))


def test_a_tied_time_match_goes_to_sudden_death() -> None:
    match = new_match(players=3, stocks=None, time_frames=300, countdown_frames=20)
    tick(match, 20)
    knock_out(match, 2)
    tick(match, 298)
    assert match.phase is MatchPhase.PLAYING and not match.sudden_death
    tick(match, 1)
    [event] = [e for e in match.events if isinstance(e, SuddenDeathEvent)]
    assert event.players == (0, 1)
    assert match.sudden_death and match.time_left is None
    assert match.phase is MatchPhase.COUNTDOWN and match.countdown == 20
    first, second, third = match.fighters
    assert first.damage == second.damage == SUDDEN_DEATH_DAMAGE == 300
    assert (first.stocks, second.stocks, third.stocks) == (1, 1, 0)
    assert first.pos == match.stage.spawn_point(0) and second.pos == match.stage.spawn_point(1)
    assert third.eliminated and not third.in_play
    tick(match, 20)
    knock_out(match, 0)
    assert match.phase is MatchPhase.OVER
    assert match.result is not None and match.result.winner == 1


def test_the_last_two_falling_together_in_a_stock_match_is_sudden_death() -> None:
    match = new_match(stocks=1)
    for fighter in match.fighters:
        place(match, fighter, FAR_BELOW.x, FAR_BELOW.y, z=FAR_BELOW.z)
    tick(match)
    assert match.sudden_death and match.phase is MatchPhase.PLAYING
    assert [fighter.stocks for fighter in match.fighters] == [1, 1]
    assert all(fighter.in_play and fighter.damage == 300 for fighter in match.fighters)
    knock_out(match, 1)
    assert match.result is not None and match.result.winner == 0


# --- launch rate --------------------------------------------------------------------------


def launched(rate: float) -> Fighter:
    match = new_match(stocks=None, launch_rate=rate)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0, damage=50.0)
    run(match, hold(buttons=Button.STRONG, frames=1) + neutral(20))
    return target


def test_launch_rate_scales_knockback() -> None:
    normal, double = launched(1.0), launched(2.0)
    assert double.last_knockback == pytest.approx(normal.last_knockback * 2)
    assert double.damage == normal.damage


# --- determinism --------------------------------------------------------------------------


def test_rule_state_is_hashed_and_copies_exactly() -> None:
    match = new_match(stocks=2, time_frames=5000, countdown_frames=5)
    before = match.state_hash()
    match.stats[0].kos += 1
    assert match.state_hash() != before
    match.stats[0].kos -= 1
    match.time_left = 4000
    assert match.state_hash() != before
    match.time_left = 5000
    assert match.state_hash() == before
    twin = copy.deepcopy(match)
    for _ in range(3):
        knock_out(match, 1)
        knock_out(twin, 1)
        tick(match, 150)
        tick(twin, 150)
    assert match.state_hash() == twin.state_hash() and match.result == twin.result


def test_make_match_default_rules() -> None:
    assert make_match().rules == MatchRules(stocks=3)
