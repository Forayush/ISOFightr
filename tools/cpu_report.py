"""Measure how the CPUs play: fixed seeded matches, behaviour metrics and M20's targets.

Usage::

    uv run python tools/cpu_report.py                  # the full report (about 650 matches)
    uv run python tools/cpu_report.py --quick          # a thin fixed sample, under a minute
    uv run python tools/cpu_report.py --suite matrix --suite bots
    uv run python tools/cpu_report.py --subject classic        # the frozen M10 CPU: the baseline
    uv run python tools/cpu_report.py --write report.txt       # also save the text
    uv run python tools/cpu_report.py --save runs.pkl          # keep the matches' counts...
    uv run python tools/cpu_report.py --load runs.pkl          # ...and print them again later
    uv run python tools/cpu_report.py --trace --players rook=cpu:9,zephyr=bot:dtilt

Suites: ``ladder`` (each level against the next), ``matrix`` (every character pair at level
9), ``versus`` (the game's CPU against the frozen M10 one), ``bots`` (the scripted cheap
strategies), ``low`` (levels 1 and 5 against the one-button bots), ``ffa``, ``mix`` and
``teams`` (four players). It then prints each metric against its target and exits with
status 1 if one is missed. ``--trace`` instead plays one match and prints a player's decision
timeline. A player is ``cpu:<level>`` (the CPU being measured), ``classic:<level>`` or
``bot:<name>``. See :mod:`isofightr.ai.report` (decision D-071).
"""

import argparse
import json
import os
import pickle
import sys
import time
from functools import partial
from multiprocessing import Pool
from pathlib import Path

from isofightr.ai.bots import BOTS
from isofightr.ai.report import (
    CHARACTERS,
    GAME,
    SUITES,
    TOP_LEVEL,
    MatchReport,
    MatchSpec,
    check,
    make_brain,
    play,
    report_lines,
    suites,
    summarise,
    trace,
)
from isofightr.ai.view import observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.match import Match, MatchRules

COST_STAGE = "sky_ruins"
COST_TICKS = 3000
COST_SEED = 4


def think_cost(subject: str, level: int = TOP_LEVEL) -> tuple[float, float]:
    """Milliseconds one CPU's think takes per tick with four in a match: the mean, and the
    worst single think after the first tick (which records the move knowledge)."""
    stage = load_stage(COST_STAGE)
    characters = [load_character(character) for character in CHARACTERS]
    match = Match.create(stage, characters, seed=COST_SEED, rules=MatchRules(stocks=None))
    cpus = [
        make_brain(f"cpu:{level}", index, COST_SEED, stage, subject)
        for index in range(len(characters))
    ]
    total = worst = 0.0
    for tick in range(COST_TICKS):
        world = observe(match)
        frames = []
        for cpu in cpus:
            begin = time.perf_counter()
            frames.append(cpu.think(match, world))
            spent = time.perf_counter() - begin
            if tick > 0:
                total += spent
                worst = max(worst, spent)
        match.tick(frames)
    return total / ((COST_TICKS - 1) * len(cpus)) * 1000.0, worst * 1000.0


PROGRESS_EVERY = 50


def run(specs: list[MatchSpec], subject: str, jobs: int) -> list[MatchReport]:
    """Play the matches, in parallel when ``jobs`` allows; results come back in order.
    Progress goes to stderr, so the report on stdout stays clean."""
    worker = partial(play, subject=subject)
    if jobs <= 1 or len(specs) <= 1:
        return [worker(spec) for spec in specs]
    begin = time.perf_counter()
    reports: list[MatchReport] = []
    with Pool(jobs) as pool:
        for report in pool.imap(worker, specs, chunksize=1):
            reports.append(report)
            if len(reports) % PROGRESS_EVERY == 0:
                spent = time.perf_counter() - begin
                print(f"  {len(reports)}/{len(specs)} matches, {spent:.0f} s", file=sys.stderr)
    return reports


def trace_spec(args: argparse.Namespace) -> MatchSpec:
    """The single match ``--trace`` plays, from ``--stage``, ``--players`` and ``--seed``."""
    characters, players = [], []
    for part in args.players.split(","):
        character, _, player = part.partition("=")
        characters.append(character.strip())
        players.append(player.strip() or f"cpu:{TOP_LEVEL}")
    return MatchSpec(
        "trace", "trace", args.stage, tuple(characters), tuple(players), args.seed, hazards=True
    )


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, play, print; return the exit status."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="a thin fixed sample of each suite")
    parser.add_argument("--suite", action="append", choices=SUITES, help="repeat for several")
    parser.add_argument(
        "--subject",
        choices=(GAME, "classic"),
        default=GAME,
        help="which CPU 'cpu:<level>' is: the game's (default) or the frozen M10 one",
    )
    parser.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int, default=0, help="play only the first N matches")
    parser.add_argument("--no-cost", action="store_true", help="skip the think-time measurement")
    parser.add_argument("--write", type=Path, help="also write the report to this file")
    parser.add_argument("--json", type=Path, help="also write the metrics to this file")
    parser.add_argument("--save", type=Path, help="keep every match's counts in this file")
    parser.add_argument("--load", type=Path, help="print a saved run instead of playing")
    parser.add_argument("--trace", action="store_true", help="print one player's decisions")
    parser.add_argument("--stage", default="sky_ruins", help="--trace: the stage")
    parser.add_argument(
        "--players",
        default=f"rook=cpu:{TOP_LEVEL},zephyr=cpu:{TOP_LEVEL}",
        help="--trace: character=player, comma separated (bots: "
        + ", ".join(bot.name for bot in BOTS)
        + ")",
    )
    parser.add_argument("--seed", type=int, default=1, help="--trace: the match seed")
    parser.add_argument("--ticks", type=int, default=1800, help="--trace: how long to watch")
    parser.add_argument("--watch", type=int, default=1, help="--trace: which player (1 to 4)")
    args = parser.parse_args(argv)

    if args.trace:
        print("\n".join(trace(trace_spec(args), args.watch - 1, args.ticks, args.subject)))
        return 0

    begin = time.perf_counter()
    if args.load:
        # A file this tool wrote with --save: only load one you made yourself.
        reports = pickle.loads(args.load.read_bytes())
        wanted = set(args.suite or SUITES)
        reports = [report for report in reports if report.spec.suite in wanted]
    else:
        specs = suites(args.quick, tuple(args.suite or ()))
        if args.limit:
            specs = specs[: args.limit]
        reports = run(specs, args.subject, args.jobs)
    if args.save:
        args.save.write_bytes(pickle.dumps(reports))
    metrics = summarise(reports)
    if not args.no_cost:
        metrics["think_ms"], metrics["think_worst_ms"] = think_cost(args.subject)
    name = "the game's CPU" if args.subject == GAME else "the frozen M10 CPU"
    lines = [f"CPU report: {name}" + (" (quick sample)" if args.quick else "")]
    lines += report_lines(reports, metrics)
    if not args.no_cost:
        lines += [
            "",
            f"COST: {metrics['think_ms']:.3f} ms per CPU per tick (four level {TOP_LEVEL} "
            f"CPUs on {COST_STAGE}), worst single think {metrics['think_worst_ms']:.2f} ms",
        ]
    if not args.load:
        lines += ["", f"played in {time.perf_counter() - begin:.0f} s"]
    text = "\n".join(lines)
    print(text)
    if args.write:
        args.write.write_text(text + "\n", encoding="utf-8", newline="\n")
    if args.json:
        args.json.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8", newline="\n")
    missed = [target for target, _, met in check(metrics) if not met]
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
