"""Decides how a fighter's placeholder sprite looks this frame, from sim state.

Plan note "03 - Isometric World and Rendering" ("Hit flash", "Hitlag shake", "Charge flash").
Until real animations arrive in M8 a fighter has three poses: standing, tumbling (the capsule
spins) and lying down. Reads the fighter; never changes it.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final

from isofightr.sim.combat.constants import GETUP_FRAMES
from isofightr.sim.fighter import Fighter, StateId

HITLAG_SHAKE_PIXELS: Final[int] = 1
HITLAG_SHAKE_FLIP_FRAMES: Final[int] = 2
"""The victim's sprite hops between +1 and -1 px every this many frames of hitlag."""
CHARGE_BLINK_FRAMES: Final[int] = 3
TUMBLE_SPIN_FRAMES: Final[int] = 5
"""A tumbling fighter turns a quarter turn every this many frames."""
QUARTER_TURNS: Final[int] = 4
ROLL_SPIN_FRAMES: Final[int] = 4
ROLLING_STATES: Final[frozenset[StateId]] = frozenset(
    {StateId.ROLL, StateId.TECH_ROLL, StateId.GETUP_ROLL, StateId.LEDGE_ROLL}
)
"""States drawn as a spinning capsule until rolls have animations."""
INTANGIBLE_BLINK_FRAMES: Final[int] = 2
"""An intangible fighter's sprite is hidden for this many frames, then shown for as many."""
DIZZY_WOBBLE: Final[tuple[int, ...]] = (-1, 0, 1, 0)
DIZZY_WOBBLE_FRAMES: Final[int] = 6


class Pose(Enum):
    """The placeholder poses."""

    STAND = "stand"
    TUMBLE = "tumble"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class FighterLook:
    """How to draw a fighter this frame."""

    pose: Pose = Pose.STAND
    quarter_turns: int = 0
    """Rotation of a tumbling fighter, in quarter turns."""
    flash: bool = False
    """Draw the sprite solid white."""
    offset_x: int = 0
    """Sideways sprite offset in native pixels (hitlag shake, dizzy wobble)."""
    hidden: bool = False
    """Skip the sprite this frame (the blink of an intangible fighter)."""
    dim: bool = False
    """Draw the sprite darkened (helpless)."""


DEFAULT_LOOK: Final[FighterLook] = FighterLook()


def fighter_look(fighter: Fighter, frame: int, flash_frames: int = 0) -> FighterLook:
    """Return a fighter's look.

    Args:
        fighter: the fighter to draw.
        frame: the match frame, which times the blinks and the shake.
        flash_frames: ticks of hit flash left for this fighter (from ``BattleEffects``).
    """
    pose, turns = Pose.STAND, 0
    if fighter.state is StateId.TUMBLE:
        pose = Pose.TUMBLE
        turns = (fighter.state_frame // TUMBLE_SPIN_FRAMES) % QUARTER_TURNS
    elif fighter.state is StateId.KNOCKDOWN or (
        fighter.state is StateId.GETUP and fighter.state_frame <= GETUP_FRAMES // 2
    ):
        pose = Pose.DOWN
    elif fighter.state in ROLLING_STATES:
        pose = Pose.TUMBLE
        turns = (fighter.state_frame // ROLL_SPIN_FRAMES) % QUARTER_TURNS

    charging = fighter.state is StateId.ATTACK and fighter.charge_frames > 0
    charge_blink = charging and (frame // CHARGE_BLINK_FRAMES) % 2 == 0
    # Only the victim shakes: it is the one with a launch waiting for hitlag to end.
    shaking = fighter.hitlag > 0 and fighter.launch is not None
    offset = 0
    if shaking:
        left = (frame // HITLAG_SHAKE_FLIP_FRAMES) % 2 == 0
        offset = -HITLAG_SHAKE_PIXELS if left else HITLAG_SHAKE_PIXELS
    elif fighter.state is StateId.DIZZY:
        offset = DIZZY_WOBBLE[(frame // DIZZY_WOBBLE_FRAMES) % len(DIZZY_WOBBLE)]
    blink_off = (frame // INTANGIBLE_BLINK_FRAMES) % 2 == 1
    return FighterLook(
        pose,
        turns,
        flash_frames > 0 or charge_blink,
        offset,
        hidden=fighter.intangible and blink_off,
        dim=fighter.state is StateId.HELPLESS,
    )
