"""Seeded deterministic PRNG owned by the ``Match``.

Plan note "02 - Technical Architecture" (determinism rules): the sim never touches Python's
``random``, clocks or OS entropy. Everything random in a match comes from this generator, whose
whole state is two integers, so it copies, hashes and replays exactly.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from dataclasses import dataclass
from typing import Final

_MASK_64: Final[int] = (1 << 64) - 1
_MASK_32: Final[int] = (1 << 32) - 1
_MULTIPLIER: Final[int] = 6364136223846793005
_DEFAULT_STREAM: Final[int] = 1442695040888963407
_FLOAT_STEPS: Final[int] = 1 << 32


@dataclass(slots=True)
class Rng:
    """PCG32 (O'Neill's ``pcg32_random_r``): small, fast, and good enough for gameplay."""

    state: int = 0
    increment: int = _DEFAULT_STREAM | 1

    @classmethod
    def seeded(cls, seed: int) -> "Rng":
        """Return a generator whose sequence is fully determined by ``seed``."""
        rng = cls(state=0, increment=_DEFAULT_STREAM | 1)
        rng.next_u32()
        rng.state = (rng.state + (seed & _MASK_64)) & _MASK_64
        rng.next_u32()
        return rng

    def next_u32(self) -> int:
        """Return the next 32-bit unsigned integer."""
        old = self.state
        self.state = (old * _MULTIPLIER + self.increment) & _MASK_64
        xorshifted = (((old >> 18) ^ old) >> 27) & _MASK_32
        rotation = old >> 59
        return ((xorshifted >> rotation) | (xorshifted << ((-rotation) & 31))) & _MASK_32

    def random(self) -> float:
        """Return a float in ``[0, 1)``."""
        return self.next_u32() / _FLOAT_STEPS

    def below(self, bound: int) -> int:
        """Return an integer in ``[0, bound)`` without modulo bias."""
        if bound <= 0:
            raise ValueError(f"bound must be positive, got {bound}")
        threshold = (_FLOAT_STEPS - bound) % bound
        while True:
            value = self.next_u32()
            if value >= threshold:
                return value % bound

    def between(self, low: int, high: int) -> int:
        """Return an integer in ``[low, high]`` inclusive."""
        return low + self.below(high - low + 1)
