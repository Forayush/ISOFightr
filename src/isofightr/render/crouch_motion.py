"""How a crouch is drawn: dropping into it, holding it, and rising out of it (decision D-069).

The sim's ``CROUCH`` state says only that a fighter is crouching. This module times its
animations: ``crouch_enter`` over the crouch's first frames (skipped when the fighter was
already low, out of a down tilt, which ends in the crouch), then the ``crouch`` hold looping,
and ``crouch_exit`` for the first ticks after a crouch or a down tilt hands back to standing or
walking. A :class:`CrouchMotion` remembers, per player, what one tick ago it cannot read from
the sim (like :mod:`isofightr.render.hurt_motion`): step it once per sim tick.

Pure Python (no ``arcade``), so it is unit tested without a window. Reads the fighters; never
changes them.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from isofightr.data.sprite_sheet import AnimInfo
from isofightr.render.anim_select import AnimChoice
from isofightr.sim.combat.hitbox import low_profile
from isofightr.sim.fighter import Fighter, StateId

ENTER_ANIM: Final[str] = "crouch_enter"
HOLD_ANIM: Final[str] = "crouch"
EXIT_ANIM: Final[str] = "crouch_exit"
CROUCH_ANIMS: Final[tuple[str, ...]] = (ENTER_ANIM, HOLD_ANIM, EXIT_ANIM)
"""What every character with sprites must have (``tests/test_sprites.py``)."""
EXIT_TICKS: Final[int] = 3
"""How long ``crouch_exit`` shows after the fighter leaves a crouch (or a down tilt)."""
RISING_STATES: Final[frozenset[StateId]] = frozenset({StateId.IDLE, StateId.WALK})
"""The states a fighter rises into; anything else (an attack, a jump, a dodge) has its own
animation from its first frame."""


@dataclass(slots=True)
class CrouchTrack:
    """What one player's crouch looked like on the ticks before this one."""

    low: bool = False
    """Whether the fighter was low (crouching, or in a down tilt) on the last tick."""
    skip_enter: bool = False
    """This crouch began low (out of a down tilt): no ``crouch_enter``."""
    rising: int = 0
    """Ticks since the fighter stood up out of a crouch (0: it did not just stand up)."""


@dataclass(slots=True)
class CrouchMotion:
    """Every player's :class:`CrouchTrack`."""

    tracks: dict[int, CrouchTrack] = field(default_factory=dict)

    def step(self, fighters: Iterable[Fighter]) -> None:
        """Advance every player's track by one sim tick."""
        for fighter in fighters:
            track = self.tracks.setdefault(fighter.player_index, CrouchTrack())
            low = low_profile(fighter)
            if fighter.state is StateId.CROUCH and fighter.state_frame == 1:
                track.skip_enter = track.low
            if track.low and not low and fighter.state in RISING_STATES:
                track.rising = 1
            elif track.rising and fighter.state in RISING_STATES:
                track.rising += 1
            else:
                track.rising = 0
            if track.rising > EXIT_TICKS:
                track.rising = 0
            track.low = low

    def track(self, player: int) -> CrouchTrack | None:
        """Return a player's track, if it has been stepped."""
        return self.tracks.get(player)


def enter_frames(anims: Mapping[str, AnimInfo]) -> int:
    """Return how many frames ``crouch_enter`` lasts (0 without it): its last pose's start."""
    enter = anims.get(ENTER_ANIM)
    return max(enter.starts, default=0) if enter is not None else 0


def crouch_choice(
    fighter: Fighter, track: CrouchTrack | None, anims: Mapping[str, AnimInfo]
) -> AnimChoice | None:
    """Return the crouch pose a fighter shows, or ``None`` when its own state's animation (or
    the selector's fallback, without the crouch animations) should show instead."""
    if fighter.state is StateId.CROUCH:
        if HOLD_ANIM not in anims:
            return None
        frames = 0 if track is not None and track.skip_enter else enter_frames(anims)
        if fighter.state_frame <= frames:
            return AnimChoice(ENTER_ANIM, anims[ENTER_ANIM].pose_at(fighter.state_frame), True)
        return AnimChoice(HOLD_ANIM, anims[HOLD_ANIM].pose_at(fighter.state_frame - frames), True)
    if track is not None and track.rising and fighter.state in RISING_STATES:
        exit_anim = anims.get(EXIT_ANIM)
        if exit_anim is not None:
            return AnimChoice(EXIT_ANIM, exit_anim.pose_at(track.rising), True)
    return None
