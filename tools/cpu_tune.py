"""Tune the CPU's weights: seeded matches and a coordinate search over ``config.CPU_*``.

Usage::

    uv run python tools/cpu_tune.py --vary CPU_FREE_ACT_VALUE=3,5,8 --suite versus --suite matrix
    uv run python tools/cpu_tune.py --vary CPU_REPEAT_PENALTY=4,8,12 --vary CPU_STARTER_VALUE=2,3,4
    uv run python tools/cpu_tune.py --vary CPU_FREE_ACT_VALUE=3,5 --stride 2   # every 2nd match

Each ``--vary NAME=a,b,c`` is one coordinate. The search starts from the values in
``config.py``; for each coordinate in turn it plays the chosen suites (the same fixed seeds
as ``tools/cpu_report.py``) with each value, keeps the best, and moves on. A run is scored by
the M20 targets it meets (``ai.report.TARGETS``), then by how far it is from the ones it
misses (each miss measured as a share of its target). The chosen values are printed; copy
them into ``config.py`` with the report that justified them (decision D-071). Overrides are
applied in each worker process, so nothing in the game changes while it runs.
"""

import argparse
import os
import sys
import time
from functools import partial
from multiprocessing import Pool

from isofightr import config
from isofightr.ai.report import SUITES, MatchReport, MatchSpec, check, play, suites, summarise


def _play(spec: MatchSpec, overrides: dict[str, float]) -> MatchReport:
    for name, value in overrides.items():
        setattr(config, name, value)
    return play(spec)


def score(metrics: dict[str, float]) -> tuple[int, float]:
    """(targets met, minus the summed shortfall of the ones missed): bigger is better."""
    met = 0
    shortfall = 0.0
    for target, value, ok in check(metrics):
        if ok:
            met += 1
            continue
        scale = abs(target.value) or 1.0
        shortfall += abs(value - target.value) / scale
    return met, -shortfall


def evaluate(
    specs: list[MatchSpec], overrides: dict[str, float], jobs: int
) -> tuple[tuple[int, float], dict[str, float]]:
    """Play ``specs`` with ``overrides`` and score the result."""
    with Pool(jobs) as pool:
        reports = pool.map(partial(_play, overrides=overrides), specs, chunksize=1)
    metrics = summarise(reports)
    return score(metrics), metrics


def parse_vary(items: list[str]) -> list[tuple[str, list[float]]]:
    """``NAME=a,b,c`` items as (name, values); every name must be a ``config.CPU_*``."""
    out = []
    for item in items:
        name, _, values = item.partition("=")
        if not name.startswith("CPU_") or not hasattr(config, name):
            raise SystemExit(f"--vary {item!r}: no such setting config.{name}")
        out.append((name, [float(v) for v in values.split(",") if v]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vary", action="append", required=True, help="NAME=a,b,c")
    parser.add_argument("--suite", action="append", choices=SUITES)
    parser.add_argument("--stride", type=int, default=1, help="play every Nth match only")
    parser.add_argument("--jobs", type=int, default=min(6, os.cpu_count() or 1))
    args = parser.parse_args()
    coordinates = parse_vary(args.vary)
    chosen = args.suite or ["versus", "matrix"]
    specs = [s for i, s in enumerate(suites(only=chosen)) if i % max(args.stride, 1) == 0]
    best: dict[str, float] = {name: float(getattr(config, name)) for name, _ in coordinates}
    print(f"{len(specs)} matches a run ({', '.join(chosen)}); starting from {best}", flush=True)
    begin = time.perf_counter()
    best_score, _ = evaluate(specs, dict(best), args.jobs)
    print(f"  start: {best_score[0]} targets met, shortfall {-best_score[1]:.2f}", flush=True)
    for name, values in coordinates:
        for value in values:
            if value == best[name]:
                continue
            trial = dict(best, **{name: value})
            result, _ = evaluate(specs, trial, args.jobs)
            mark = ""
            if result > best_score:
                best, best_score, mark = trial, result, "  <- better"
            print(
                f"  {name}={value:g}: {result[0]} met, shortfall {-result[1]:.2f}{mark}",
                flush=True,
            )
    print(f"chosen: {best} ({best_score[0]} targets met) in {time.perf_counter() - begin:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
