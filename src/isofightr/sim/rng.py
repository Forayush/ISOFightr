"""Seeded deterministic PRNG owned by the ``Match``.

Plan note "02 - Technical Architecture" (determinism rules). Arrives in M2.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""
