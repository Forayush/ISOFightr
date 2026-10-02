"""Stale-move queue.

Plan note "05 - Combat Core" ("Stale-move negation"): each fighter remembers the last nine
moves that connected, and a move does less damage for every slot of the queue it occupies.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from collections.abc import Sequence

from isofightr.sim.combat.constants import FRESH_BONUS, STALE_PENALTIES, STALE_QUEUE_LENGTH


def stale_multiplier(queue: Sequence[str], move_id: str) -> float:
    """Return the damage multiplier for ``move_id`` given the queue (newest first).

    A move that is not in the queue at all gets the fresh bonus.
    """
    penalty = sum(STALE_PENALTIES[slot] for slot, queued in enumerate(queue) if queued == move_id)
    return FRESH_BONUS if penalty == 0.0 else 1.0 - penalty


def push_stale(queue: list[str], move_id: str) -> None:
    """Record that ``move_id`` connected: it becomes the newest entry, the oldest drops off."""
    queue.insert(0, move_id)
    del queue[STALE_QUEUE_LENGTH:]
