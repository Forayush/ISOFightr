"""The state machine framework: the ``State`` base class, the state table, ``change_state``.

Plan note "07 - Fighter State Machine and Move Data" ("State machine design"). Each state is
a class with ``enter``, ``step`` and ``exit``, registered in a table; there are no if/else
chains over state ids. States hold no data of their own: everything lives on the ``Fighter``,
so the sim copies and hashes exactly.

Frame convention: the tick a state is entered is its frame 1 (``enter`` is that frame's
logic). ``step`` then runs once per tick from frame 2 on, after ``state_frame`` is advanced.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from isofightr.sim import physics
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.math3d import Vec2, Vec3

if TYPE_CHECKING:
    from isofightr.sim.match import Match


class State:
    """Behaviour of one fighter state. Subclasses set ``id`` and override what they need."""

    id: ClassVar[StateId]
    uses_physics: ClassVar[bool] = True
    """False for states that place the fighter themselves (hanging, climbing, being held)."""
    stops_at_edges: ClassVar[bool] = False
    """True for grounded states that cannot slide or move off an edge (shield, rolls...)."""
    grabs_ledges: ClassVar[bool] = False
    """True for airborne states in which a falling fighter catches a nearby ledge."""
    regens_shield: ClassVar[bool] = True

    def enter(self, match: Match, fighter: Fighter) -> None:
        """Run once when the fighter enters this state (its frame 1)."""

    def step(self, match: Match, fighter: Fighter) -> None:
        """Check interrupts and transitions (tick step 3). Runs from frame 2 on."""

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Update the fighter's velocity before physics moves it (start of tick step 5)."""

    def exit(self, match: Match, fighter: Fighter) -> None:
        """Run once when the fighter leaves this state."""

    def on_land(self, match: Match, fighter: Fighter) -> None:
        """Physics landed the fighter this tick. By default: normal landing lag."""
        fighter.land_lag = fighter.character.movement.land_lag
        change_state(match, fighter, StateId.LAND)

    def on_leave_ground(self, match: Match, fighter: Fighter) -> None:
        """The fighter walked, slid or was pushed off an edge. By default: fall."""
        change_state(match, fighter, StateId.FALL)

    def on_wall(self, match: Match, fighter: Fighter, normal: Vec2, knockback: Vec3) -> None:
        """An airborne fighter ran into a wall. ``normal`` points away from the wall and
        ``knockback`` is the knockback velocity it had before the wall stopped it."""


class GroundState(State):
    """Default motion for grounded states: slide to a stop under traction."""

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Slow down by the character's traction."""
        physics.apply_traction(fighter)


class AirState(State):
    """Default motion for airborne states: gravity plus air drift."""

    def motion(self, match: Match, fighter: Fighter) -> None:
        """Fall and steer."""
        physics.apply_gravity(fighter)
        physics.apply_air_drift(fighter)


STATES: dict[StateId, State] = {}
"""The state table. Every ``StateId`` has exactly one entry once ``sim.states`` is imported."""


def register[S: State](state_class: type[S]) -> type[S]:
    """Class decorator: add a state to the table under its ``id``."""
    if state_class.id in STATES:
        raise ValueError(f"state {state_class.id} is registered twice")
    STATES[state_class.id] = state_class()
    return state_class


def change_state(match: Match, fighter: Fighter, new_state: StateId) -> None:
    """Move a fighter to another state. The only way a fighter's state may change.

    Runs the old state's ``exit`` and the new state's ``enter``, so enter/exit logic can never
    be skipped. Re-entering the current state restarts it.
    """
    STATES[fighter.state].exit(match, fighter)
    fighter.state = new_state
    fighter.state_frame = 1
    STATES[new_state].enter(match, fighter)
