"""``Match``: ``tick()``, rules, stocks, timer and the per-tick event list.

Plan note "02 - Technical Architecture" (order of operations inside ``Match.tick()``).
Arrives in M2.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""
