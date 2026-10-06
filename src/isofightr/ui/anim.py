"""Tweens for the UI: easing curves and the small animations screens are built from.

Plan note "13 - Game Modes UI and Flow" (decision D-061): banners slide in with a bounce,
numbers count up, bars grow, the focus pulses. Everything is a pure function of a tick
count, so a screen's look at tick N can be tested, and nothing here keeps state.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

import math
from collections.abc import Callable
from typing import Final

Ease = Callable[[float], float]

BACK_OVERSHOOT: Final[float] = 1.70158
"""How far :func:`ease_out_back` shoots past its target (the usual constant: about 10%)."""
BOUNCE_STRENGTH: Final[float] = 7.5625
BOUNCE_SPAN: Final[float] = 2.75


def clamp01(value: float) -> float:
    """Clamp a value to 0..1."""
    return min(max(value, 0.0), 1.0)


def lerp(start: float, end: float, amount: float) -> float:
    """Blend from ``start`` to ``end``."""
    return start + (end - start) * amount


def linear(amount: float) -> float:
    """No easing."""
    return clamp01(amount)


def ease_out(amount: float) -> float:
    """Fast, then settling (cubic)."""
    return 1.0 - (1.0 - clamp01(amount)) ** 3


def ease_in(amount: float) -> float:
    """Slow, then fast (cubic)."""
    return clamp01(amount) ** 3


def ease_in_out(amount: float) -> float:
    """Slow at both ends (cubic)."""
    amount = clamp01(amount)
    if amount < 0.5:
        return 4.0 * amount**3
    return 1.0 - (-2.0 * amount + 2.0) ** 3 / 2.0


def ease_out_back(amount: float) -> float:
    """Overshoot the target a little, then come back to it."""
    shifted = clamp01(amount) - 1.0
    return 1.0 + (BACK_OVERSHOOT + 1.0) * shifted**3 + BACK_OVERSHOOT * shifted**2


def bounce(amount: float) -> float:
    """Arrive, then bounce three times, each smaller."""
    amount = clamp01(amount)
    if amount < 1.0 / BOUNCE_SPAN:
        return BOUNCE_STRENGTH * amount * amount
    if amount < 2.0 / BOUNCE_SPAN:
        amount -= 1.5 / BOUNCE_SPAN
        return BOUNCE_STRENGTH * amount * amount + 0.75
    if amount < 2.5 / BOUNCE_SPAN:
        amount -= 2.25 / BOUNCE_SPAN
        return BOUNCE_STRENGTH * amount * amount + 0.9375
    amount -= 2.625 / BOUNCE_SPAN
    return BOUNCE_STRENGTH * amount * amount + 0.984375


def progress(tick: int, start: int, duration: int) -> float:
    """Return how far through an animation ``tick`` is: 0 before ``start``, 1 once
    ``duration`` ticks have passed."""
    if duration <= 0:
        return 1.0 if tick >= start else 0.0
    return clamp01((tick - start) / duration)


def tween(
    tick: int, start: int, duration: int, begin: float, end: float, ease: Ease = ease_out
) -> float:
    """Return a value animated from ``begin`` to ``end``."""
    return lerp(begin, end, ease(progress(tick, start, duration)))


def slide(tick: int, start: int, duration: int, begin: int, end: int, ease: Ease = ease_out) -> int:
    """Return a whole-pixel position animated from ``begin`` to ``end``."""
    return round(tween(tick, start, duration, begin, end, ease))


def count_up(tick: int, start: int, duration: int, target: float) -> int:
    """Return a number counting from 0 up to ``target`` (rounded down until it arrives)."""
    amount = progress(tick, start, duration)
    if amount >= 1.0:
        return round(target)
    return int(target * ease_out(amount))


def pulse(tick: int, period: int) -> float:
    """Return a smooth 0..1..0 wave with the given period in ticks (0 at tick 0)."""
    return 0.5 - 0.5 * math.cos(2.0 * math.pi * tick / max(period, 1))


def blink(tick: int, period: int) -> bool:
    """Return whether a blinking thing is shown: on for the first half of each period."""
    return (tick % max(period, 1)) * 2 < max(period, 1)


def wave(tick: int, index: int, amplitude: int, period: int, spread: int = 4) -> int:
    """Return the vertical offset in pixels of the ``index``-th letter of a waving banner."""
    phase = 2.0 * math.pi * (tick - index * spread) / max(period, 1)
    return round(amplitude * math.sin(phase))


def shake(tick: int, amplitude: int) -> int:
    """Return a jitter offset in pixels that changes every tick: -amplitude..amplitude.

    Deterministic (a fixed pattern), so a screenshot at tick N is always the same."""
    if amplitude <= 0:
        return 0
    pattern = (1, -1, 0, 1, 0, -1, 1, -1, 0)
    return round(amplitude * pattern[tick % len(pattern)])


def pop(tick: int, start: int, duration: int, peak: float = 1.5) -> float:
    """Return a scale that jumps to ``peak`` at ``start`` and eases back to 1."""
    if tick < start:
        return 1.0
    return lerp(peak, 1.0, ease_out(progress(tick, start, duration)))
