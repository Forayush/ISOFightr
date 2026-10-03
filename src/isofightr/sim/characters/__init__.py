"""Special-move scripts: the only character-specific Python in the sim.

Plan note "07 - Fighter State Machine and Move Data": every move runs from data in the generic
``Attack`` state. A move may name a script (``script = "rook.side_special"``) to add logic that
data cannot express; the ``Attack`` state calls the script's hooks. One module per character
registers its scripts here.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isofightr.sim.fighter import Fighter
    from isofightr.sim.match import Match
    from isofightr.sim.projectile import Projectile


class MoveScript:
    """Hooks a move can override. Scripts hold no data: anything to remember is on the
    ``Fighter``."""

    def on_start(self, match: Match, fighter: Fighter) -> None:
        """Run on the move's frame 1, after the generic setup."""

    def on_frame(self, match: Match, fighter: Fighter) -> None:
        """Run on every later frame of the move, before the generic logic."""

    def motion(self, match: Match, fighter: Fighter) -> bool:
        """Set the fighter's velocity for this frame. Return ``True`` if the script handled
        it, ``False`` to fall back to the move's data-driven motion."""
        return False

    def on_projectile(self, match: Match, fighter: Fighter, projectile: Projectile) -> None:
        """Adjust a projectile the move just spawned (speed, lifetime, damage...)."""

    def on_land(self, match: Match, fighter: Fighter) -> bool:
        """React to landing during the move. Return ``True`` if the script handled it (for
        example by starting another move), ``False`` for the usual landing lag."""
        return False


SCRIPTS: dict[str, MoveScript] = {}
"""Every registered script, by name."""


def register_script(name: str, script: MoveScript) -> None:
    """Add a script under ``name`` (``"<character>.<move>"``)."""
    if name in SCRIPTS:
        raise ValueError(f"move script {name!r} is registered twice")
    SCRIPTS[name] = script


# Registered last, so the character modules can import the names above.
from isofightr.sim.characters import bramble, mote, rook, zephyr  # noqa: E402, F401
