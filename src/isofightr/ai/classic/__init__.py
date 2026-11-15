"""The M10 CPU, frozen as a benchmark (decision D-071).

A complete copy of the CPU as it played before M20: its controller, levels, move knowledge,
terrain questions, view and tunables. Tools and tests use it as the opponent the game's CPU
(:mod:`isofightr.ai.controller`) is measured against, and the scripted bots of
:mod:`isofightr.ai.bots` borrow it to get back onto the stage. The game never plays it.
``tests/test_cpu_report.py`` pins how it plays, so it cannot drift.

Pure Python (no ``arcade``).
"""

from isofightr.ai.classic.controller import CpuController as ClassicCpu

__all__ = ["ClassicCpu"]
