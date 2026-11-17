"""Habits: what each opponent tends to do, learned during the match (decision D-071).

Plan note "15 - CPU AI" ("Habits: adapting to the player"). A :class:`Habits` watches the
fighters as the CPU believes them to be (so it learns late, like a person) and keeps, per
opponent, decaying counts of:

- what it does from a recurring spot: hanging from a ledge (``LEDGE``: getup, roll, jump,
  attack, drop), lying down (``GETUP``: stand, roll in, roll out, attack) and landing in a
  tumble (``TECH``: tech, tech in, tech out, miss);
- how often it is shielding when the CPU's own move comes out near it (:meth:`guard`);
- which of its moves it uses (:meth:`share`, :meth:`zoning` for projectiles).

Every new observation first scales the old ones by ``CPU_HABIT_DECAY``, so recent choices
count most and a player who changes habit is followed within a few repeats. How much the CPU
trusts what it learned is ``adapt`` (from its level: none below level 5) times a confidence
that grows with the number of observations. The CPU also counts its **own** moves
(:class:`OwnMoves`) and lowers the value of what it just did, so its play is no pattern.

Nothing here reads the clock or the match's dice; it resets with each match (a new CPU).
Pure Python (no ``arcade``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from isofightr import config
from isofightr.ai.view import FighterView
from isofightr.sim.fighter import StateId
from isofightr.sim.math3d import Vec2, Vec3

LEDGE: Final[str] = "ledge"
GETUP: Final[str] = "getup"
TECH: Final[str] = "tech"

SHIELDING: Final[frozenset[StateId]] = frozenset(
    {StateId.SHIELD, StateId.SHIELD_STUN, StateId.SHIELD_DROP}
)
ROLL_SETTLE: Final[int] = 8
"""Frames into a roll after which its direction (in or out) is read."""


def _decayed(counts: dict[str, float], name: str) -> None:
    for key in counts:
        counts[key] *= config.CPU_HABIT_DECAY
    counts[name] = counts.get(name, 0.0) + 1.0


@dataclass(slots=True)
class _Roll:
    """A roll seen starting, waiting to be told in from out."""

    situation: str
    start: Vec3
    frame: int


class Habits:
    """One CPU's record of its opponents' habits (see the module docstring)."""

    def __init__(self, me: int, adapt: float, respawn: Vec2) -> None:
        self.me = me
        self.adapt = adapt
        """0 to 1: how much the CPU acts on what it learns (by level)."""
        self.respawn = respawn
        self._options: dict[tuple[int, str], dict[str, float]] = {}
        self._moves: dict[int, dict[str, float]] = {}
        self._guard: dict[int, list[float]] = {}
        """Per opponent: [decayed times shielding, decayed times approached]."""
        self._previous: dict[int, FighterView] = {}
        self._rolls: dict[int, _Roll] = {}
        self._watch: dict[int, tuple[int, bool]] = {}
        """Per opponent: (the frame the CPU's move started near it, whether it shielded)."""

    # --- recording -----------------------------------------------------------------------

    def observe(self, views: Sequence[FighterView], frame: int) -> None:
        """Look at this tick's (believed) fighters and record what changed."""
        me = views[self.me]
        before_me = self._previous.get(self.me)
        started = me.state is StateId.ATTACK and (
            before_me is None
            or before_me.state is not StateId.ATTACK
            or before_me.move_id != me.move_id
        )
        for view in views:
            index = view.index
            before = self._previous.get(index)
            self._previous[index] = view
            if index == self.me or not view.in_play:
                continue
            if before is not None and before.state is not view.state:
                self._changed(index, before, view, frame)
            self._settle_roll(index, view, frame)
            self._watch_guard(index, me, view, frame, started)
            if view.state is StateId.ATTACK and (
                before is None
                or before.state is not StateId.ATTACK
                or before.move_id != view.move_id
            ):
                _decayed(self._moves.setdefault(index, {}), view.move_id)
        self._previous[self.me] = me

    def _changed(self, index: int, before: FighterView, view: FighterView, frame: int) -> None:
        state = view.state
        if before.state is StateId.LEDGE_HANG:
            name = {
                StateId.LEDGE_GETUP: "getup",
                StateId.LEDGE_ROLL: "roll",
                StateId.LEDGE_ATTACK: "attack",
                StateId.JUMP: "jump",
                StateId.DOUBLE_JUMP: "jump",
                StateId.FALL: "drop",
            }.get(state)
            if name is not None:
                self.record(index, LEDGE, name)
        elif before.state is StateId.KNOCKDOWN:
            if state is StateId.GETUP_ROLL:
                self._rolls[index] = _Roll(GETUP, view.pos, frame)
            elif state is StateId.ATTACK:
                self.record(index, GETUP, "attack")
            elif state is StateId.GETUP:
                self.record(index, GETUP, "stand")
        elif before.state is StateId.TUMBLE and not before.grounded:
            if state is StateId.TECH_ROLL:
                self._rolls[index] = _Roll(TECH, view.pos, frame)
            elif state is StateId.TECH:
                self.record(index, TECH, "tech")
            elif state is StateId.KNOCKDOWN:
                self.record(index, TECH, "miss")

    def _settle_roll(self, index: int, view: FighterView, frame: int) -> None:
        roll = self._rolls.get(index)
        if roll is None or frame - roll.frame < ROLL_SETTLE:
            return
        del self._rolls[index]
        inward = self.respawn - roll.start.xy
        moved = view.pos.xy - roll.start.xy
        towards = moved.dot(inward) >= 0.0
        if roll.situation == GETUP:
            self.record(index, GETUP, "roll in" if towards else "roll out")
        else:
            self.record(index, TECH, "tech in" if towards else "tech out")

    def _watch_guard(
        self, index: int, me: FighterView, view: FighterView, frame: int, started: bool
    ) -> None:
        watch = self._watch.get(index)
        if watch is not None:
            start, shielded = watch
            shielded = shielded or view.state in SHIELDING
            if frame - start > config.CPU_HABIT_GUARD_FRAMES:
                del self._watch[index]
                counts = self._guard.setdefault(index, [0.0, 0.0])
                counts[0] = counts[0] * config.CPU_HABIT_DECAY + (1.0 if shielded else 0.0)
                counts[1] = counts[1] * config.CPU_HABIT_DECAY + 1.0
            else:
                self._watch[index] = (start, shielded)
        if (
            started
            and index not in self._watch
            and view.grounded
            and (view.pos.xy - me.pos.xy).length() <= config.CPU_HABIT_NEAR
        ):
            self._watch[index] = (frame, view.state in SHIELDING)

    def record(self, opponent: int, situation: str, option: str) -> None:
        """Count one choice ``option`` of ``opponent`` in ``situation``."""
        _decayed(self._options.setdefault((opponent, situation), {}), option)

    # --- reading -------------------------------------------------------------------------

    def _trust(self, weight: float) -> float:
        return self.adapt * weight / (weight + config.CPU_HABIT_CONFIDENCE)

    def options(self, opponent: int, situation: str) -> Mapping[str, float]:
        """The opponent's choices in ``situation`` as shares (empty if never seen)."""
        counts = self._options.get((opponent, situation), {})
        total = sum(counts.values())
        if total <= 0.0:
            return {}
        return {name: value / total for name, value in counts.items()}

    def expected(self, opponent: int, situation: str) -> tuple[str, float] | None:
        """The choice the CPU expects in ``situation`` and how much it trusts that (0 to 1),
        or ``None`` when it has no reason to expect anything in particular."""
        counts = self._options.get((opponent, situation), {})
        total = sum(counts.values())
        if total <= 0.0:
            return None
        name = max(sorted(counts), key=counts.__getitem__)
        share = counts[name] / total
        trust = self._trust(total) * share
        if share < config.CPU_HABIT_SURE or trust < config.CPU_HABIT_TRUST:
            return None
        return name, trust

    def guard(self, opponent: int, prior: float) -> float:
        """How likely the opponent is to be shielding when the CPU swings near it: the prior
        moved toward what the CPU has seen, as far as it trusts that."""
        counts = self._guard.get(opponent)
        if counts is None or counts[1] <= 0.0:
            return prior
        trust = self._trust(counts[1])
        return prior + (counts[0] / counts[1] - prior) * trust

    def share(self, opponent: int, moves: Iterable[str]) -> float:
        """The trusted share of ``moves`` among the opponent's recent moves."""
        counts = self._moves.get(opponent, {})
        total = sum(counts.values())
        if total <= 0.0:
            return 0.0
        wanted = set(moves)
        part = sum(value for name, value in counts.items() if name in wanted)
        return part / total * self._trust(total)


class OwnMoves:
    """The CPU's own recent moves, so it can avoid repeating itself."""

    def __init__(self) -> None:
        self._counts: dict[str, float] = {}

    def used(self, name: str) -> None:
        """Count one use of ``name``."""
        _decayed(self._counts, name)

    def share(self, name: str) -> float:
        """The share of recent moves that were ``name``."""
        total = sum(self._counts.values())
        return self._counts.get(name, 0.0) / total if total > 0.0 else 0.0
