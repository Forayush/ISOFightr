"""``InputFrame``, ``InputBuffer`` and direction helpers.

Plan notes "08 - Controls and Input" and "07 - Fighter State Machine and Move Data".
An :class:`InputFrame` is one player's raw input for one tick, and it is all the sim ever
sees of a device, a CPU or a replay. An :class:`InputBuffer` (one per fighter) turns the
stream of frames into what states ask about: press edges, a short press buffer, and flicks.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Final

from isofightr.config import FACING_HYSTERESIS_DEGREES
from isofightr.sim.constants import (
    BUFFER_FRAMES,
    FLICK_FRAMES,
    FLICK_HIGH,
    FLICK_LOW,
    STICK_NEUTRAL,
)
from isofightr.sim.math3d import EPSILON, ZERO2, Vec2

SQRT2: Final[float] = math.sqrt(2.0)
DIR8_STEP_DEGREES: Final[float] = 45.0
FULL_TURN_DEGREES: Final[float] = 360.0


class Dir8(IntEnum):
    """The eight facings, named by **screen** compass, counter-clockwise from screen-right.

    The value times 45 degrees is the direction's angle in stick space (``u`` right, ``v`` up).
    """

    E = 0
    NE = 1
    N = 2
    NW = 3
    W = 4
    SW = 5
    S = 6
    SE = 7

    @property
    def stick_degrees(self) -> float:
        """The facing's angle in stick space, in degrees counter-clockwise from screen-right."""
        return self.value * DIR8_STEP_DEGREES

    @property
    def world(self) -> Vec2:
        """The facing as a unit vector on the world ground plane."""
        return _WORLD_VECTORS[self]


def stick_to_world(u: float, v: float) -> Vec2:
    """Convert a screen-relative stick vector (``u`` right, ``v`` up) to a world ground vector.

    Pushing right moves right on screen: screen-east is world ``(+1, -1)/sqrt(2)``. The
    transform is a pure rotation, so magnitude is preserved (plan note 08).
    """
    return Vec2((u - v) / SQRT2, (-u - v) / SQRT2)


def world_to_stick(world: Vec2) -> tuple[float, float]:
    """Inverse of :func:`stick_to_world`: a world ground vector as screen-relative ``(u, v)``."""
    return ((world.x - world.y) / SQRT2, (-world.x - world.y) / SQRT2)


def facing_from_move(move: Vec2, current: Dir8 | None = None) -> Dir8 | None:
    """Snap a world move vector to the nearest of the eight facings.

    With a ``current`` facing, the vector must point more than ``FACING_HYSTERESIS_DEGREES``
    past the 45-degree boundary before the facing changes, which stops jitter when the stick
    sits on a boundary. A zero vector keeps ``current``.
    """
    if move.length_squared() < EPSILON:
        return current
    u, v = world_to_stick(move)
    degrees = math.degrees(math.atan2(v, u))
    if current is not None:
        offset = _wrap_degrees(degrees - current.stick_degrees)
        if abs(offset) <= DIR8_STEP_DEGREES / 2 + FACING_HYSTERESIS_DEGREES:
            return current
    return Dir8(round(degrees / DIR8_STEP_DEGREES) % len(Dir8))


def _wrap_degrees(degrees: float) -> float:
    """Wrap an angle into ``[-180, 180)``."""
    half_turn = FULL_TURN_DEGREES / 2
    return (degrees + half_turn) % FULL_TURN_DEGREES - half_turn


_DIAGONAL: Final[float] = 1.0 / SQRT2

# The table from the plan note "03 - Isometric World and Rendering": stage edges are
# world-axis-aligned, so the four screen diagonals are the exact world axes.
_WORLD_VECTORS: Final[dict[Dir8, Vec2]] = {
    Dir8.E: Vec2(_DIAGONAL, -_DIAGONAL),
    Dir8.NE: Vec2(0.0, -1.0),
    Dir8.N: Vec2(-_DIAGONAL, -_DIAGONAL),
    Dir8.NW: Vec2(-1.0, 0.0),
    Dir8.W: Vec2(-_DIAGONAL, _DIAGONAL),
    Dir8.SW: Vec2(0.0, 1.0),
    Dir8.S: Vec2(_DIAGONAL, _DIAGONAL),
    Dir8.SE: Vec2(1.0, 0.0),
}


class Button(IntFlag):
    """Held buttons, as bits of :attr:`InputFrame.held` (plan note 08, "Logical actions")."""

    ATTACK = 1
    SPECIAL = 2
    STRONG = 4
    JUMP = 8
    SHIELD = 16
    GRAB = 32
    WALK = 64
    TAUNT = 128


VERTICAL_UP: Final[int] = 1
VERTICAL_DOWN: Final[int] = -1
VERTICAL_NONE: Final[int] = 0
MAX_STICK_MAGNITUDE: Final[float] = 1.0 + 1e-9


@dataclass(frozen=True, slots=True)
class InputFrame:
    """One player's raw input for one tick.

    Only what is *held* is stored. Press and release edges and stick flicks are derived inside
    the sim by :class:`InputBuffer`, so a frame can never contradict itself and scripted tests,
    CPUs and replays only have to say what is held (decision D-024).
    """

    move: Vec2 = ZERO2
    """World-space ground vector, magnitude 0 to 1."""
    vertical: int = VERTICAL_NONE
    """Vertical intent: ``+1`` up, ``-1`` down, ``0`` none."""
    held: int = 0
    """Bitmask of :class:`Button`."""
    cstick: Vec2 | None = None
    """World-space smash direction when the right stick is flicked (used from M3)."""

    def __post_init__(self) -> None:
        if self.move.length() > MAX_STICK_MAGNITUDE:
            raise ValueError(f"move magnitude must be at most 1, got {self.move.length()}")
        if self.vertical not in (VERTICAL_UP, VERTICAL_NONE, VERTICAL_DOWN):
            raise ValueError(f"vertical must be -1, 0 or +1, got {self.vertical}")


NEUTRAL_INPUT: Final[InputFrame] = InputFrame()


class Press(IntEnum):
    """Everything that can be buffered: button presses, vertical taps, stick flicks and
    right-stick ("C-stick") smash inputs."""

    ATTACK = 0
    SPECIAL = 1
    STRONG = 2
    JUMP = 3
    SHIELD = 4
    GRAB = 5
    TAUNT = 6
    UP = 7
    DOWN = 8
    FLICK = 9
    CSTICK = 10


_BUTTON_PRESSES: Final[tuple[tuple[int, Press], ...]] = (
    (Button.ATTACK, Press.ATTACK),
    (Button.SPECIAL, Press.SPECIAL),
    (Button.STRONG, Press.STRONG),
    (Button.JUMP, Press.JUMP),
    (Button.SHIELD, Press.SHIELD),
    (Button.GRAB, Press.GRAB),
    (Button.TAUNT, Press.TAUNT),
)
_BUTTON_PRESS_BITS: Final[tuple[tuple[int, Press], ...]] = tuple(
    (int(button), press) for button, press in _BUTTON_PRESSES
)
_EXPIRED: Final[int] = BUFFER_FRAMES


def _expired_ages() -> list[int]:
    return [_EXPIRED] * len(Press)


def _neutral_history() -> list[Vec2]:
    return [ZERO2] * FLICK_FRAMES


@dataclass(slots=True)
class InputBuffer:
    """A fighter's view of its input: the current frame, edges, buffered presses and flicks.

    ``push`` is called once per tick, first thing (step 1 of the per-tick order in the plan
    note "02 - Technical Architecture"). A press stays buffered for ``BUFFER_FRAMES`` frames,
    counting the frame it happened on, until a state consumes it.
    """

    frame: InputFrame = NEUTRAL_INPUT
    pressed: int = 0
    """:class:`Button` bits that went down this frame."""
    released: int = 0
    """:class:`Button` bits that went up this frame."""
    ages: list[int] = field(default_factory=_expired_ages)
    """Frames since each :class:`Press` last happened; ``BUFFER_FRAMES`` or more = expired."""
    history: list[Vec2] = field(default_factory=_neutral_history)
    """The stick vectors of the previous ``FLICK_FRAMES`` frames, oldest first."""
    cstick_press: Vec2 = ZERO2
    """The direction of the last right-stick press, kept while it is buffered: a quick flick
    is often back in the centre by the time a state uses it (e.g. after a jumpsquat)."""

    def push(self, frame: InputFrame) -> None:
        """Take this tick's frame and update edges, buffered presses and flick detection."""
        previous = self.frame
        # Plain ints: IntFlag operators are many times slower, and this runs for every
        # fighter on every tick.
        held, held_before = int(frame.held), int(previous.held)
        self.pressed = held & ~held_before
        self.released = held_before & ~held
        for index in range(len(self.ages)):
            if self.ages[index] < _EXPIRED:
                self.ages[index] += 1
        pressed = self.pressed
        if pressed:
            for bit, press in _BUTTON_PRESS_BITS:
                if pressed & bit:
                    self.ages[press] = 0
        if frame.vertical == VERTICAL_UP and previous.vertical != VERTICAL_UP:
            self.ages[Press.UP] = 0
        if frame.vertical == VERTICAL_DOWN and previous.vertical != VERTICAL_DOWN:
            self.ages[Press.DOWN] = 0
        if frame.cstick is not None and previous.cstick is None:
            self.ages[Press.CSTICK] = 0
            self.cstick_press = frame.cstick
        if _is_flick(frame.move, self.history):
            self.ages[Press.FLICK] = 0
        self.history = [*self.history[1:], frame.move]
        self.frame = frame

    @property
    def move(self) -> Vec2:
        """This tick's world-space stick vector."""
        return self.frame.move

    @property
    def stick_active(self) -> bool:
        """Whether the stick is pushed beyond the neutral zone."""
        return self.frame.move.length() > STICK_NEUTRAL

    @property
    def vertical(self) -> int:
        """This tick's vertical intent."""
        return self.frame.vertical

    def holds(self, button: Button) -> bool:
        """Return whether ``button`` is held this tick."""
        return bool(int(self.frame.held) & int(button))

    def has(self, press: Press) -> bool:
        """Return whether ``press`` happened within the buffer window and is unconsumed."""
        return self.ages[press] < BUFFER_FRAMES

    def consume(self, press: Press) -> bool:
        """Use up a buffered press. Returns whether there was one."""
        if self.ages[press] < BUFFER_FRAMES:
            self.ages[press] = _EXPIRED
            return True
        return False

    def clear(self) -> None:
        """Forget every buffered press and flick (e.g. on respawn)."""
        self.ages = _expired_ages()


def _is_flick(move: Vec2, history: list[Vec2]) -> bool:
    """Return whether the stick was just flicked to ``move``.

    A flick is a quick, decisive push: the stick is now beyond ``FLICK_HIGH``, and within the
    last ``FLICK_FRAMES`` frames it was either near neutral (below ``FLICK_LOW``) or pointing
    the opposite way. Holding a direction, or rolling the stick around its rim, is not a
    flick. Digital input (keyboard) flicks on every fresh direction press.
    """
    if move.length() <= FLICK_HIGH:
        return False
    previous = history[-1]
    if previous.length() > FLICK_HIGH and previous.dot(move) > 0:
        return False  # already pushed this way last frame
    return any(past.length() < FLICK_LOW or past.dot(move) < 0 for past in history)
