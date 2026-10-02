"""Shield states: Shield, ShieldStun, ShieldDrop, ShieldBreak and Dizzy.

Plan note "06 - Shield Dodge Grab and Ledge" ("Shield"). Blocking itself happens in hit
resolution; these states run the shield's HP, its out-of-shield options and what happens
when it breaks.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat import constants as c
from isofightr.sim.combat.shield import dizzy_frames
from isofightr.sim.events import ShieldBreakEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_UP, Button, Press
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import GroundState, State, change_state, register
from isofightr.sim.states.ground import leave_ground

if TYPE_CHECKING:
    from isofightr.sim.match import Match


@register
class Shield(GroundState):
    """Holding the shield up. It drains while held and breaks at zero."""

    id = StateId.SHIELD
    stops_at_edges = True
    regens_shield = False

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Use up the press that raised the shield."""
        fighter.buffer.consume(Press.SHIELD)

    def step(self, match: Match, fighter: Fighter) -> None:
        """Drain, then: out-of-shield option, dodge, or drop the shield when released."""
        fighter.shield_hp -= c.SHIELD_DECAY
        if fighter.shield_hp <= 0.0:
            change_state(match, fighter, StateId.SHIELD_BREAK)
            return
        buffer = fighter.buffer
        if interrupts.ground_jump(match, fighter):
            return
        # Grab out of shield: the grab button, or attack while shielding.
        if buffer.consume(Press.GRAB) or buffer.consume(Press.ATTACK):
            change_state(match, fighter, StateId.GRAB)
            return
        if buffer.vertical == VERTICAL_UP and buffer.consume(Press.SPECIAL):
            buffer.consume(Press.UP)
            interrupts.start_move(match, fighter, fighter.character.moveset.uspecial)
            return
        if buffer.vertical == VERTICAL_UP and buffer.consume(Press.STRONG):
            buffer.consume(Press.UP)
            interrupts.start_move(match, fighter, fighter.character.moveset.usmash)
            return
        if buffer.consume(Press.DOWN):
            change_state(match, fighter, StateId.SPOT_DODGE)
            return
        if buffer.stick_active and buffer.consume(Press.FLICK):
            change_state(match, fighter, StateId.ROLL)
            return
        if not buffer.holds(Button.SHIELD) and fighter.state_frame >= c.SHIELD_MIN_FRAMES:
            change_state(match, fighter, StateId.SHIELD_DROP)


@register
class ShieldStun(GroundState):
    """Frozen behind the shield after blocking a hit."""

    id = StateId.SHIELD_STUN
    stops_at_edges = True
    regens_shield = False

    def step(self, match: Match, fighter: Fighter) -> None:
        """Count the stun down, then go back to shielding or drop the shield."""
        fighter.stun_frames -= 1
        if fighter.stun_frames > 0:
            return
        fighter.stun_frames = 0
        held = fighter.buffer.holds(Button.SHIELD)
        change_state(match, fighter, StateId.SHIELD if held else StateId.SHIELD_DROP)


@register
class ShieldDrop(GroundState):
    """Lowering the shield: a short lag before anything else."""

    id = StateId.SHIELD_DROP
    stops_at_edges = True

    def step(self, match: Match, fighter: Fighter) -> None:
        """Become actionable once the shield is down."""
        if fighter.state_frame > c.SHIELD_DROP_FRAMES:
            interrupts.become_ground_neutral(match, fighter)


@register
class ShieldBreak(State):
    """Shield broken: popped into the air, helpless, and dizzy on landing."""

    id = StateId.SHIELD_BREAK
    regens_shield = False

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Pop straight up with a partly refilled shield."""
        fighter.shield_hp = c.SHIELD_BREAK_HP
        fighter.vel = Vec3(0.0, 0.0, c.SHIELD_BREAK_POP)
        fighter.kb_vel = ZERO3
        fighter.fast_falling = False
        leave_ground(fighter)
        match.events.append(ShieldBreakEvent(fighter.player_index, fighter.pos))

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Rise and fall with no control."""
        physics.apply_gravity(fighter)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Land dizzy: longer at low damage."""
        fighter.stun_frames = dizzy_frames(fighter.damage)
        change_state(match, fighter, StateId.DIZZY)


@register
class Dizzy(GroundState):
    """Stunned after a shield break. Wide open."""

    id = StateId.DIZZY
    regens_shield = False

    def step(self, match: Match, fighter: Fighter) -> None:
        """Recover when the stun runs out."""
        fighter.stun_frames -= 1
        if fighter.stun_frames <= 0:
            fighter.stun_frames = 0
            interrupts.become_ground_neutral(match, fighter)
