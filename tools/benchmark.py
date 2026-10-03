"""Measure how long the simulation, the CPU players and drawing take.

Usage::

    uv run python tools/benchmark.py              # sim, CPUs and drawing
    uv run python tools/benchmark.py --no-draw    # no window needed
    uv run python tools/benchmark.py --profile sim|cpu|draw   # print the hottest functions

Plan note "16 - Testing Debug and Tooling" (benchmark) and the M11 performance pass. One 60 Hz
frame is 16.7 ms: a tick of the sim plus the CPUs plus a draw must fit well inside it.
"""

import argparse
import cProfile
import pstats
import time
from collections.abc import Callable

from isofightr.ai.controller import CpuController
from isofightr.ai.random_inputs import random_inputs
from isofightr.ai.view import observe
from isofightr.config import TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.sim.match import Match, MatchRules

ROSTER = ("rook", "bramble", "zephyr", "mote")
SIM_TICKS = 20000
CPU_TICKS = 6000
DRAW_FRAMES = 300
WARMUP_FRAMES = 60
FRAME_MS = TICK_SECONDS * 1000.0
PROFILE_LINES = 25


def bench_sim(players: int = 4, ticks: int = SIM_TICKS) -> float:
    """Milliseconds per sim tick with ``players`` fighters on random input."""
    characters = [load_character(name) for name in ROSTER[:players]]
    match = Match.create(load_stage("sky_ruins"), characters, seed=1, rules=MatchRules(stocks=None))
    inputs = random_inputs(1, ticks, players)
    started = time.perf_counter()
    for frames in inputs:
        match.tick(frames)
    return (time.perf_counter() - started) * 1000.0 / ticks


def bench_cpu(stage_id: str = "lily_pads", ticks: int = CPU_TICKS) -> tuple[float, float]:
    """Milliseconds per tick of four level 9 CPUs: (thinking, simulating)."""
    stage = load_stage(stage_id)
    characters = [load_character(name) for name in ROSTER]
    match = Match.create(stage, characters, seed=3, rules=MatchRules(stocks=None))
    cpus = [CpuController(index, 9, 3, stage) for index in range(len(characters))]
    cpus[0].think(match)  # record the move knowledge outside the measurement
    think = sim = 0.0
    for _ in range(ticks):
        a = time.perf_counter()
        world = observe(match)
        frames = [cpu.think(match, world) for cpu in cpus]
        b = time.perf_counter()
        match.tick(frames)
        sim += time.perf_counter() - b
        think += b - a
    return think * 1000.0 / ticks, sim * 1000.0 / ticks


def bench_draw(stage_id: str, frames: int = DRAW_FRAMES) -> tuple[float, float]:
    """Milliseconds per frame of a four-CPU battle in a hidden window: (tick, draw)."""
    from isofightr.app import GameWindow
    from isofightr.scenes.battle import BattleView

    window = GameWindow(visible=False)
    window.switch_to()
    characters = [load_character(name) for name in ROSTER]
    view = BattleView(window.pixel_buffer, load_stage(stage_id), characters, seed=5, cpus=[9] * 4)
    window.show_view(view)
    tick = draw = 0.0
    for frame in range(WARMUP_FRAMES + frames):
        a = time.perf_counter()
        view.tick()
        b = time.perf_counter()
        view.on_draw()
        window.ctx.finish()
        c = time.perf_counter()
        if frame >= WARMUP_FRAMES:
            tick += b - a
            draw += c - b
    window.close()
    return tick * 1000.0 / frames, draw * 1000.0 / frames


def profile(run: Callable[[], object]) -> None:
    """Run ``run`` under cProfile and print the functions that took longest."""
    profiler = cProfile.Profile()
    profiler.enable()
    run()
    profiler.disable()
    pstats.Stats(profiler).sort_stats("cumulative").print_stats(PROFILE_LINES)


def main() -> None:
    """Parse arguments and print the measurements."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-draw", action="store_true", help="skip the drawing benchmark")
    parser.add_argument("--profile", choices=("sim", "cpu", "draw"), help="profile one part")
    args = parser.parse_args()
    if args.profile == "sim":
        profile(lambda: bench_sim(4, 5000))
        return
    if args.profile == "cpu":
        profile(lambda: bench_cpu(ticks=2000))
        return
    if args.profile == "draw":
        profile(lambda: bench_draw("lily_pads", 200))
        return
    print(f"one frame at 60 Hz is {FRAME_MS:.1f} ms")
    for players in (2, 4):
        print(f"sim, {players} fighters, random input: {bench_sim(players):.3f} ms/tick")
    think, sim = bench_cpu()
    print(f"four level 9 CPUs: {think:.3f} ms/tick thinking, {sim:.3f} ms/tick sim")
    if args.no_draw:
        return
    for stage_id in list_stage_ids():
        tick, draw = bench_draw(stage_id)
        share = (tick + draw) / FRAME_MS * 100.0
        print(f"{stage_id:14} tick {tick:.2f} ms, draw {draw:.2f} ms: {share:.0f}% of a frame")


if __name__ == "__main__":
    main()
