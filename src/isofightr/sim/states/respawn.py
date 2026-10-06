"""Match-flow states: KO (waiting to respawn) and Revival (on the revival platform).

Plan note "04 - Movement and Physics" ("Blast zones and KO", "Respawn").
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim.combat.constants import MAX_DAMAGE, SHIELD_MAX_HP
from isofightr.sim.constants import (
    RESPAWN_DELAY_FRAMES,
    REVIVAL_HEIGHT,
    REVIVAL_MAX_FRAMES,
    REVIVAL_SPACING,
)
from isofightr.sim.events import RespawnEvent
from isofightr.sim.fighter import NO_PARTNER, Fighter, GroundKind, StateId
from isofightr.sim.input_frame import VERTICAL_NONE, Dir8, Press
from isofightr.sim.math3d import ZERO2, ZERO3, Vec3
from isofightr.sim.stage import NO_PLATFORM
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import State, change_state, register
from isofightr.sim.states.ground import leave_ground

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def revival_point(match: Match, fighter: Fighter) -> Vec3:
    """Return where a fighter's revival platform hovers.

    Above the stage's respawn point, with fighters spread along the screen-horizontal axis
    so several respawning at once do not stack.
    """
    offset = fighter.player_index - (len(match.fighters) - 1) / 2
    side = Dir8.E.world * (offset * REVIVAL_SPACING)
    base = match.stage.respawn_point()
    return Vec3(base.x + side.x, base.y + side.y, base.z + REVIVAL_HEIGHT)


@register
class Ko(State):
    """Out of play after crossing a blast zone, until the respawn delay runs out."""

    id = StateId.KO

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Stop all motion; the fighter is no longer in the world."""
        fighter.vel = ZERO3
        fighter.kb_vel = ZERO3
        fighter.drive = ZERO2
        fighter.fast_falling = False
        fighter.ground = GroundKind.NONE
        fighter.platform = NO_PLATFORM
        fighter.drop_platform = NO_PLATFORM
        fighter.hitlag = 0
        fighter.hitstun = 0
        fighter.launch = None
        fighter.intangible_frames = 0
        fighter.stun_frames = 0
        fighter.tech_window = 0
        fighter.tech_lockout = 0

    def step(self, match: Match, fighter: Fighter) -> None:
        """Respawn after the delay, unless out of stocks."""
        if fighter.state_frame > RESPAWN_DELAY_FRAMES and not fighter.eliminated:
            change_state(match, fighter, StateId.REVIVAL)


@register
class Revival(State):
    """Standing on the revival platform: invincible until the fighter leaves it."""

    id = StateId.REVIVAL

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Appear on the platform at the rules' starting damage (0% unless they say more),
        with fresh air jumps and an empty input buffer."""
        fighter.pos = revival_point(match, fighter)
        fighter.ground = GroundKind.REVIVAL
        fighter.damage = min(max(match.rules.start_damage, 0.0), MAX_DAMAGE)
        fighter.last_hit_by = NO_PARTNER
        fighter.last_hit_timer = 0
        fighter.combo_hits = 0
        fighter.shield_hp = SHIELD_MAX_HP
        fighter.dodge_stale = 0
        fighter.air_dodge_used = False
        fighter.ledge_grabs = 0
        fighter.ledge_cooldown = 0
        fighter.air_jumps_left = fighter.character.movement.air_jumps
        fighter.buffer.clear()
        centre = match.stage.respawn_point()
        interrupts.snap_facing(fighter, (centre - fighter.pos).xy)
        match.events.append(RespawnEvent(fighter.player_index, fighter.pos))

    def step(self, match: Match, fighter: Fighter) -> None:
        """Jump off, or drop on any other input or when the platform times out."""
        if interrupts.ground_jump(match, fighter):
            return
        buffer = fighter.buffer
        acted = buffer.stick_active or buffer.vertical != VERTICAL_NONE or buffer.pressed != 0
        if acted or fighter.state_frame > REVIVAL_MAX_FRAMES:
            buffer.consume(Press.DOWN)  # the tap that dropped us must not also fast-fall
            buffer.consume(Press.FLICK)
            leave_ground(fighter)
            change_state(match, fighter, StateId.FALL)
