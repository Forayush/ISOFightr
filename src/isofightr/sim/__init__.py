"""The deterministic simulation: pure Python driven only by ``InputFrame``s.

Plan note "02 - Technical Architecture". Hard rule: nothing in this package imports
``arcade`` or ``pyglet``, reads a clock, or uses ``random`` (use ``match.rng``). That is
what makes the game testable headless, replayable and rollback-ready.
"""
