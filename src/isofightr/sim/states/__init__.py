"""The fighter state machine, one module per state family.

Plan note "07 - Fighter State Machine and Move Data". Importing this package registers every
state in :data:`STATES`; :func:`change_state` is the only way a fighter changes state.
"""

from isofightr.sim.states import air, ground, respawn
from isofightr.sim.states.base import STATES, State, change_state

__all__ = ["STATES", "State", "air", "change_state", "ground", "respawn"]
