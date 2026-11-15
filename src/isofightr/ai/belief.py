"""What a CPU believes about its opponents: tracking is fast, reacting is slow (D-071).

Plan note "15 - CPU AI" ("Perception: tracking is fast, reacting is slow"). The M10 CPU sees
everything about an opponent the same number of frames late. People do not: following
something that moves smoothly is almost immediate, while noticing that something **new**
started takes a reaction time. So a belief about an opponent is put together from two
moments of the CPU's snapshot history:

- **Smooth values** (position, velocity, damage, shield size, whether it is on the ground)
  come from ``tracking_frames`` ago.
- **What it is doing** (its state, its move and how far into it, hitstun, landing lag, who it
  holds) comes from the last change the CPU has had time to notice: a change becomes visible
  ``reaction_frames`` after it happens, plus a few frames drawn per event, never fewer.
  Until then the belief keeps the old state and lets its frame count run on.

A CPU knows its own fighter as it is now. An opponent it is not focused on takes
``CPU_ATTENTION_FRAMES`` longer to read, unless it is close.

Group 1 builds and tests this; the decisions start reading it in group 2.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from isofightr import config
from isofightr.ai.view import FighterView, WorldView
from isofightr.sim.fighter import StateId
from isofightr.sim.rng import Rng

CLOSE_ATTENTION: Final[float] = 3.0
"""An opponent this close is read as fast as the one the CPU is focused on."""


@dataclass(slots=True)
class _Seen:
    """One opponent: the change the CPU believes in and the ones it has yet to notice."""

    believed: FighterView
    believed_frame: int
    """The frame ``believed`` was true on."""
    key: tuple[StateId, str]
    """The newest state and move the history has shown (noticed or not)."""
    pending: list[tuple[int, int, FighterView]]
    """Changes not yet noticed: (frame it becomes visible, frame it happened, the view)."""


class Beliefs:
    """One CPU's picture of everyone else. Call :meth:`update` once per tick."""

    def __init__(
        self,
        player_index: int,
        tracking_frames: int,
        reaction_frames: int,
        rng: Rng,
        spread: int = config.CPU_REACTION_SPREAD,
    ) -> None:
        self.player = player_index
        self.tracking_frames = tracking_frames
        self.reaction_frames = reaction_frames
        self.spread = spread
        self.rng = rng
        self._seen: dict[int, _Seen] = {}
        self._views: dict[int, FighterView] = {}
        self.frame = 0

    def update(self, history: Sequence[WorldView], focus: int | None = None) -> None:
        """Take in this tick's snapshot (the last of ``history``, oldest first). ``focus`` is
        the opponent the CPU is fighting; the others are read a little later."""
        now = history[-1]
        self.frame = now.frame
        tracked = history[max(len(history) - 1 - self.tracking_frames, 0)]
        me = now.fighters[self.player]
        for fighter in now.fighters:
            index = fighter.index
            if index == self.player:
                self._views[index] = fighter
                continue
            seen = self._seen.get(index)
            key = (fighter.state, fighter.move_id)
            if seen is None:
                seen = self._seen[index] = _Seen(fighter, now.frame, key, [])
            elif key != seen.key:
                seen.key = key
                seen.pending.append(
                    (now.frame + self._reaction(me, fighter, focus), now.frame, fighter)
                )
            while seen.pending and seen.pending[0][0] <= now.frame:
                _, happened, view = seen.pending.pop(0)
                seen.believed, seen.believed_frame = view, happened
            lag = now.frame - tracked.frame
            self._views[index] = self._compose(tracked.fighters[index], seen, now.frame, lag)

    def _reaction(self, me: FighterView, other: FighterView, focus: int | None) -> int:
        frames = self.reaction_frames
        if self.spread > 0:
            frames += int(self.rng.random() * (self.spread + 1))
        distracted = focus is not None and other.index != focus
        if distracted and (other.pos - me.pos).length() > CLOSE_ATTENTION:
            frames += config.CPU_ATTENTION_FRAMES
        return frames

    @staticmethod
    def _compose(tracked: FighterView, seen: _Seen, frame: int, lag: int) -> FighterView:
        """Smooth values as tracked, the doing as last noticed and run on to now.

        Once the tracked snapshot shows the same state and move as the one noticed, its own
        frame count is the better one: a charging smash holds its frame still in the sim
        (counting on would make the CPU think the hit had passed)."""
        doing = seen.believed
        elapsed = frame - seen.believed_frame
        state_frame = doing.state_frame + elapsed
        if (tracked.state, tracked.move_id) == (doing.state, doing.move_id):
            if tracked.charge_frames > 0:
                state_frame = tracked.state_frame
            else:
                state_frame = tracked.state_frame + lag
        return replace(
            tracked,
            state=doing.state,
            state_frame=state_frame,
            move_id=doing.move_id,
            move_faf=doing.move_faf,
            hitlag=max(doing.hitlag - elapsed, 0),
            hitstun=max(doing.hitstun - max(elapsed - doing.hitlag, 0), 0),
            land_lag=doing.land_lag,
            launch=doing.launch if doing.hitlag > elapsed else None,
            grab_partner=doing.grab_partner,
            stun_frames=max(doing.stun_frames - elapsed, 0),
            air_dodge_used=doing.air_dodge_used,
            armored=doing.armored,
            countering=doing.countering,
            reflecting=doing.reflecting,
            intangible_left=max(doing.intangible_left - elapsed, 0),
        )

    def of(self, index: int) -> FighterView:
        """What the CPU believes about a fighter right now."""
        return self._views[index]

    def noticed(self, index: int) -> bool:
        """Whether the CPU has caught up with what that opponent is doing (nothing it did is
        still waiting to be noticed)."""
        seen = self._seen.get(index)
        return seen is None or not seen.pending

    def views(self) -> tuple[FighterView, ...]:
        """Every fighter as believed, in player order."""
        return tuple(self._views[index] for index in sorted(self._views))
