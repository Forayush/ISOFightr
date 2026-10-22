"""Measure how long the simulation, the CPU players and drawing take.

Usage::

    uv run python tools/benchmark.py              # sim, CPUs and drawing
    uv run python tools/benchmark.py --no-draw    # no window needed
    uv run python tools/benchmark.py --profile sim|cpu|draw   # print the hottest functions
    uv run python tools/benchmark.py --hits sky_ruins --runs 3  # hit effects: a hit storm

Plan note "16 - Testing Debug and Tooling" (benchmark) and the M11 performance pass. One 60 Hz
frame is 16.7 ms: a tick of the sim plus the CPUs plus a draw must fit well inside it.

``--hits`` measures hit effects (decision D-068): a hit storm (two fighters swing at the other
two every ``STORM_CYCLE`` ticks, a rotating list of moves and percents, about a hit every 11
ticks) and a four-CPU match on the same stage, in turn, printing the median and 95th
percentile draw time and the effect layer's live sprites.
"""

import argparse
import cProfile
import pstats
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass

from isofightr.ai.controller import CpuController
from isofightr.ai.random_inputs import random_inputs
from isofightr.ai.view import observe
from isofightr.config import TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.states.base import change_state
from isofightr.sim.states.interrupts import start_move

ROSTER = ("rook", "bramble", "zephyr", "mote")
SIM_TICKS = 20000
CPU_TICKS = 6000
DRAW_FRAMES = 300
WARMUP_FRAMES = 60
FRAME_MS = TICK_SECONDS * 1000.0
PROFILE_LINES = 25
STORM_FRAMES = 600
STORM_WARMUP = 120
STORM_CYCLE = 24
"""Ticks between one round of the hit storm and the next."""
STORM_ROSTER = ("rook", "bramble", "mote", "zephyr")
"""Players 1 and 3 (Rook, Mote) attack; 2 and 4 (Bramble, Zephyr) are hit."""
STORM_MOVES = (
    ("jab1", 0.0),
    ("ftilt", 40.0),
    ("fsmash", 100.0),
    ("dtilt", 20.0),
    ("nair", 30.0),
    ("jab1", 60.0),
    ("fsmash", 150.0),
    ("ftilt", 80.0),
    ("dtilt", 50.0),
    ("fsmash", 120.0),
)
"""Each round's move and the percent everyone is set to."""
STORM_GAP = 0.9
STORM_SECOND_PAIR = Vec2(-1.2, -1.2)
"""Where the second pair stands, from the stage's respawn point (the first stands on it)."""


@dataclass(frozen=True, slots=True)
class DrawStats:
    """What :func:`bench_hits` measures over one run."""

    hits: int
    tick_ms: float
    """Median sim tick."""
    draw_ms: float
    """Median draw (with the GPU finished)."""
    draw_p95_ms: float
    sprites_mean: float
    """The effect layer's live sprites."""
    sprites_max: int


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


def _stand(match: Match, fighter: Fighter, spot: Vec2, facing: Dir8, damage: float) -> None:
    """Put a fighter back on its feet at ``spot`` with ``damage`` (the hit storm's reset)."""
    top = match.stage.surface_top(spot.x, spot.y)
    assert top is not None, "the hit storm needs solid ground at its spots"
    fighter.pos = Vec3(spot.x, spot.y, top)
    fighter.vel = ZERO3
    fighter.kb_vel = ZERO3
    fighter.facing = facing
    fighter.ground = GroundKind.CELL
    fighter.hitstun = 0
    fighter.launch = None
    match.set_damage(fighter.player_index, damage)
    if fighter.state is not StateId.IDLE:
        change_state(match, fighter, StateId.IDLE)


def _storm_round(match: Match, tick: int) -> None:
    """Every ``STORM_CYCLE`` ticks, stand the four fighters in two facing pairs and have the
    first of each pair swing (fighters still frozen in a hit are left alone)."""
    if tick % STORM_CYCLE:
        return
    move_id, percent = STORM_MOVES[(tick // STORM_CYCLE) % len(STORM_MOVES)]
    respawn = match.stage.respawn
    first = (respawn, respawn + Dir8.E.world * STORM_GAP)
    spots = (*first, *(spot + STORM_SECOND_PAIR for spot in first))
    for index, fighter in enumerate(match.fighters):
        if fighter.hitlag:
            continue
        attacker = index % 2 == 0
        _stand(match, fighter, spots[index], Dir8.E if attacker else Dir8.W, percent)
        if attacker and move_id in fighter.character.moves:
            start_move(match, fighter, move_id)


def bench_hits(stage_id: str, storm: bool, frames: int = STORM_FRAMES) -> DrawStats:
    """Draw cost and live effect sprites of a hit storm (``storm``) or a four-CPU match."""
    from isofightr.app import GameWindow
    from isofightr.scenes.battle import BattleView
    from isofightr.sim.events import HitEvent

    window = GameWindow(visible=False)
    window.switch_to()
    names = STORM_ROSTER if storm else ROSTER
    characters = [load_character(name) for name in names]
    view = BattleView(
        window.pixel_buffer,
        load_stage(stage_id),
        characters,
        seed=5,
        cpus=None if storm else [9] * 4,
        rules=MatchRules(stocks=None),
    )
    window.show_view(view)
    ticks, draws, sprites = [], [], []
    hits = 0
    for frame in range(STORM_WARMUP + frames):
        if storm:
            _storm_round(view.match, frame)
        a = time.perf_counter()
        view.tick()
        b = time.perf_counter()
        view.on_draw()
        window.ctx.finish()
        c = time.perf_counter()
        hits += sum(isinstance(event, HitEvent) for event in view.match.events)
        if frame >= STORM_WARMUP:
            ticks.append(b - a)
            draws.append(c - b)
            sprites.append(view.effect_renderer.live)
    window.close()
    draws.sort()
    return DrawStats(
        hits,
        statistics.median(ticks) * 1000.0,
        statistics.median(draws) * 1000.0,
        draws[int(len(draws) * 0.95)] * 1000.0,
        statistics.mean(sprites),
        max(sprites),
    )


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
    parser.add_argument("--hits", metavar="STAGE", help="hit effects: a hit storm on STAGE")
    parser.add_argument("--runs", type=int, default=3, help="--hits: runs of each, in turn")
    args = parser.parse_args()
    if args.hits:
        for run in range(args.runs):
            for storm in (True, False):
                stats = bench_hits(args.hits, storm)
                kind = "hit storm" if storm else "four CPUs"
                print(
                    f"{kind} {args.hits} run {run + 1}: {stats.hits} hits, tick"
                    f" {stats.tick_ms:.2f} ms, draw median {stats.draw_ms:.2f} ms p95"
                    f" {stats.draw_p95_ms:.2f} ms, effect sprites mean"
                    f" {stats.sprites_mean:.1f} max {stats.sprites_max}"
                )
        return
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
