"""Tests for the match loop itself: tick order, determinism, the state hash, goldens, the RNG.

Plan notes "02 - Technical Architecture" (determinism rules, entity model) and
"16 - Testing Debug and Tooling" (state hash, golden replays).
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from helpers import hold, make_match, neutral, random_inputs, run
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.rng import Rng
from isofightr.sim.states import STATES

GOLDENS_DIR = Path(__file__).parent / "goldens"


def play(match: Match, inputs: list[list[InputFrame]]) -> Match:
    for frames in inputs:
        match.tick(frames)
    return match


# --- tick basics --------------------------------------------------------------------------


def test_every_state_id_has_a_registered_state() -> None:
    assert set(STATES) == set(StateId)
    assert all(state.id is state_id for state_id, state in STATES.items())


def test_tick_counts_frames_and_needs_one_input_per_fighter() -> None:
    match = make_match()
    assert match.frame == 0
    run(match, neutral(3))
    assert match.frame == 3
    with pytest.raises(ValueError, match="expected 2 input frames, got 1"):
        match.tick([NEUTRAL_INPUT])


def test_events_only_hold_the_latest_tick() -> None:
    match = make_match()
    run(match, [InputFrame(held=Button.JUMP)] * 4)
    assert len(match.events) == 1
    run(match, neutral(1))
    assert match.events == []


def test_fighters_are_processed_in_player_index_order() -> None:
    match = make_match(fighters=("rook", "rook", "rook", "rook"))
    assert [fighter.player_index for fighter in match.fighters] == [0, 1, 2, 3]
    assert [fighter.pos for fighter in match.fighters] == [
        match.stage.spawn_point(index) for index in range(4)
    ]


def test_a_match_needs_between_one_and_four_fighters() -> None:
    with pytest.raises(ValueError, match="1 to 4 fighters"):
        make_match(fighters=())
    with pytest.raises(ValueError, match="1 to 4 fighters"):
        make_match(fighters=("rook",) * 5)
    assert len(make_match(fighters=("rook",)).fighters) == 1


def test_input_reaches_the_fighter_on_the_same_tick() -> None:
    match = make_match()
    run(match, hold(Dir8.SE, frames=1))
    assert match.fighters[0].state is StateId.DASH
    assert match.fighters[1].state is StateId.IDLE


def test_second_player_is_driven_by_the_second_input() -> None:
    match = make_match()
    run(match, neutral(1), hold(Dir8.NW, frames=1))
    assert match.fighters[0].state is StateId.IDLE
    assert match.fighters[1].state is StateId.DASH


# --- determinism --------------------------------------------------------------------------


def test_same_inputs_and_seed_give_the_same_state_hash() -> None:
    inputs = random_inputs(seed=7, frames=1500)
    first = play(make_match("sky_ruins", seed=3), inputs)
    second = play(make_match("sky_ruins", seed=3), inputs)
    assert first.state_hash() == second.state_hash()
    assert first.fighters[0].pos == second.fighters[0].pos


def test_the_hash_matches_at_every_tick_not_just_the_end() -> None:
    inputs = random_inputs(seed=11, frames=400)
    first, second = make_match("sky_ruins"), make_match("sky_ruins")
    for frames in inputs:
        first.tick(frames)
        second.tick(frames)
        assert first.state_hash() == second.state_hash()


def test_different_inputs_or_seed_give_a_different_hash() -> None:
    base = play(make_match(seed=1), random_inputs(seed=7, frames=300)).state_hash()
    assert play(make_match(seed=1), random_inputs(seed=8, frames=300)).state_hash() != base
    assert play(make_match(seed=2), random_inputs(seed=7, frames=300)).state_hash() != base


def test_a_deep_copy_continues_identically() -> None:
    """Every mutable sim object must be copyable: the basis for replays and rollback."""
    inputs = random_inputs(seed=5, frames=600)
    original = play(make_match("sky_ruins"), inputs[:300])
    clone = copy.deepcopy(original)
    assert clone.state_hash() == original.state_hash()
    play(original, inputs[300:])
    assert clone.state_hash() != original.state_hash(), "the clone did not move with it"
    play(clone, inputs[300:])
    assert clone.state_hash() == original.state_hash()


def test_the_hash_sees_small_state_changes() -> None:
    match = make_match()
    before = match.state_hash()
    match.fighters[1].damage = 0.5
    assert match.state_hash() != before
    match.fighters[1].damage = 0.0
    assert match.state_hash() == before
    match.rng.next_u32()
    assert match.state_hash() != before


def test_the_hash_ignores_float_noise_below_a_millionth() -> None:
    match = make_match()
    before = match.state_hash()
    fighter = match.fighters[0]
    fighter.pos = fighter.pos + type(fighter.pos)(1e-9, 0.0, 0.0)
    assert match.state_hash() == before


def test_random_play_survives_and_keeps_fighters_inside_the_blast_zone_or_ko() -> None:
    """A light soak: thousands of random ticks must never leave a fighter in a broken state."""
    match = make_match("sky_ruins", stocks=None)
    for frames in random_inputs(seed=21, frames=6000):
        match.tick(frames)
        for fighter in match.fighters:
            assert fighter.in_play or fighter.state is StateId.KO
            if fighter.in_play:
                assert match.stage.blast_zone.contains(fighter.pos)
            if fighter.grounded and fighter.state is not StateId.REVIVAL:
                support = match.stage.support_below(fighter.pos.x, fighter.pos.y, fighter.pos.z)
                assert support is None or support <= fighter.pos.z + 1e-6


# --- goldens ------------------------------------------------------------------------------


def golden_match(golden: dict[str, Any]) -> Match:
    """Build the match a golden file describes. ``start_damage`` (optional) is the percent
    every fighter starts on, so that random hits launch hard enough to tumble; ``rules``
    (optional) turns on optional match rules."""
    rules = MatchRules(stocks=golden["stocks"], **golden.get("rules", {}))
    characters = [load_character(name) for name in golden["characters"]]
    match = Match.create(load_stage(golden["stage"]), characters, golden["seed"], rules)
    for fighter in match.fighters:
        fighter.damage = golden.get("start_damage", 0.0)
    return match


@pytest.mark.parametrize("path", sorted(GOLDENS_DIR.glob("*.json")), ids=lambda path: path.stem)
def test_golden_state_hash(path: Path, update_goldens: bool) -> None:
    """A recorded run must end in the recorded state hash.

    A mismatch means gameplay changed. If that was intended, re-record with
    ``uv run pytest --update-goldens`` and say so in the commit message.
    """
    golden = json.loads(path.read_text(encoding="utf-8"))
    match = golden_match(golden)
    inputs = random_inputs(golden["input_seed"], golden["ticks"], len(golden["characters"]))
    actual = play(match, inputs).state_hash()
    if update_goldens:
        golden["hash"] = actual
        text = json.dumps(golden, indent=2) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")  # LF on every platform
    assert actual == golden["hash"]


SCENARIO_ONLY_STATES = {
    StateId.SHIELD_BREAK,
    StateId.DIZZY,
    StateId.LEDGE_TRUMPED,
    StateId.WALL_TECH,
    StateId.GETUP_ROLL,
}
"""States random input practically never reaches (they need a shield held until it breaks, two
fighters on one ledge spot, a well-timed tech against a wall, or a stick flick as the very
first input after a knockdown). Scenario tests cover them:
``test_defense_scenarios.py`` and ``test_ledge_tech_scenarios.py``."""


def test_golden_runs_between_them_visit_every_state() -> None:
    """A golden that never reaches a state cannot notice that state changing.

    Every state must be visited, except the few listed in ``SCENARIO_ONLY_STATES`` (which
    random play may still happen to reach).
    """
    visited: set[StateId] = set()
    for path in sorted(GOLDENS_DIR.glob("*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        match = golden_match(golden)
        players = len(golden["characters"])
        for frames in random_inputs(golden["input_seed"], golden["ticks"], players):
            match.tick(frames)
            visited.update(fighter.state for fighter in match.fighters)
    assert set(StateId) - SCENARIO_ONLY_STATES - visited == set()


def test_goldens_exist() -> None:
    assert sorted(path.stem for path in GOLDENS_DIR.glob("*.json")) == [
        "combat_sky_ruins",
        "combat_training_grid",
        "movement_sky_ruins",
        "movement_training_grid",
        "roster_sky_ruins",
    ]


# --- rules and rng ------------------------------------------------------------------------


def test_default_rules_are_three_stocks() -> None:
    assert MatchRules().stocks == 3
    assert make_match().fighters[0].stocks == 3


def test_rng_is_deterministic_per_seed() -> None:
    first, second, other = Rng.seeded(42), Rng.seeded(42), Rng.seeded(43)
    sequence = [first.next_u32() for _ in range(100)]
    assert sequence == [second.next_u32() for _ in range(100)]
    assert sequence != [other.next_u32() for _ in range(100)]
    assert all(0 <= value < 2**32 for value in sequence)


def test_rng_matches_the_pcg32_reference_output() -> None:
    """First outputs of the reference ``pcg32`` demo: seed 42, stream 54."""
    rng = Rng(state=0, increment=(54 << 1) | 1)
    rng.next_u32()
    rng.state = (rng.state + 42) & ((1 << 64) - 1)
    rng.next_u32()
    assert [rng.next_u32() for _ in range(6)] == [
        0xA15C02B7,
        0x7B47F409,
        0xBA1D3330,
        0x83D2F293,
        0xBFA4784B,
        0xCBED606E,
    ]


def test_rng_ranges() -> None:
    rng = Rng.seeded(1)
    floats = [rng.random() for _ in range(1000)]
    assert all(0.0 <= value < 1.0 for value in floats)
    assert 0.4 < sum(floats) / len(floats) < 0.6
    rolls = [rng.between(1, 6) for _ in range(2000)]
    assert set(rolls) == {1, 2, 3, 4, 5, 6}
    assert {rng.below(1) for _ in range(10)} == {0}
    with pytest.raises(ValueError, match="bound must be positive"):
        rng.below(0)


def test_rng_copies_with_its_state() -> None:
    rng = Rng.seeded(9)
    rng.next_u32()
    clone = copy.deepcopy(rng)
    assert [rng.next_u32() for _ in range(5)] == [clone.next_u32() for _ in range(5)]
