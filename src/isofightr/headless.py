"""Run the simulation without a window: benchmarks, soak runs and determinism checks.

Plan note "16 - Testing Debug and Tooling" (``--headless --frames N``). The sim is driven by
seeded random movement input, so the same command always ends in the same state hash.
Imports no ``arcade``: it works on a machine with no display.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass

from isofightr.ai.random_inputs import random_inputs
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.events import KoEvent
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.stage import Stage

MILLISECONDS = 1000.0


@dataclass(frozen=True, slots=True)
class HeadlessReport:
    """What a headless run did."""

    stage_id: str
    fighters: int
    ticks: int
    seconds: float
    knockouts: int
    state_hash: str

    @property
    def ms_per_tick(self) -> float:
        """Average wall-clock cost of one tick, in milliseconds."""
        return self.seconds * MILLISECONDS / self.ticks

    def summary(self) -> str:
        """Return a short human-readable report."""
        return (
            f"{self.ticks} ticks on {self.stage_id} with {self.fighters} fighters: "
            f"{self.ms_per_tick:.4f} ms/tick, {self.knockouts} KOs, "
            f"state hash {self.state_hash}"
        )


def run_headless(
    stage: Stage, characters: Sequence[CharacterDef], seed: int, ticks: int
) -> HeadlessReport:
    """Play ``ticks`` ticks on seeded random input and report the result.

    Stocks are infinite, so the run never ends early. ``seed`` seeds both the match and the
    input, so one number reproduces the whole run.
    """
    match = Match.create(stage, characters, seed=seed, rules=MatchRules(stocks=None))
    inputs = random_inputs(seed, ticks, len(characters))
    knockouts = 0
    started = time.perf_counter()
    for frames in inputs:
        match.tick(frames)
        knockouts += sum(isinstance(event, KoEvent) for event in match.events)
    seconds = time.perf_counter() - started
    return HeadlessReport(
        stage_id=stage.id,
        fighters=len(characters),
        ticks=ticks,
        seconds=seconds,
        knockouts=knockouts,
        state_hash=match.state_hash(),
    )
