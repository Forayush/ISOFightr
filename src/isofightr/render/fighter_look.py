"""Decides how a fighter's sprite looks this frame, from sim state.

Plan note "03 - Isometric World and Rendering" ("Fighter sprite selection", "Hit flash",
"Hitlag shake", "Charge flash"). A character with packed sprites shows an animation pose
(:mod:`isofightr.render.anim_select`) in its costume; one without keeps the placeholder
capsule's three poses (standing, tumbling and lying down). Reads the fighter; never changes it.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from isofightr.data.sprite_sheet import AnimInfo
from isofightr.render.anim_select import AnimChoice, select_anim
from isofightr.sim.combat.constants import GETUP_FRAMES
from isofightr.sim.fighter import NO_TEAM, Fighter, StateId

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
    sprite: AnimChoice | None = None
    """The animation pose to draw; ``None`` draws the placeholder capsule."""
    costume: int = 0
    character: str = ""
    """Whose sprites ``sprite`` refers to."""


DEFAULT_LOOK: Final[FighterLook] = FighterLook()


def costume_for(fighter: Fighter, costumes: int) -> int:
    """Return the costume a fighter wears.

    In a free-for-all player 1 wears costume 0 (the character's default) and the others the
    costume of their player colour; in a team match everyone wears their team's colour.
    Costumes 1 to 4 are red, blue, yellow and green, in player-colour order (plan note
    "09 - Art Direction", "Palette swaps").
    """
    if fighter.team == NO_TEAM and fighter.color_index == 0:
        return 0
    return (1 + fighter.color_index) % max(costumes, 1)


def fighter_look(
    fighter: Fighter,
    frame: int,
    flash_frames: int = 0,
    anims: Mapping[str, AnimInfo] | None = None,
    costume: int = 0,
) -> FighterLook:
    """Return a fighter's look.

    Args:
        fighter: the fighter to draw.
        frame: the match frame, which times the blinks and the shake.
        flash_frames: ticks of hit flash left for this fighter (from ``BattleEffects``).
        anims: the character's animations, if it has packed sprites.
        costume: the costume to draw them in.
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
        sprite=None if anims is None else select_anim(fighter, anims),
        costume=costume,
        character="" if anims is None else fighter.character.id,
    )
