"""Scripted "cheap strategy" players the CPU is measured against (decision D-071).

Plan note "15 - CPU AI" ("Tuning and proof"). A person who finds one thing that works on a
CPU repeats it: a down tilt, a grab, a held shield, an orb from across the stage. Each bot
here is that person: it gets within reach, faces the nearest opponent and does its one thing
again and again. ``tools/cpu_report.py`` plays the CPU against them; a good CPU makes each of
them land little and lose.

A bot is not a CPU. It reads the live match directly (it never changes it), has no reaction
delay and no dice, and so plays the same way whatever the CPU under test becomes. Only when
it is in trouble (launched, grabbed, lying down, hanging from a ledge, off the stage) does it
hand the stick to a frozen M10 CPU (:mod:`isofightr.ai.classic`) of middling level, so that
it techs, gets up and recovers about as an average player would.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Final, Protocol

from isofightr.ai.classic import ClassicCpu
from isofightr.ai.classic.knowledge import Step, frames_for, knowledge_for
from isofightr.ai.classic.terrain import level_ground_ahead, over_ground
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, InputFrame, facing_from_move
from isofightr.sim.match import Match
from isofightr.sim.math3d import Vec2
from isofightr.sim.stage import Stage

RESCUE_LEVEL: Final[int] = 5
"""Level of the frozen CPU that plays a bot's hurt and off-stage moments."""
TURN_TILT: Final[float] = 0.3
"""A light push that turns a standing fighter without walking it."""
EDGE_LOOKAHEAD: Final[float] = 1.2
"""A bot only runs on while there is level ground this far ahead."""
SHIELD_RANGE: Final[float] = 3.0
"""The shield holder raises its shield when an opponent is this close."""
SHIELD_REST_HP: Final[float] = 12.0
"""It lets a shield smaller than this recover instead of holding it until it breaks."""
WALK_IN: Final[float] = 1.5
"""Within this distance of its reach a bot walks instead of running, so it arrives standing."""
WALK_TILT: Final[float] = 0.55
MOVING_STATES: Final[frozenset[StateId]] = frozenset(
    {StateId.IDLE, StateId.WALK, StateId.DASH, StateId.RUN, StateId.CROUCH}
)
"""Grounded states a bot steers in."""
START_STATES: Final[frozenset[StateId]] = frozenset({StateId.IDLE, StateId.WALK, StateId.CROUCH})
"""States a bot starts its move from: never a dash or a run, where the same buttons would
give a dash attack or a dash grab instead of the move it is meant to repeat."""
HURT_STATES: Final[frozenset[StateId]] = frozenset(
    {
        StateId.GRABBED,
        StateId.TUMBLE,
        StateId.FLINCH,
        StateId.KNOCKDOWN,
        StateId.LEDGE_HANG,
        StateId.HELPLESS,
    }
)
"""States in which a bot lets the frozen CPU play for it."""


class Brain(Protocol):
    """Anything that plays a fighter: a CPU or a bot."""

    def think(self, match: Match, world: Any = None) -> InputFrame:
        """Return this tick's input. Never changes the match. ``world`` is a snapshot the
        caller already took, for the brains that use one."""
        ...


@dataclass(frozen=True, slots=True)
class BotDef:
    """One cheap strategy: who plays it, what it repeats and from how far."""

    name: str
    character: str
    action: str
    """A recorded action of :mod:`isofightr.ai.classic.knowledge` ("" = hold shield)."""
    reach: float
    """It acts once the nearest opponent is within this many units."""
    approach: bool = True
    """Whether it runs at an opponent that is out of reach (a zoner stays where it is)."""
    what: str = ""
    """A few words for the report."""


BOTS: Final[tuple[BotDef, ...]] = (
    BotDef("fsmash", "rook", "fsmash", 2.2, what="walks up and forward smashes"),
    BotDef("heavy_fsmash", "bramble", "fsmash", 2.4, what="Bramble's armoured forward smash"),
    BotDef("jab", "rook", "jab", 1.2, what="walks up and jabs"),
    BotDef("dtilt", "rook", "dtilt", 1.5, what="walks up and down tilts"),
    BotDef("dash_attack", "zephyr", "dash_attack", 3.0, what="Zephyr's dash attack"),
    BotDef("sh_fair", "rook", "sh_fair", 2.0, what="short-hop forward air"),
    BotDef("grab", "rook", "grab", 1.1, what="walks up, grabs, throws forward"),
    BotDef("dash_grab", "rook", "dash_grab", 2.4, what="dash grab, throws forward"),
    BotDef("counter", "rook", "dspecial", 2.2, what="Rook's Riposte whenever someone is near"),
    BotDef("orb", "mote", "nspecial", 9.0, approach=False, what="Mote's Ember Orb from afar"),
    BotDef("lamp", "mote", "sspecial", 7.0, approach=False, what="Mote's Orbit Lamp from afar"),
    BotDef("shield", "rook", "", SHIELD_RANGE, approach=False, what="holds shield when close"),
)
"""Every bot, in the order the report lists them."""
ONE_BUTTON: Final[tuple[str, ...]] = ("fsmash", "jab", "dtilt", "dash_attack", "sh_fair", "grab")
"""The bots a new player could be: the low levels are measured against these."""


def bot_def(name: str) -> BotDef:
    """Return a bot's definition by name."""
    for definition in BOTS:
        if definition.name == name:
            return definition
    raise KeyError(f"no bot named {name!r} (known: {', '.join(d.name for d in BOTS)})")


def nearest_opponent(match: Match, me: Fighter) -> Fighter | None:
    """The closest fighter still in play that is not ``me`` or on its team."""
    best: Fighter | None = None
    best_distance = float("inf")
    for other in match.fighters:
        if other is me or not other.in_play or me.allied_with(other):
            continue
        distance = (other.pos - me.pos).length()
        if distance < best_distance:
            best, best_distance = other, distance
    return best


class ScriptedBot:
    """One cheap strategy at the controls. Call :meth:`think` once per tick."""

    def __init__(self, definition: BotDef, player_index: int, seed: int, stage: Stage) -> None:
        self.definition = definition
        self.player = player_index
        self.seed = seed
        self.stage = stage
        self.queue: deque[InputFrame] = deque()
        self._steps: tuple[Step, ...] | None = None
        self._rescue: ClassicCpu | None = None
        self._rescues = 0

    def think(self, match: Match, world: object = None) -> InputFrame:
        """Return this tick's input. Never changes the match."""
        me = match.fighters[self.player]
        if not me.in_play:
            self.queue.clear()
            self._rescue = None
            return NEUTRAL_INPUT
        if self._in_trouble(match, me):
            return self._rescued(match)
        self._rescue = None
        if self.queue:
            return self.queue.popleft()
        foe = nearest_opponent(match, me)
        if foe is None:
            return NEUTRAL_INPUT
        if me.state is StateId.GRAB_HOLD:
            # Throws need a stick flick: one neutral frame, then forward.
            self.queue.extend([InputFrame(move=me.facing.world), NEUTRAL_INPUT])
            return NEUTRAL_INPUT
        if not self.definition.action:
            return self._hold_shield(me, foe)
        if me.state not in MOVING_STATES:
            return NEUTRAL_INPUT
        return self._repeat(match, me, foe)

    def _in_trouble(self, match: Match, me: Fighter) -> bool:
        if me.hitlag > 0 and me.launch is not None:
            return True
        if me.state in HURT_STATES:
            return True
        return not me.grounded and not over_ground(match.stage, me.pos)

    def _rescued(self, match: Match) -> InputFrame:
        """Let a frozen CPU play this moment; a fresh one each time, so nothing it planned
        while the bot was at the controls leaks in."""
        if self._rescue is None:
            self.queue.clear()
            self._rescues += 1
            seed = self.seed * 131 + self._rescues
            self._rescue = ClassicCpu(self.player, RESCUE_LEVEL, seed, self.stage)
        return self._rescue.think(match)

    def _hold_shield(self, me: Fighter, foe: Fighter) -> InputFrame:
        close = (foe.pos - me.pos).length() < self.definition.reach
        if close and me.grounded and me.shield_hp > SHIELD_REST_HP:
            return InputFrame(held=int(Button.SHIELD))
        return NEUTRAL_INPUT

    def _repeat(self, match: Match, me: Fighter, foe: Fighter) -> InputFrame:
        delta = foe.pos.xy - me.pos.xy
        distance = delta.length()
        if distance == 0.0:
            return NEUTRAL_INPUT
        direction = delta.normalized()
        if distance > self.definition.reach:
            if not self.definition.approach:
                return self._turn(me, direction) or NEUTRAL_INPUT
            if level_ground_ahead(match.stage, me.pos, direction, EDGE_LOOKAHEAD):
                near = distance <= self.definition.reach + WALK_IN
                return InputFrame(move=direction * (WALK_TILT if near else 1.0))
            return NEUTRAL_INPUT
        if me.state not in START_STATES:
            return NEUTRAL_INPUT  # let the run stop first
        turn = self._turn(me, direction)
        if turn is not None:
            return turn
        if self._steps is None:
            self._steps = knowledge_for(me.character).action(self.definition.action).steps
        self.queue.extend(frames_for(self._steps, me.facing.world))
        self.queue.append(NEUTRAL_INPUT)
        # A neutral frame first, so the press is fresh.
        return NEUTRAL_INPUT

    @staticmethod
    def _turn(me: Fighter, direction: Vec2) -> InputFrame | None:
        """A light push toward ``direction`` if the fighter faces another way."""
        wanted = facing_from_move(direction)
        if wanted is None or wanted is me.facing:
            return None
        return InputFrame(move=wanted.world * TURN_TILT)


def make_bot(name: str, player_index: int, seed: int, stage: Stage) -> ScriptedBot:
    """Build the bot called ``name`` for a player slot."""
    return ScriptedBot(bot_def(name), player_index, seed, stage)
