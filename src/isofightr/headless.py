"""Run the simulation without a window: benchmarks, soak runs and determinism checks.

Plan note "16 - Testing Debug and Tooling" (``--headless --frames N``). The sim is driven by
seeded random movement input, so the same command always ends in the same state hash.
Imports no ``arcade``: it works on a machine with no display.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass

from isofightr.ai.controller import CpuController
from isofightr.ai.random_inputs import random_inputs
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.events import KoEvent
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.replay import Recorder, Replay, play_back
from isofightr.sim.stage import Stage

MILLISECONDS = 1000.0
HEADLESS_RULES = MatchRules(stocks=None)
"""Rules of a headless run: endless stocks, so it never ends early."""


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
    stage: Stage,
    characters: Sequence[CharacterDef],
    seed: int,
    ticks: int,
    recorder: Recorder | None = None,
    cpus: Sequence[int] = (),
) -> HeadlessReport:
    """Play ``ticks`` ticks on seeded random input and report the result.

    Stocks are infinite, so the run never ends early. ``seed`` seeds both the match and the
    input, so one number reproduces the whole run. With a ``recorder`` every tick's input
    is recorded (the recorder must have been made with :data:`HEADLESS_RULES`). Players with
    a CPU level in ``cpus`` (above 0) are played by CPUs instead of random input.
    """
    match = Match.create(stage, characters, seed=seed, rules=HEADLESS_RULES)
    inputs = random_inputs(seed, ticks, len(characters))
    controllers = {
        player: CpuController(player, level, seed, stage)
        for player, level in enumerate(cpus)
        if level > 0
    }
    knockouts = 0
    started = time.perf_counter()
    for random_frames in inputs:
        frames = [
            controllers[player].think(match) if player in controllers else frame
            for player, frame in enumerate(random_frames)
        ]
        if recorder is not None:
            recorder.record(frames)
        match.tick(frames)
        knockouts += sum(isinstance(event, KoEvent) for event in match.events)
    seconds = time.perf_counter() - started
    if recorder is not None:
        recorder.final = recorder.finish(match)
    return HeadlessReport(
        stage_id=stage.id,
        fighters=len(characters),
        ticks=ticks,
        seconds=seconds,
        knockouts=knockouts,
        state_hash=match.state_hash(),
    )


def replay_headless(match: Match, replay: Replay) -> tuple[HeadlessReport, bool]:
    """Play a replay back on its freshly created match. Returns the report and whether the
    match ended on the recorded state hash."""
    started = time.perf_counter()
    matches = play_back(match, replay)
    seconds = time.perf_counter() - started
    report = HeadlessReport(
        stage_id=match.stage.id,
        fighters=len(match.fighters),
        ticks=replay.ticks,
        seconds=seconds,
        knockouts=sum(stats.falls for stats in match.stats),
        state_hash=match.state_hash(),
    )
    return report, matches


@dataclass(frozen=True, slots=True)
class CpuMatchReport:
    """How a match played entirely by CPUs went (plan note "15 - CPU AI", "Testing")."""

    ticks: int
    ended: bool
    longest_state: int
    """The most frames any fighter still in the match spent in one state without a break."""
    longest_state_name: str
    knockouts: int
    self_destructs: int
    winners: tuple[int, ...]
    """Player indices of the winners (empty if the match did not end)."""
    state_hash: str


def run_cpu_match(
    stage: Stage,
    characters: Sequence[CharacterDef],
    levels: Sequence[int],
    seed: int,
    rules: MatchRules,
    max_ticks: int,
) -> CpuMatchReport:
    """Play a match with every player a CPU until it ends (or ``max_ticks``) and report it.

    Fighters that are out of the match (no stocks left) are not counted for the longest
    state, nor is a fighter waiting to come back after a KO.
    """
    match = Match.create(stage, characters, seed=seed, rules=rules)
    controllers = [CpuController(player, level, seed, stage) for player, level in enumerate(levels)]
    runs = [0] * len(characters)
    previous = [fighter.state for fighter in match.fighters]
    longest, longest_name = 0, ""
    knockouts = self_destructs = 0
    ticks = 0
    while ticks < max_ticks and match.result is None:
        ticks += 1
        match.tick([controller.think(match) for controller in controllers])
        for event in match.events:
            if isinstance(event, KoEvent):
                knockouts += 1
                if event.credited_to is None:
                    self_destructs += 1
        for index, fighter in enumerate(match.fighters):
            if fighter.state is previous[index] and fighter.in_play:
                runs[index] += 1
            else:
                runs[index] = 0
                previous[index] = fighter.state
            if runs[index] > longest:
                longest, longest_name = runs[index], fighter.state.value
    return CpuMatchReport(
        ticks=ticks,
        ended=match.result is not None,
        longest_state=longest,
        longest_state_name=longest_name,
        knockouts=knockouts,
        self_destructs=self_destructs,
        winners=tuple(match.result.winners) if match.result is not None else (),
        state_hash=match.state_hash(),
    )
