"""The ``Attack`` state: one generic runner for every data-driven move, plus ``Rebound``.

Plan note "07 - Fighter State Machine and Move Data": attack states are generic; a single
state runs any move from data (hit windows, scripted motion, charge, cancels, FAF). The
hitboxes themselves are read from the move by :mod:`isofightr.sim.combat.hitbox`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.sim import physics
from isofightr.sim.characters import SCRIPTS
from isofightr.sim.combat.constants import REBOUND_FRAMES
from isofightr.sim.combat.hitbox import hit_damage, local_to_world
from isofightr.sim.combat.staling import stale_multiplier
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Button, Press
from isofightr.sim.math3d import ZERO3
from isofightr.sim.move_def import MoveDef, MoveKind
from isofightr.sim.states import interrupts
from isofightr.sim.states.base import State, change_state, register
from isofightr.sim.states.dodge import open_intangible_window

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
        fighter.counter_damage = 0.0
        move = fighter.character.moves[fighter.move_id]
        if move.once_per_airtime and not fighter.grounded:
            fighter.air_moves_used = [*fighter.air_moves_used, move.id]
        self._intangibility(fighter)
        if move.script is not None:
            SCRIPTS[move.script].on_start(match, fighter)
        self._fire(match, fighter, move)

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Forget the swept hitbox positions."""
        fighter.hitbox_centres = {}

    def step(self, match: Match, fighter: Fighter) -> None:
        """Charge, chain, become actionable at the FAF, and end after the last frame."""
        move = fighter.character.moves[fighter.move_id]
        self._intangibility(fighter)
        if move.script is not None:
            SCRIPTS[move.script].on_frame(match, fighter)
        if self._hold_charge(fighter, move):
            return
        self._fire(match, fighter, move)
        frame = fighter.state_frame
        cancel = move.cancel
        if cancel is not None and frame in cancel.frames and fighter.buffer.consume(Press.ATTACK):
            interrupts.start_move(match, fighter, cancel.into)
            return
        if frame > move.total:
            if move.helpless and not fighter.grounded:
                change_state(match, fighter, StateId.HELPLESS)
            else:
                _end(match, fighter)
        elif frame >= move.faf:
            table = interrupts.GROUND_RECOVER if fighter.grounded else interrupts.AIR_NEUTRAL
            interrupts.run_interrupts(match, fighter, table)

    @staticmethod
    def _intangibility(fighter: Fighter) -> None:
        """Open the move's intangible window, if it has one (getup and ledge attacks)."""
        window = fighter.character.moves[fighter.move_id].intangible
        if window is not None:
            open_intangible_window(fighter, (window.first, window.last))

    @staticmethod
    def _hold_charge(fighter: Fighter, move: MoveDef) -> bool:
        """Stay on the charge frame while the move's button is held, up to the maximum:
        strong for smash attacks, special for specials."""
        charge = move.charge
        if charge is None or fighter.state_frame != charge.frame + 1:
            return False
        button = Button.SPECIAL if move.kind is MoveKind.SPECIAL else Button.STRONG
        if fighter.charge_frames >= charge.max_frames or not fighter.buffer.holds(button):
            return False
        fighter.charge_frames += 1
        fighter.state_frame = charge.frame
        return True

    @staticmethod
    def _fire(match: Match, fighter: Fighter, move: MoveDef) -> None:
        """Spawn the projectiles the move fires on this frame."""
        for definition in move.projectiles:
            if definition.frame != fighter.state_frame:
                continue
            damage = hit_damage(fighter, definition.hitbox)
            projectile = match.spawn_projectile(fighter, definition, damage)
            if move.script is not None:
                SCRIPTS[move.script].on_projectile(match, fighter, projectile)

    def can_grab_ledge(self, fighter: Fighter) -> bool:
        """Some recovery moves catch ledges from a certain frame on."""
        first = fighter.character.moves[fighter.move_id].ledge_grab_from
        return first > 0 and fighter.state_frame >= first

    def on_leave_ground(self, match: Match, fighter: Fighter) -> None:
        """A special carries on off an edge or into the air; any other move is cut short."""
        if fighter.character.moves[fighter.move_id].kind is not MoveKind.SPECIAL:
            change_state(match, fighter, StateId.FALL)

    def motion(self, match: Match, fighter: Fighter) -> None:
        """A script's motion if the move has one; otherwise, on the ground: the move's
        scripted velocity, else traction; in the air: fall and drift as usual."""
        script = fighter.character.moves[fighter.move_id].script
        if script is not None and SCRIPTS[script].motion(match, fighter):
            return
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
        """Landing interrupts an aerial with its own landing lag, unless it autocancels or the
        move's script handles the landing itself."""
        move = fighter.character.moves[fighter.move_id]
        if move.script is not None and SCRIPTS[move.script].on_land(match, fighter):
            return
        frame = fighter.state_frame
        normal = fighter.character.movement.land_lag
        if any(frame in window for window in move.autocancel):
            fighter.land_lag = normal
        else:
            fighter.land_lag = max(move.landing_lag, normal)
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
