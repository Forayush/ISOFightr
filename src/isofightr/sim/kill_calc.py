"""Works out at what percent a move KOs, by running the real sim.

Plan note "16 - Testing Debug and Tooling" (``kill_calc.py``). The attacker performs the move
on a target standing in front of it that never touches the controls (no DI, no recovery).
A hit "kills" when the target crosses a side or top blast zone, or the bottom one while
still in hitstun: falling off the stage afterwards does not count, since a real player would
recover from that.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from isofightr.sim.character_def import CharacterDef
from isofightr.sim.events import KoEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import Stage
from isofightr.sim.states.interrupts import start_move

MAX_TICKS = 600
MAX_PERCENT = 300
SETTLE_TICKS = 120
"""After this many ticks, a target standing idle again has clearly survived."""
DEFAULT_GAP = 0.9
"""Distance between attacker and target, in units: inside the sweet spot of most moves."""


def move_kills(
    stage: Stage,
    attacker: CharacterDef,
    target: CharacterDef,
    move_id: str,
    percent: float,
    position: Vec2 | None = None,
    facing: Dir8 = Dir8.SE,
    gap: float = DEFAULT_GAP,
) -> bool:
    """Return whether ``move_id`` KOs a target at ``percent`` (see the module docstring).

    ``position`` is where the target stands (default: the stage's respawn point); the
    attacker stands ``gap`` units behind it, facing it.
    """
    match = Match.create(stage, [attacker, target], rules=MatchRules(stocks=None))
    striker, victim = match.fighters
    spot = stage.respawn if position is None else position
    top = stage.surface_top(spot.x, spot.y)
    assert top is not None, "the target must stand on solid ground"
    victim.pos = Vec3(spot.x, spot.y, top)
    victim.damage = percent
    behind = spot - facing.world * gap
    striker.pos = Vec3(behind.x, behind.y, top)
    striker.facing = facing
    start_move(match, striker, move_id)

    for _ in range(MAX_TICKS):
        stunned = victim.hitstun > 0 or victim.hitlag > 0
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        for event in match.events:
            if isinstance(event, KoEvent) and event.player == victim.player_index:
                return event.normal.z >= 0.0 or stunned
        if victim.state is StateId.IDLE and match.frame > SETTLE_TICKS:
            return False
    return False


def kill_percent(
    stage: Stage,
    attacker: CharacterDef,
    target: CharacterDef,
    move_id: str,
    position: Vec2 | None = None,
    facing: Dir8 = Dir8.SE,
) -> int | None:
    """Return the lowest whole percent at which the move KOs, or ``None`` if it never does."""
    low, high = 0, MAX_PERCENT
    if not move_kills(stage, attacker, target, move_id, high, position, facing):
        return None
    while low < high:
        middle = (low + high) // 2
        if move_kills(stage, attacker, target, move_id, middle, position, facing):
            high = middle
        else:
            low = middle + 1
    return low
