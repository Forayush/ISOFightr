"""Training dummy behaviours: simple scripted input for players 2 to 4 in training mode.

Plan note "13 - Game Modes UI and Flow" ("Training mode": CPU behavior stand, walk, jump,
shield, attack, act like a CPU, or controlled manually). The CPU behaviour is run by the
battle scene, which owns the controllers; :func:`dummy_frame` covers the scripted ones.
An input source like any other: it only produces ``InputFrame``s.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from enum import Enum
from typing import Final

from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame

WALK_LEG_FRAMES: Final[int] = 50
"""A walking dummy turns around every this many frames."""
WALK_TILT: Final[float] = 0.6
JUMP_EVERY: Final[int] = 70
JUMP_HOLD: Final[int] = 8
ATTACK_EVERY: Final[int] = 45
ATTACK_HOLD: Final[int] = 2


class DummyBehavior(Enum):
    """What a training dummy does."""

    STAND = "stand"
    WALK = "walk"
    JUMP = "jump"
    SHIELD = "shield"
    ATTACK = "attack"
    CPU = "cpu"
    """Played by a CPU opponent (:mod:`isofightr.ai.controller`) at the chosen level."""
    MANUAL = "manual"
    """Controlled by its own player's devices."""


def dummy_frame(behavior: DummyBehavior, frame: int, manual: InputFrame) -> InputFrame:
    """Return a dummy's input on a match frame. ``manual`` is its player's real input."""
    if behavior is DummyBehavior.MANUAL:
        return manual
    if behavior is DummyBehavior.WALK:
        forward = (frame // WALK_LEG_FRAMES) % 2 == 0
        direction = Dir8.E if forward else Dir8.W
        return InputFrame(move=direction.world * WALK_TILT, held=int(Button.WALK))
    if behavior is DummyBehavior.JUMP:
        return InputFrame(held=int(Button.JUMP) if frame % JUMP_EVERY < JUMP_HOLD else 0)
    if behavior is DummyBehavior.SHIELD:
        return InputFrame(held=int(Button.SHIELD))
    if behavior is DummyBehavior.ATTACK:
        return InputFrame(held=int(Button.ATTACK) if frame % ATTACK_EVERY < ATTACK_HOLD else 0)
    return NEUTRAL_INPUT
