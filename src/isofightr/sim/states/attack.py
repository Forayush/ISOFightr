"""The ``Attack`` state: one generic runner for every data-driven move, plus ``Rebound``.

Plan note "07 - Fighter State Machine and Move Data": attack states are generic; a single
state runs any move from data (hit windows, scripted motion, charge, cancels, FAF). The
hitboxes themselves are read from the move by :mod:`isofightr.sim.combat.hitbox`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.combat.constants import REBOUND_FRAMES
from isofightr.sim.combat.hitbox import local_to_world
from isofightr.sim.combat.staling import stale_multiplier
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Button, Press
from isofightr.sim.math3d import ZERO3
from isofightr.sim.move_def import MoveDef
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import State, change_state, register

if TYPE_CHECKING:
    from isofightr.sim.match import Match


def _end(match: Match, fighter: Fighter) -> None:
    """Hand control back after a move or a rebound."""
    if fighter.grounded:
        interrupts.become_ground_neutral(match, fighter)
    else:
        change_state(match, fighter, StateId.FALL)


@register
class Attack(State):
    """Performing ``fighter.move_id``. ``state_frame`` is the move frame."""

    id = StateId.ATTACK

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Start the move fresh: no charge, nothing hit yet. Staling is fixed here, so every
        hit of a multi-hit move is staled alike."""
        fighter.move_stale = stale_multiplier(fighter.stale_queue, fighter.move_id)
        fighter.charge_frames = 0
        fighter.hit_log = {}
        fighter.move_connected = False
        fighter.hitbox_centres = {}

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Forget the swept hitbox positions."""
        fighter.hitbox_centres = {}

    def step(self, match: Match, fighter: Fighter) -> None:
        """Charge, chain, become actionable at the FAF, and end after the last frame."""
        move = fighter.character.moves[fighter.move_id]
        if self._hold_charge(fighter, move):
            return
        frame = fighter.state_frame
        cancel = move.cancel
        if cancel is not None and frame in cancel.frames and fighter.buffer.consume(Press.ATTACK):
            interrupts.start_move(match, fighter, cancel.into)
            return
        if frame > move.total:
            _end(match, fighter)
        elif frame >= move.faf:
            table = interrupts.GROUND_RECOVER if fighter.grounded else interrupts.AIR_NEUTRAL
            interrupts.run_interrupts(match, fighter, table)

    @staticmethod
    def _hold_charge(fighter: Fighter, move: MoveDef) -> bool:
        """Stay on the charge frame while the strong button is held, up to the maximum."""
        charge = move.charge
        if charge is None or fighter.state_frame != charge.frame + 1:
            return False
        if fighter.charge_frames >= charge.max_frames or not fighter.buffer.holds(Button.STRONG):
            return False
        fighter.charge_frames += 1
        fighter.state_frame = charge.frame
        return True

    def motion(self, match: Match, fighter: Fighter) -> None:
        """On the ground: the move's scripted velocity, else traction. In the air: fall and
        drift as usual."""
        if not fighter.grounded:
            physics.apply_gravity(fighter)
            physics.apply_air_drift(fighter)
            return
        scripted = fighter.character.moves[fighter.move_id].scripted_velocity(fighter.state_frame)
        if scripted is None:
            physics.apply_traction(fighter)
        else:
            world = local_to_world(ZERO3, fighter.facing.world, scripted)
            physics.set_ground_velocity(fighter, world.xy)

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Landing interrupts an aerial with its own landing lag, unless it autocancels."""
        move = fighter.character.moves[fighter.move_id]
        frame = fighter.state_frame
        if any(frame in window for window in move.autocancel):
            fighter.land_lag = fighter.character.movement.land_lag
        else:
            fighter.land_lag = move.landing_lag
        change_state(match, fighter, StateId.LAND)


@register
class Rebound(State):
    """Knocked back out of an attack by a clank."""

    id = StateId.REBOUND

    def step(self, match: Match, fighter: Fighter) -> None:
        """Recover after the rebound."""
        if fighter.state_frame > REBOUND_FRAMES:
            _end(match, fighter)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Slide to a stop on the ground; fall normally in the air."""
        if fighter.grounded:
            physics.apply_traction(fighter)
        else:
            physics.apply_gravity(fighter)
            physics.apply_air_drift(fighter)
