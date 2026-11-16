"""Strolling: scripted input for the fighters that live on the menus' island.

Plan note "13 - Game Modes UI and Flow" ("Planned (M21)", decision D-072). The menus are drawn
on a piece of the game's world with the roster on it. A stroller is what plays one of them:
it stands, walks a few steps to somewhere else on the plaza, turns, crouches or taunts, and
never jumps, attacks or shields, so nobody leaves the ground they were given. Like the
training dummy it is an input source: it only produces ``InputFrame``s, and what the fighter
then does is the sim's business.

It has its own seeded :class:`~isofightr.sim.rng.Rng`, so a session's menus are the same
every time for the same seed.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Protocol

from isofightr.sim.input_frame import NEUTRAL_INPUT, VERTICAL_DOWN, Button, InputFrame
from isofightr.sim.math3d import Vec2
from isofightr.sim.rng import Rng

WALK_TILT: Final[float] = 0.55
"""How far the stick is pushed while walking: a walk, never a dash."""
ARRIVE: Final[float] = 0.3
"""A walk ends this close to where it was going (tiles)."""
WALK_LIMIT: Final[int] = 240
"""A walk is given up after this many ticks, wherever it has got to."""
STAND_TICKS: Final[tuple[int, int]] = (50, 200)
CROUCH_TICKS: Final[tuple[int, int]] = (30, 80)
TAUNT_HOLD: Final[int] = 2
TAUNT_REST: Final[int] = 70
"""Ticks left alone after a taunt, so its animation plays out."""
TURN_TICKS: Final[int] = 3
CHOICES: Final[tuple[tuple[str, int], ...]] = (
    ("stand", 40),
    ("walk", 34),
    ("turn", 10),
    ("crouch", 6),
    ("taunt", 10),
)
"""What a stroller does next, and how likely (weights)."""


class Ground(Protocol):
    """Where a stroller may be: the plaza
    (:class:`isofightr.scenes.menu_world_model.Bounds`)."""

    def holds(self, x: float, y: float) -> bool:
        """Whether a ground position is inside."""
        ...

    def point(self, depth: float, across: float) -> tuple[float, float]:
        """Return the position at shares (0 to 1) of the way through it."""
        ...


class Doing(Enum):
    """What a stroller is in the middle of."""

    STAND = "stand"
    WALK = "walk"
    TURN = "turn"
    CROUCH = "crouch"
    TAUNT = "taunt"


class Stroller:
    """One fighter's stroll: a small plan, drawn again whenever it ends."""

    def __init__(self, seed: int, ground: Ground) -> None:
        """Create a stroller that keeps inside ``ground``."""
        self.rng = Rng.seeded(seed)
        self.ground = ground
        self.doing = Doing.STAND
        self.left = self.rng.between(*STAND_TICKS)
        """Ticks left of what it is doing."""
        self.goal: tuple[float, float] = ground.point(0.5, 0.5)
        """Where a walk is going (or the way a turn faces)."""

    def think(self, x: float, y: float) -> InputFrame:
        """Return this tick's input for a fighter standing at ``(x, y)``."""
        if not self.ground.holds(x, y):
            # Somewhere it should not be: walk back to the middle before anything else.
            self.doing, self.goal, self.left = Doing.WALK, self.ground.point(0.5, 0.5), WALK_LIMIT
        elif self.left <= 0 or (self.doing is Doing.WALK and self._arrived(x, y)):
            self._choose(x, y)
        self.left -= 1
        if self.doing is Doing.WALK or self.doing is Doing.TURN:
            return self._toward(x, y)
        if self.doing is Doing.CROUCH:
            return InputFrame(vertical=VERTICAL_DOWN)
        if self.doing is Doing.TAUNT and self.left >= TAUNT_REST:
            return InputFrame(held=int(Button.TAUNT))
        return NEUTRAL_INPUT

    def _arrived(self, x: float, y: float) -> bool:
        return (Vec2(*self.goal) - Vec2(x, y)).length() <= ARRIVE

    def _toward(self, x: float, y: float) -> InputFrame:
        heading = Vec2(*self.goal) - Vec2(x, y)
        distance = heading.length()
        if distance < 1e-6:
            return NEUTRAL_INPUT
        return InputFrame(move=heading * (WALK_TILT / distance), held=int(Button.WALK))

    def _choose(self, x: float, y: float) -> None:
        """Draw what to do next."""
        roll = self.rng.below(sum(weight for _, weight in CHOICES))
        name = CHOICES[-1][0]
        for choice, weight in CHOICES:
            if roll < weight:
                name = choice
                break
            roll -= weight
        self.doing = Doing(name)
        if self.doing is Doing.WALK:
            self.goal = self.ground.point(self.rng.random(), self.rng.random())
            self.left = WALK_LIMIT
        elif self.doing is Doing.TURN:
            # A step's worth of stick toward somewhere else: the fighter turns to face it.
            self.goal = self.ground.point(self.rng.random(), self.rng.random())
            self.left = TURN_TICKS
        elif self.doing is Doing.CROUCH:
            self.left = self.rng.between(*CROUCH_TICKS)
        elif self.doing is Doing.TAUNT:
            self.left = TAUNT_HOLD + TAUNT_REST
        else:
            self.left = self.rng.between(*STAND_TICKS)
