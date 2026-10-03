"""Long soak runs (``pytest -m slow``).

M7 exit criterion: "a 4-player free-for-all ... is stable for 30 minutes". The sim half of
that is checked here: 30 minutes of random input for four players, recorded, then played back
to the same state hash. Plan note "16 - Testing Debug and Tooling".
"""

import math
import os

import pytest

from isofightr.ai.random_inputs import random_inputs
from isofightr.config import CPU_SOFTLOCK_FRAMES, TICK_RATE
from isofightr.data.character_loader import load_character
from isofightr.data.replay_io import match_for
from isofightr.data.stage_loader import load_stage
from isofightr.headless import run_cpu_match
from isofightr.sim.events import KoEvent
from isofightr.sim.match import MatchRules
from isofightr.sim.replay import Recorder, Replay, play_back

SOAK_MINUTES = 30
SOAK_TICKS = SOAK_MINUTES * 60 * TICK_RATE
CHUNK_TICKS = 6000
PLAYERS = 4
SEED = 7


@pytest.mark.slow
def test_four_player_free_for_all_is_stable_for_thirty_minutes() -> None:
    rules = MatchRules(stocks=None, parry=True)
    characters = ("rook", "bramble", "zephyr", "mote")[:PLAYERS]
    recorder = Recorder("sky_ruins", characters, SEED, rules)
    match = match_for(Replay("sky_ruins", characters, SEED, rules, (), ""))
    knockouts = 0
    for chunk in range(SOAK_TICKS // CHUNK_TICKS):
        for frames in random_inputs(SEED + chunk, CHUNK_TICKS, PLAYERS):
            recorder.record(frames)
            match.tick(frames)
            knockouts += sum(1 for event in match.events if isinstance(event, KoEvent))
        for fighter in match.fighters:
            assert all(
                math.isfinite(value)
                for vector in (fighter.pos, fighter.vel, fighter.kb_vel)
                for value in (vector.x, vector.y, vector.z)
            )
            assert 0.0 <= fighter.damage <= 999.0
        assert len(match.projectiles) < 50, "projectiles are cleaned up"
    assert match.frame == SOAK_TICKS and match.result is None
    assert knockouts > 100, "the fighters really did fight"

    replay = recorder.finish(match)
    assert replay.ticks == SOAK_TICKS
    assert play_back(match_for(replay), replay), "the same input gives the same match"


CPU_SOAK_MATCHES = int(os.environ.get("ISOFIGHTR_SOAK_MATCHES", "10"))
"""CPU-vs-CPU matches in the soak (the nightly CI run raises it)."""
CPU_SOAK_STAGES = ("sky_ruins", "final_plateau", "training_grid", "twin_isles", "lily_pads")
CPU_SOAK_MAX_TICKS = 10 * 60 * TICK_RATE


@pytest.mark.slow
def test_cpu_versus_cpu_matches_end_without_soft_locks() -> None:
    """Plan note "15 - CPU AI" ("Testing"): four CPUs, random seeds and stages, no exceptions,
    no fighter stuck in one state for more than 20 seconds, and every match ends."""
    characters = [load_character(name) for name in ("rook", "bramble", "zephyr", "mote")]
    for number in range(CPU_SOAK_MATCHES):
        stage = load_stage(CPU_SOAK_STAGES[number % len(CPU_SOAK_STAGES)])
        levels = (9, 9, 9, 9) if number % 2 == 0 else (9, 7, 5, 3)
        report = run_cpu_match(
            stage,
            characters,
            levels,
            seed=1000 + number,
            rules=MatchRules(stocks=2),
            max_ticks=CPU_SOAK_MAX_TICKS,
        )
        where = f"match {number} on {stage.id}"
        assert report.ended, f"{where} did not end in {CPU_SOAK_MAX_TICKS} ticks"
        assert report.longest_state <= CPU_SOFTLOCK_FRAMES, (
            f"{where}: stuck {report.longest_state} frames in {report.longest_state_name}"
        )
