"""Unit tests for the fixed-timestep accumulator (plan note 02, "Game loop")."""

import pytest

from isofightr.config import MAX_FRAME_SECONDS, TICK_RATE, TICK_SECONDS
from isofightr.timestep import FixedTimestep


def test_one_tick_per_exact_tick_of_frame_time() -> None:
    timestep = FixedTimestep()
    assert [timestep.advance(TICK_SECONDS) for _ in range(5)] == [1, 1, 1, 1, 1]


def test_one_second_of_frames_yields_sixty_ticks() -> None:
    timestep = FixedTimestep()
    assert sum(timestep.advance(TICK_SECONDS) for _ in range(TICK_RATE)) == TICK_RATE


def test_short_frames_bank_time_until_a_tick_is_due() -> None:
    timestep = FixedTimestep()
    half_tick = TICK_SECONDS / 2
    assert [timestep.advance(half_tick) for _ in range(4)] == [0, 1, 0, 1]


def test_high_refresh_display_still_runs_sixty_ticks_per_second() -> None:
    timestep = FixedTimestep()
    frames_per_second = 144
    total = sum(timestep.advance(1 / frames_per_second) for _ in range(frames_per_second * 10))
    assert total == pytest.approx(TICK_RATE * 10, abs=1)


def test_slow_frame_runs_several_ticks_to_catch_up() -> None:
    timestep = FixedTimestep()
    assert timestep.advance(TICK_SECONDS * 3.5) == 3
    assert timestep.accumulator == pytest.approx(TICK_SECONDS * 0.5)


def test_long_stall_is_clamped() -> None:
    timestep = FixedTimestep()
    assert timestep.advance(10.0) == round(MAX_FRAME_SECONDS * TICK_RATE)
    assert timestep.accumulator < TICK_SECONDS


def test_negative_delta_is_ignored() -> None:
    timestep = FixedTimestep()
    assert timestep.advance(-1.0) == 0
    assert timestep.accumulator == 0.0


def test_reset_drops_banked_time() -> None:
    timestep = FixedTimestep()
    timestep.advance(TICK_SECONDS * 0.9)
    timestep.reset()
    assert timestep.advance(TICK_SECONDS * 0.9) == 0
