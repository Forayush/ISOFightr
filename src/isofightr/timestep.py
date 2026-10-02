"""Fixed-timestep accumulator that turns variable frame times into whole 60 Hz ticks.

Implements "Game loop: fixed 60 Hz simulation" in the plan note "02 - Technical
Architecture". It lives outside ``sim/`` because it consumes wall-clock ``dt``; the sim itself
only ever sees whole ticks. It is pure Python so the loop can be tested without a window.
"""

from dataclasses import dataclass

from isofightr.config import MAX_FRAME_SECONDS, TICK_SECONDS


@dataclass(slots=True)
class FixedTimestep:
    """Accumulates frame time and reports how many simulation ticks are due.

    The caller runs one full poll/tick/consume step per reported tick::

        for _ in range(self.timestep.advance(delta_time)):
            self.match.tick(self.input_mapper.poll())
    """

    tick_seconds: float = TICK_SECONDS
    max_frame_seconds: float = MAX_FRAME_SECONDS
    accumulator: float = 0.0

    def advance(self, delta_seconds: float) -> int:
        """Add one frame's elapsed time and return the number of whole ticks now due.

        ``delta_seconds`` is clamped to ``[0, max_frame_seconds]`` so a long stall (window drag,
        debugger pause) cannot queue up an unbounded burst of ticks.
        """
        self.accumulator += min(max(delta_seconds, 0.0), self.max_frame_seconds)
        ticks_due = 0
        while self.accumulator >= self.tick_seconds:
            self.accumulator -= self.tick_seconds
            ticks_due += 1
        return ticks_due

    def reset(self) -> None:
        """Drop any banked time, e.g. when leaving pause so the sim does not jump ahead."""
        self.accumulator = 0.0
