"""The CPU opponent: sees the match a little late, weighs what it could do, acts through
inputs.

Plan note "15 - CPU AI" and decision D-071 (M20). Three layers:

1. **Perception.** Each tick the CPU takes (or is handed) a :class:`~isofightr.ai.view.
   WorldView` and updates its :class:`~isofightr.ai.belief.Beliefs`: where an opponent is, it
   tracks almost at once; what an opponent has just started, it notices a reaction time
   later. It knows its own state as it is now.
2. **Decision.** Situations that only concern itself (being launched, tumbling, lying down,
   hanging from a ledge, being grabbed, holding someone, being off the stage) are handled
   every frame, still by the M10 rules (M20 groups 3 and 4 replace them). In neutral it
   re-plans every ``decision_frames``: it predicts where its target can be
   (:mod:`isofightr.ai.predict`), searches everything it could do, with or without a run-up
   (:mod:`isofightr.ai.intercept`), and does the best of what is worth doing. If nothing is,
   it takes up a distance: just outside the opponent's quick reach, never standing still.
3. **Execution.** Attacks and other multi-frame inputs are queued as ``InputFrame``s built
   from the recorded recipe of each action (:mod:`isofightr.ai.knowledge`), with a release
   frame first whenever a press would otherwise not be fresh. A run-up is called off if its
   target is not where it was expected.

A CPU only ever returns ``InputFrame``s, so replays record it like any player, and all its
randomness comes from its own seeded :class:`~isofightr.sim.rng.Rng`: the same match seed
gives the same CPU every time.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import chain
from typing import Final, NamedTuple

from isofightr import config
from isofightr.ai import advantage, crowd, disadvantage, habits, intercept, predict
from isofightr.ai.belief import Beliefs
from isofightr.ai.knowledge import Action, CharacterKnowledge, Start, frames_for, knowledge_for
from isofightr.ai.levels import CpuLevel, cpu_level
from isofightr.ai.situation import Situation, Standing, classify
from isofightr.ai.style import RANGE_OFFSET, Style, style_for
from isofightr.ai.terrain import (
    ground_below,
    level_ground_ahead,
    over_ground,
    recovery_ledge,
    region_of,
    route,
    safe_spot,
)
from isofightr.ai.view import FighterView, HazardView, WorldView, observe
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import constants as combat
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import (
    NEUTRAL_INPUT,
    VERTICAL_DOWN,
    VERTICAL_NONE,
    VERTICAL_UP,
    Button,
    InputFrame,
    facing_from_move,
)
from isofightr.sim.match import Match
from isofightr.sim.math3d import ZERO2, Vec2, Vec3
from isofightr.sim.rng import Rng
from isofightr.sim.stage import Stage

SEED_SALT: Final[int] = 0x5EED_C0DE
"""Mixed into the match seed so a CPU's dice differ from the match's own RNG stream."""
PRESS_BUTTONS: Final[int] = (
    Button.ATTACK | Button.SPECIAL | Button.STRONG | Button.JUMP | Button.GRAB | Button.SHIELD
)
SHIELDING: Final[frozenset[StateId]] = frozenset(
    {StateId.SHIELD, StateId.SHIELD_STUN, StateId.SHIELD_DROP}
)
DOWNED: Final[frozenset[StateId]] = frozenset(
    {StateId.SHIELD_BREAK, StateId.DIZZY, StateId.KNOCKDOWN, StateId.HELPLESS}
)
"""Opponent states that leave it open for a while."""
IGNORED: Final[frozenset[StateId]] = frozenset({StateId.KO})
JUMP_PRESS_FRAMES: Final[int] = 10
"""Jump is held this long for a full hop toward higher ground or across a gap."""
PREDICT_LIMIT: Final[int] = 30
"""Motion is extrapolated at most this many frames ahead."""
STYLE_SALT: Final[int] = 0x057_11E5
"""Seeds each CPU's temperament apart from its other dice."""
BELIEF_SALT: Final[int] = 0x0B5E_12FE
"""Seeds the dice of the CPU's reaction times apart from its other dice."""
HELPLESS_ARRIVAL: Final[float] = 0.3
"""A helpless move must end at least this far inside the stage to be considered."""
TECH_ROLL_SHARE: Final[float] = 0.4
GRABBING: Final[frozenset[StateId]] = frozenset({StateId.GRAB, StateId.DASH_GRAB})
OUT_OF_SHIELD: Final[tuple[str, ...]] = ("grab", "usmash", "uspecial")
"""What a CPU can do straight out of its shield (the sim's own shield options)."""
THROW_KILL_PERCENT: Final[float] = 90.0
MAX_PUMMELS: Final[int] = 2
PUMMEL_EVERY: Final[int] = 12
BASIC_LEVEL: Final[int] = 2
"""Levels at or below this always take the plain options (ledge getup, neutral getup)."""
TARGET_REACHED: Final[float] = 0.3


class Threat(NamedTuple):
    """A hit (or grab) the CPU sees coming."""

    frames: int
    """Frames until it lands."""
    key: int
    """Identifies it, so each is judged once."""
    grab: bool
    """A grab: a shield does not stop it."""
    source: Vec3 | None
    """Where it comes from (the attacker or the projectile)."""


@dataclass(frozen=True, slots=True)
class Plan:
    """What a CPU decided, for debugging and tests."""

    kind: str
    detail: str = ""


def _segment_distance(point: Vec3, low: Vec3, high: Vec3) -> float:
    along = high - low
    length_squared = along.dot(along)
    t = (
        0.0
        if length_squared == 0.0
        else max(0.0, min(1.0, (point - low).dot(along) / length_squared))
    )
    return (point - (low + along * t)).length()


def _rotate(local: Vec3, forward: Vec2) -> Vec3:
    left = forward.perpendicular_left()
    return Vec3(
        local.x * forward.x + local.y * left.x,
        local.x * forward.y + local.y * left.y,
        local.z,
    )


class CpuController:
    """One CPU player. Call :meth:`think` once per tick, before the match ticks."""

    def __init__(self, player_index: int, level: int, seed: int, stage: Stage) -> None:
        self.player = player_index
        self.level: CpuLevel = cpu_level(level)
        self.rng = Rng.seeded((seed ^ SEED_SALT) * 31 + player_index)
        self.stage = stage
        self.live = stage
        """The stage on the current frame (``match.stage``): where its moving platforms are
        now. Routes are planned on ``stage``, where they rest and are left out (D-063)."""
        self.history: deque[WorldView] = deque(maxlen=self.level.tracking_frames + 1)
        self.beliefs = Beliefs(
            player_index,
            self.level.tracking_frames,
            self.level.reaction_frames,
            Rng.seeded((seed ^ BELIEF_SALT) * 31 + player_index),
        )
        self.characters: dict[int, CharacterDef] = {}
        self.habits = habits.Habits(player_index, self.level.adapt, stage.respawn)
        """What it has learned of its opponents this match (M20 group 5)."""
        self.own = habits.OwnMoves()
        self.style = Style()
        """Its style, resolved from its character on the first tick."""
        self._style_seed = (seed ^ STYLE_SALT) * 31 + player_index
        self._projectiles: dict[int, frozenset[str]] = {}
        """Each opponent's projectile move ids (to spot a projectile repeater)."""
        self.standing = Standing(Situation.NEUTRAL)
        """The situation the CPU last found itself in (for debugging and the trace)."""
        self._believed: WorldView | None = None
        self._focus: int | None = None
        self._last_attack = 0
        self._queued: tuple[Action, int] | None = None
        """The ground action whose inputs are queued, and the frame it was started on."""
        self._climb_blocked_until = 0
        self._edgeguard_ok = False
        """While choosing: the target is off the stage and this level may follow it."""
        self._own_air_jumps = 0
        """Until this frame it does not try to climb to an opponent on other ground."""
        self._their_attack: dict[int, int] = {}
        """The frame each opponent was last seen attacking (or grabbing)."""
        """The frame it last chose to attack: waiting makes it less patient."""
        self._sway = 0.0
        self._sway_until = 0
        self._committed: tuple[int, int, int, Vec3] | None = None
        """A run-up in progress: (frame the hit is due, frame the run ends, the target,
        where the target was expected to be)."""
        self.queue: deque[InputFrame] = deque()
        self.last = NEUTRAL_INPUT
        self.plan = Plan("idle")
        self.knowledge: dict[int, CharacterKnowledge] = {}
        self.gravity: dict[int, float] = {}
        self._next_decision = 0
        self._edge_lookahead = config.CPU_EDGE_LOOKAHEAD
        self._destination: Vec2 | None = None
        self._facing_target: Vec3 | None = None
        self._waypoint: Vec3 | None = None
        """Where the jump in progress should land."""
        self._move_goal: Vec3 | None = None
        """Where neutral movement is heading."""
        self._steer_goal: Vec3 | None = None
        """Where recovery is heading (kept apart so it never leaks into neutral)."""
        self._was_free = True
        self._previous_state = StateId.IDLE
        self._situation = 0
        """Frame the current own situation (state) began: per-situation dice are rolled once."""
        self._rolled: dict[str, float] = {}
        self._defended: set[tuple[int, int]] = set()
        self._shield_until = 0
        self._pummels_done = 0
        self._edgeguarding = False
        self._di: tuple[object, Vec2, int] | None = None
        """The launch the DI was chosen for, the stick and the modifier chosen."""

    # --- the tick ------------------------------------------------------------------------

    def think(self, match: Match, world: WorldView | None = None) -> InputFrame:
        """Look at the match and return this tick's input. Never changes the match.

        ``world`` is this tick's :func:`~isofightr.ai.view.observe` of the match, if the
        caller already took one (several CPUs in a match share it).
        """
        if not self.knowledge:
            for fighter in match.fighters:
                index = fighter.player_index
                self.knowledge[index] = knowledge_for(fighter.character)
                self.characters[index] = fighter.character
                self.gravity[index] = fighter.character.movement.gravity
                self._projectiles[index] = frozenset(
                    action.move_id
                    for action in self.knowledge[index].actions
                    if action.projectile and action.move_id
                )
                if index == self.player:
                    self.style = style_for(
                        fighter.character, self.knowledge[index], self._style_seed
                    )
                    stats = fighter.character.movement
                    skid = stats.run_speed * stats.run_speed / (2.0 * stats.traction)
                    self._edge_lookahead = max(
                        config.CPU_EDGE_LOOKAHEAD, skid + config.CPU_EDGE_MARGIN
                    )
        self.live = match.stage
        if world is None:
            world = observe(match)
        self.history.append(world)
        self.beliefs.update(self.history, self._focus)
        self.habits.observe(self.beliefs.views(), world.frame)
        for view in self.beliefs.views():
            if view.state in (StateId.ATTACK, StateId.GRAB, StateId.DASH_GRAB):
                self._their_attack[view.index] = world.frame
        self._believed = WorldView(
            frame=world.frame,
            playing=world.playing,
            fighters=self.beliefs.views(),
            projectiles=self.history[0].projectiles,
            hazards=world.hazards,
            platforms=world.platforms,
            time_left=world.time_left,
            sudden_death=world.sudden_death,
        )
        frame = self._decide(world)
        self.last = frame
        return frame

    def _seen(self) -> WorldView:
        """The world as the CPU believes it to be: its opponents where it tracks them, doing
        what it has had time to notice."""
        assert self._believed is not None
        return self._believed

    def _roll(self, key: str) -> float:
        """A die rolled once per situation (the same key returns the same value until the
        CPU's own state changes)."""
        if key not in self._rolled:
            self._rolled[key] = self.rng.random()
        return self._rolled[key]

    def _decide(self, world: WorldView) -> InputFrame:
        me = world.fighters[self.player]
        if me.state is not self._previous_state:
            self._previous_state = me.state
            self._situation = world.frame
            self._rolled.clear()
        if not world.playing or not me.in_play:
            self.queue.clear()
            return NEUTRAL_INPUT
        if me.hitstun > 0 or me.hitlag > 0:
            self._waypoint = self._destination = None
        if me.hitlag > 0 and me.launch is not None:
            self.queue.clear()
            return self._directional_influence(world, me)
        if me.state is StateId.GRABBED:
            self.queue.clear()
            return self._mash(world)
        if me.state in (StateId.TUMBLE, StateId.FLINCH) and me.hitstun > 0:
            self.queue.clear()
            return self._in_hitstun(me)
        if me.state is StateId.KNOCKDOWN:
            self.queue.clear()
            return self._get_up(world, me)
        if me.state is StateId.LEDGE_HANG:
            if not self.queue:
                self._ledge_option(world, me)
            return self._emit()
        if me.state is not StateId.GRAB_HOLD:
            self._pummels_done = 0
        elif not self.queue:
            self._throw(world, me)
        if self.queue and self._run_up_fails(world):
            self.queue.clear()
        if self.queue and self._queued is not None and not me.grounded:
            # A ground move whose inputs are still coming, and the fighter is in the air while
            # the recording still had it on its feet (it slid or ran off something): the rest
            # would come out as an aerial. Stop.
            action, started = self._queued
            if action.offset_at(world.frame - started).z <= config.CPU_FOOTED_HEIGHT:
                self.queue.clear()
                self._queued = None
        if self.queue:
            return self._emit()
        self._committed = None
        if me.state in SHIELDING:
            return self._shielding(world, me)
        if not me.grounded and not over_ground(self.live, me.pos):
            if self.plan.kind == "space" and self.plan.detail == "climb":
                # The way up it took dropped it over a gap: leave that climb for a while.
                self._climb_blocked_until = world.frame + config.CPU_CLIMB_RETRY_FRAMES
            return self._recover(me)
        if me.grounded:
            self._destination = None
            self._steer_goal = None
        if me.free and not self._was_free:
            self._next_decision = min(self._next_decision, world.frame)
        self._was_free = me.free
        if me.state is StateId.HELPLESS:
            return self._steer_air(me, self._steer_goal or self._move_goal)
        if not me.free:
            return self._hold_course(me)
        return self._neutral(world, me)

    def _emit(self) -> InputFrame:
        return self.queue.popleft() if self.queue else NEUTRAL_INPUT

    def _enqueue(self, frames: Sequence[InputFrame]) -> None:
        """Queue a sequence of inputs; a release frame first if a press would not be fresh."""
        if not frames:
            return
        first = frames[0]
        stale_press = (self.last.held & first.held & PRESS_BUTTONS) != 0
        stale_vertical = first.vertical != VERTICAL_NONE and self.last.vertical == first.vertical
        if stale_press or stale_vertical:
            self.queue.append(NEUTRAL_INPUT)
        self.queue.extend(frames)

    # --- aiming helpers ------------------------------------------------------------------

    def _jitter(self, direction: Vec2) -> Vec2:
        """Add the level's aiming error to a unit direction."""
        spread = self.level.aim_jitter_degrees
        if spread <= 0.0 or direction == ZERO2:
            return direction
        return direction.rotated((self.rng.random() * 2.0 - 1.0) * spread)

    def _predict(self, target: FighterView, frames: float) -> Vec3:
        """Where ``target`` will be ``frames`` after it was last seen."""
        t = min(frames, PREDICT_LIMIT)
        pos = target.pos + Vec3(target.vel.x * t, target.vel.y * t, 0.0)
        if target.grounded:
            return Vec3(pos.x, pos.y, target.pos.z)
        gravity = self.gravity.get(target.index, 0.0)
        z = target.pos.z + target.vel.z * t - 0.5 * gravity * t * t
        floor = ground_below(self.live, pos.x, pos.y, target.pos.z)
        return Vec3(pos.x, pos.y, max(z, floor) if floor is not None else z)

    @staticmethod
    def _hurt(fighter: FighterView, feet: Vec3) -> tuple[Vec3, Vec3, float]:
        """The fighter's hurtbox as it is now (crouching or not), standing on ``feet``."""
        box = fighter.hurtbox
        return (
            Vec3(feet.x, feet.y, feet.z + box.z0 + box.radius),
            Vec3(feet.x, feet.y, feet.z + box.z1 - box.radius),
            box.radius,
        )

    # --- self-centred situations ---------------------------------------------------------

    def _directional_influence(self, world: WorldView, me: FighterView) -> InputFrame:
        """In hitlag with a launch pending: every DI is flown by the forecast and the best
        held on the last frames (survive, end over the stage, far from the attacker); before
        that, from level ``CPU_SDI_LEVEL`` up, a flick every other frame SDIs out of a
        multi-hit (away from the attacker) or along the chosen DI (a strong hit)."""
        launch = me.launch
        assert launch is not None
        if self._roll("di") >= self.level.di_quality:
            return NEUTRAL_INPUT
        attacker = self._attacker(world, me)
        if self._di is None or self._di[0] != launch:
            stick, vertical = disadvantage.di_choice(
                self.live,
                launch,
                me.pos,
                me.grounded,
                self.characters[self.player],
                attacker.pos if attacker is not None else None,
            )
            self._di = (launch, stick, vertical)
        _, stick, vertical = self._di
        hold = InputFrame(move=stick, vertical=vertical if not me.grounded else VERTICAL_NONE)
        weak = launch.knockback < config.CPU_SDI_MAX_KB
        # The DI (and ASDI) is read on the last hitlag frame; a multi-hit's hitlag is only
        # two or three frames, so against one only that last frame is kept for it.
        if me.hitlag <= (1 if weak else 2) or self.level.level < config.CPU_SDI_LEVEL:
            return hold
        direction = stick
        if weak:
            direction = disadvantage.away_from(
                me.pos, attacker.pos if attacker is not None else None, stick
            )
        nudged = me.pos + Vec3(direction.x, direction.y, 0.0) * (combat.SDI_DISTANCE * me.hitlag)
        if me.grounded and not over_ground(self.live, nudged):
            direction = stick  # never SDI off the stage
        # A flick needs the stick back at rest between presses.
        return InputFrame(move=direction) if self.last.move == ZERO2 else NEUTRAL_INPUT

    def _attacker(self, world: WorldView, me: FighterView) -> FighterView | None:
        """Who hit the CPU: an opponent frozen in hitlag with it (no launch of its own),
        else the nearest opponent."""
        best: FighterView | None = None
        best_distance = math.inf
        frozen = False
        for other in world.fighters:
            if other.index == self.player or not other.in_play:
                continue
            if me.team >= 0 and other.team == me.team:
                continue
            striker = other.hitlag > 0 and other.launch is None
            distance = (other.pos - me.pos).length()
            if (striker and not frozen) or (striker == frozen and distance < best_distance):
                best, best_distance, frozen = other, distance, striker or frozen
        return best

    def _mash(self, world: WorldView) -> InputFrame:
        """Mash out of a grab: a fresh press every ``mash_every`` frames."""
        if (world.frame - self._situation) % self.level.mash_every == 0:
            return InputFrame(held=int(Button.ATTACK))
        return NEUTRAL_INPUT

    def _in_hitstun(self, me: FighterView) -> InputFrame:
        """Drift toward the stage, and tech a tumble landing if the dice allow."""
        toward = self.stage.respawn - me.pos.xy
        drift = toward.normalized() if toward.length() > 0.0 else ZERO2
        if me.state is not StateId.TUMBLE or me.grounded:
            return InputFrame(move=drift)
        if self._roll("tech") >= self.level.tech_chance or me.tech_lockout > 0:
            return InputFrame(move=drift)
        landing = self._frames_to_land(me)
        if landing is None or landing > config.CPU_TECH_PRESS_FRAMES or me.tech_window > 0:
            return InputFrame(move=drift)
        if self.level.level <= BASIC_LEVEL:
            roll = self._roll("tech_roll") < TECH_ROLL_SHARE
            return InputFrame(move=drift if roll else ZERO2, held=int(Button.SHIELD))
        # Tech in place, or roll away from an opponent waiting where the tumble comes down.
        floor = ground_below(self.live, me.pos.x, me.pos.y, me.pos.z)
        ahead = me.pos + Vec3(me.vel.x, me.vel.y, 0.0) * float(landing)
        spot = Vec3(ahead.x, ahead.y, floor if floor is not None else me.pos.z)
        opponent = self._target(self._seen(), me)
        reach = self.knowledge[opponent.index].strike_reach if opponent is not None else 0.0
        choice = disadvantage.tech_choice(spot, opponent, reach)
        roll_from: Vec3 | None = opponent.pos if opponent is not None else None
        for zone in crowd.danger_zones(self._seen().hazards):
            if crowd.inside(spot, zone, config.CPU_HAZARD_MARGIN):
                # A hazard about to strike where it lands: roll out of it, whoever waits.
                choice, roll_from = disadvantage.TECH_AWAY, zone.pos
                break
        self.plan = Plan("disadvantage", choice)
        if choice == disadvantage.TECH_IN_PLACE or roll_from is None:
            return InputFrame(held=int(Button.SHIELD))
        away = disadvantage.away_from(spot, roll_from, drift)
        if not over_ground(self.live, spot + Vec3(away.x, away.y, 0.0) * 1.5):
            away = away * -1.0  # rolling off nothing is no escape: roll past instead
        return InputFrame(move=away, held=int(Button.SHIELD))

    def _frames_to_land(self, me: FighterView) -> int | None:
        """Frames until a tumbling fighter reaches the ground below it, or ``None``."""
        floor = ground_below(self.live, me.pos.x, me.pos.y, me.pos.z)
        if floor is None:
            return None
        gravity = self.gravity[self.player] * combat.HITSTUN_GRAVITY_MULT
        z, vz = me.pos.z, me.vel.z
        for frame in range(1, PREDICT_LIMIT + 1):
            vz -= gravity
            z += vz
            if z <= floor:
                return frame
        return None

    def _get_up(self, world: WorldView, me: FighterView) -> InputFrame:
        """Lying down: stand, attack, or roll in or out, by where the opponent can punish."""
        if (world.frame - self._situation) % 2 == 1:
            return NEUTRAL_INPUT
        target = self._target(self._seen(), me)
        if self.level.level <= BASIC_LEVEL:
            return InputFrame(vertical=VERTICAL_UP)
        choice = self._option_choice(
            "getup", predict.getup_options(self.live, me, self.characters[self.player]), target
        )
        self.plan = Plan("disadvantage", f"getup {choice}")
        if choice == "attack":
            return InputFrame(held=int(Button.ATTACK))
        if choice in ("roll in", "roll out"):
            inward = self.stage.respawn - me.pos.xy
            if inward.length() > 0.0:
                inward = inward.normalized()
                return InputFrame(move=inward if choice == "roll in" else inward * -1.0)
        return InputFrame(vertical=VERTICAL_UP)

    def _option_choice(
        self, key: str, options: Sequence[predict.Option], target: FighterView | None
    ) -> str:
        """Pick among a getup or ledge menu by value (where the opponent can punish), at the
        level's temperature, once per situation."""
        theirs = self.knowledge.get(target.index) if target is not None else None
        speed = self.characters[target.index].movement.run_speed if target is not None else 0.0
        valued = disadvantage.option_values(options, target, theirs, speed)
        names = [name for name, _ in valued]
        values = [value for _, value in valued]
        return disadvantage.pick(names, values, self.level.temperature, self._roll(key))

    def _ledge_option(self, world: WorldView, me: FighterView) -> None:
        """Hanging: wait a little (releasing whatever was held), then pick a ledge option."""
        waited = world.frame - self._situation
        wait = int(self._roll("ledge_wait") * (self.level.ledge_wait_max + 1))
        if waited < max(wait, 2):
            self.queue.append(NEUTRAL_INPUT)
            return
        option = "getup"
        if self.level.level > BASIC_LEVEL:
            target = self._target(self._seen(), me)
            option = self._option_choice(
                "ledge_option",
                predict.ledge_options(self.live, me, self.characters[self.player]),
                target,
            )
        inward = self.stage.respawn - me.pos.xy
        inward = inward.normalized() if inward.length() > 0.0 else ZERO2
        press = {
            "getup": InputFrame(vertical=VERTICAL_UP),
            "jump": InputFrame(move=inward, held=int(Button.JUMP)),
            "attack": InputFrame(held=int(Button.ATTACK)),
            "roll": InputFrame(held=int(Button.SHIELD)),
        }[option]
        self.plan = Plan("ledge", option)
        self._enqueue([NEUTRAL_INPUT, press, NEUTRAL_INPUT])

    def _throw(self, world: WorldView, me: FighterView) -> None:
        """Holding someone: pummel a little while the throw would not KO, then throw: each
        throw in each direction is flown by the forecast and the best (a KO that survives DI,
        then one that does not, then one that sends the victim off the stage, then the most
        advantage) is picked at the level's temperature. Levels 1 and 2 throw at random."""
        victim = world.fighters[me.grab_partner] if me.grab_partner >= 0 else None
        if victim is None:
            return
        grabs = self.characters[self.player].grabs
        choices = advantage.throw_choices(
            self.live, me, grabs, victim, self.characters[victim.index]
        )
        kills = any(choice.kills_through_di for choice in choices)
        pummels = (
            0 if self.level.level <= BASIC_LEVEL else int(self._roll("pummels") * (MAX_PUMMELS + 1))
        )
        if self._pummels_done < pummels and not kills:
            self._pummels_done += 1
            self._enqueue([InputFrame(held=int(Button.ATTACK))] + [NEUTRAL_INPUT] * PUMMEL_EVERY)
            return
        if self.level.level <= BASIC_LEVEL:
            choice = choices[int(self._roll("throw") * len(choices))]
        else:
            choice = self._pick(choices)
        self.plan = Plan("throw", choice.name)
        if choice.vertical != VERTICAL_NONE:
            self._enqueue([NEUTRAL_INPUT, InputFrame(vertical=choice.vertical), NEUTRAL_INPUT])
        else:
            self._enqueue([NEUTRAL_INPUT, InputFrame(move=choice.heading)])

    def _pick(self, choices: list[advantage.ThrowChoice]) -> advantage.ThrowChoice:
        """Softmax over values at the level's temperature (choices are best first)."""
        top = choices[0].value
        scale = max(self.level.temperature, 1e-6)
        weights = [math.exp((choice.value - top) / scale) for choice in choices]
        mark = self.rng.random() * sum(weights)
        for choice, weight in zip(choices, weights, strict=True):
            if mark < weight:
                return choice
            mark -= weight
        return choices[0]

    def _shielding(self, world: WorldView, me: FighterView) -> InputFrame:
        """Keep the shield up until the threat has passed, then let go. Not while it drops:
        a shield held through the drop comes straight back up when the drop ends, and two
        CPUs facing each other then raised and dropped their shields forever.

        From the shield: the best of grab, up smash and up special out of shield if one is
        worth it; a spot dodge if a grab is coming; a roll away if the shield is worn and a
        hit is still coming (a small shield is not held)."""
        if me.state is StateId.SHIELD and self.level.level > BASIC_LEVEL:
            punish = self._out_of_shield(world, me)
            if punish is not None:
                return punish
            threat = self._threat(self._seen(), me, self.level.tracking_frames)
            if threat is not None and threat.grab:
                self.plan = Plan("defend", "spot dodge a grab")
                return self._press(InputFrame(held=int(Button.SHIELD), vertical=VERTICAL_DOWN))
            if threat is not None and me.shield_hp <= config.CPU_LOW_SHIELD:
                away = self._escape_direction(me, threat.source)
                if away is not None:
                    self.plan = Plan("defend", "roll from a worn shield")
                    return InputFrame(move=away, held=int(Button.SHIELD))
        if me.state is not StateId.SHIELD_STUN and world.frame >= self._shield_until:
            return NEUTRAL_INPUT
        return InputFrame(held=int(Button.SHIELD))

    def _out_of_shield(self, world: WorldView, me: FighterView) -> InputFrame | None:
        """The best punish straight out of the shield (grab, up smash, up special), weighed
        like any other choice, if one reaches surely and is worth doing."""
        target = self._target(self._seen(), me)
        if target is None or target.intangible or target.invincible:
            return None
        if self.last.held & (int(Button.GRAB) | int(Button.STRONG) | int(Button.SPECIAL)):
            return None
        reading = self._read(world, me, target, None)
        mine = self.knowledge[self.player]
        aim = me.facing.world
        best: tuple[float, str] | None = None
        for name in OUT_OF_SHIELD:
            try:
                action = mine.action(name)
            except KeyError:
                continue
            if action.grab and not target.grounded:
                continue
            frame, chance = intercept.connect(me, target, action, aim, reading.track)
            if chance < config.CPU_OUT_OF_SHIELD_CHANCE or not reading.track.sure(frame):
                continue
            if not self._safe(me, action, aim):
                continue
            value = intercept.weigh(reading, action, aim, frame, chance).value
            if value >= config.CPU_ACT_VALUE and (best is None or value > best[0]):
                best = (value, name)
        if best is None:
            return None
        name = best[1]
        self.plan = Plan("attack", f"{name} out of shield")
        self._last_attack = world.frame
        shield = int(Button.SHIELD)
        if name == "grab":
            return InputFrame(held=shield | int(Button.GRAB))
        button = Button.STRONG if name == "usmash" else Button.SPECIAL
        return self._press(InputFrame(held=shield | int(button), vertical=VERTICAL_UP))

    def _escape_direction(self, me: FighterView, source: Vec3 | None) -> Vec2 | None:
        """A direction away from ``source`` that keeps ground under a roll, else ``None``."""
        if source is None:
            return None
        away = disadvantage.away_from(me.pos, source, ZERO2)
        if away == ZERO2:
            return None
        roll = self.knowledge[self.player].utilities.get("roll_back")
        distance = max((abs(p.x) for p in roll.path), default=1.0) if roll else 1.0
        if not over_ground(self.live, me.pos + Vec3(away.x, away.y, 0.0) * (distance + 0.3)):
            return None
        return away

    def _hold_course(self, me: FighterView) -> InputFrame:
        """Busy (attacking, landing, dodging): keep drifting toward the goal in the air, and
        keep aiming the up special while it is still being steered."""
        if me.grounded:
            return NEUTRAL_INPUT
        goal = self._waypoint or self._move_goal
        if self._waypoint is None and goal is not None:
            # Drifting during a move in neutral: never toward a landing with no ground under it
            # (Bramble drifted into one of Ember Forge's pits after a short-hop aerial).
            ahead = me.pos + Vec3(me.vel.x, me.vel.y, 0.0) * float(config.CPU_DRIFT_LOOKAHEAD)
            if not over_ground(self.live, ahead) or not self._ground_between(me.pos, goal):
                here = over_ground(self.live, me.pos)
                goal = Vec3(me.pos.x, me.pos.y, me.pos.z) if here else None
                if goal is None:
                    home = self.stage.respawn
                    goal = Vec3(home.x, home.y, me.pos.z)
        return self._steer_air(me, goal)

    def _ground_between(self, start: Vec3, end: Vec3) -> bool:
        """Whether there is ground under every step of the straight way from ``start`` to
        ``end`` (at ``start``'s height): a place to go must not be across a gap."""
        delta = end.xy - start.xy
        steps = max(int(delta.length() / config.CPU_PATH_STEP), 1)
        for index in range(1, steps + 1):
            point = start.xy + delta * (index / steps)
            if ground_below(self.live, point.x, point.y, start.z + config.CPU_STEP_HEIGHT) is None:
                return False
        return True

    # --- recovery ------------------------------------------------------------------------

    def _recover(self, me: FighterView) -> InputFrame:
        """Off the stage: steer to a ledge, jump when low, up special when out of jumps."""
        knowledge = self.knowledge[self.player]
        rise = knowledge.up_special_rise * config.CPU_UPSPECIAL_SAFETY
        jumps = me.air_jumps_left * knowledge.air_jump_rise
        reach = me.pos.z + jumps + rise
        waypoint = self._waypoint
        if waypoint is not None and waypoint.z > reach:
            waypoint = self._waypoint = None  # out of reach now: just get back somewhere
        if waypoint is not None:
            on_platform = self.stage.surface_top(waypoint.x, waypoint.y) != waypoint.z
            if on_platform and (me.air_jumps_left > 0 or me.pos.z > waypoint.z):
                self.plan = Plan("move", "to platform")
                return self._air_move(me, waypoint)
            ledge = recovery_ledge(self.stage, waypoint, math.inf, None)
        else:
            ledge = recovery_ledge(
                self.stage, me.pos, reach, self._destination, self._ledge_guards(me)
            )
        if ledge is None:
            return NEUTRAL_INPUT
        below = me.pos.z < ledge.z - combat.LEDGE_Z_BELOW[0]
        steer = ledge.approach(below) - me.pos.xy
        direction = steer.normalized() if steer.length() > 0.0 else ZERO2
        self._steer_goal = Vec3(ledge.point.x, ledge.point.y, ledge.z)
        self.plan = Plan("recover")
        if not me.free:
            uspecial = knowledge.up_special
            steering = uspecial is not None and me.move_id == uspecial.move_id
            return InputFrame(move=direction, vertical=VERTICAL_UP if steering else VERTICAL_NONE)
        if not below:
            return InputFrame(move=direction)
        falling = me.vel.z <= 0.0
        late = self._roll("late_jump") < self.level.recovery_mixup
        jump_below = ledge.z - (knowledge.air_jump_rise * 0.5 if late else 0.3)
        if me.air_jumps_left > 0 and falling and me.pos.z < jump_below:
            self.plan = Plan("recover", "air jump")
            return self._press(InputFrame(move=direction, held=int(Button.JUMP)))
        distance = steer.length()
        last_chance = me.pos.z < ledge.z - rise
        in_range = distance <= knowledge.up_special_reach + config.CPU_LEDGE_APPROACH_OUT
        if falling and me.air_jumps_left == 0 and (in_range or last_chance):
            self.plan = Plan("recover", "up special")
            return self._press(
                InputFrame(move=direction, vertical=VERTICAL_UP, held=int(Button.SPECIAL))
            )
        return InputFrame(move=direction)

    def _ledge_guards(self, me: FighterView) -> list[Vec2]:
        """Opponents standing free on the stage, where a recovery should not head
        (from level 3 up)."""
        if self.level.level <= BASIC_LEVEL:
            return []
        guards = []
        for other in self._seen().fighters:
            if other.index == self.player or not other.in_play or not other.grounded:
                continue
            if me.team >= 0 and other.team == me.team:
                continue
            if other.state in DOWNED or other.state is StateId.KO:
                continue
            guards.append(other.pos.xy)
        return guards

    def _press(self, frame: InputFrame) -> InputFrame:
        """Return ``frame``, or a release frame first if its press would not be fresh."""
        if self.last.held & frame.held & PRESS_BUTTONS:
            return InputFrame(move=frame.move)
        if frame.vertical != VERTICAL_NONE and self.last.vertical == frame.vertical:
            return InputFrame(move=frame.move)
        return frame

    def _steer_air(self, me: FighterView, goal: Vec3 | None) -> InputFrame:
        if goal is None:
            return NEUTRAL_INPUT
        delta = goal.xy - me.pos.xy
        if delta.length() < TARGET_REACHED:
            return NEUTRAL_INPUT
        return InputFrame(move=delta.normalized())

    # --- neutral -------------------------------------------------------------------------

    def _target(self, seen: WorldView, me: FighterView) -> FighterView | None:
        """The opponent to fight: the cheapest by :func:`crowd.target_cost` (near, hurtable,
        at high percent, the leader, the one it was already fighting, not in a brawl)."""
        opponents = [
            other
            for other in seen.fighters
            if other.index != self.player
            and other.in_play
            and other.state not in IGNORED
            and not (me.team >= 0 and other.team == me.team)
        ]
        best: FighterView | None = None
        best_cost = math.inf
        timed = seen.time_left is not None and me.stocks is None  # a time match, not stocks
        for other in opponents:
            cost = crowd.target_cost(me, other, opponents, self._focus, timed)
            if cost < best_cost:
                best, best_cost = other, cost
        return best

    def _allies(self, me: FighterView) -> list[FighterView]:
        """Teammates in play (with friendly fire they can be hit)."""
        if me.team < 0:
            return []
        return [
            other
            for other in self._seen().fighters
            if other.index != self.player and other.in_play and other.team == me.team
        ]

    def _neutral(self, world: WorldView, me: FighterView) -> InputFrame:
        seen = self._seen()
        threat = self._threat(seen, me, self.level.tracking_frames, config.CPU_GUARD_HORIZON)
        if threat is not None and threat[0] <= config.CPU_GUARD_NOW:
            defended = self._defend(world, me, threat)
            if defended is not None:
                return defended
        target = self._target(seen, me)
        if target is None:
            self._move_goal = None
            self._focus = None
            self.standing = classify(me, None, None)
            return NEUTRAL_INPUT
        self._focus = target.index
        self._facing_target = target.pos
        if world.frame >= self._next_decision:
            reading = self._read(world, me, target, threat)
            off = not target.grounded and not over_ground(self.live, target.pos)
            self.standing = classify(me, target, reading.track, target_off_stage=off)
            ahead = self.standing.situation is Situation.ADVANTAGE
            # With the opponent open, every frame counts: look again at once.
            self._next_decision = world.frame + (1 if ahead else self.level.decision_frames)
            choice = self._choose(reading)
            if choice is not None:
                return self._attack(world, target, choice, reading)
            if threat is not None:
                # Nothing beats it to the punch: guard the hit that is on its way.
                defended = self._defend(world, me, threat)
                if defended is not None:
                    return defended
            self._move_goal = self._position(world, me, target, reading)
        if self._move_goal is None:
            self._move_goal = me.pos
        keep = self._keep_away(me)
        if keep is not None:
            self.plan = Plan("space", "give way")
            return self._move_toward(me, keep)
        zones = crowd.danger_zones(world.hazards)
        if zones:
            safer = self._out_of_hazards(me, self._move_goal, zones)
            if safer is not None:
                self.plan = Plan("space", "hazard")
                return self._move_toward(me, safer)
        return self._move_toward(me, self._move_goal)

    def _keep_away(self, me: FighterView) -> Vec3 | None:
        """A place away from an opponent that cannot be hit and stands within
        ``CPU_INVINCIBLE_KEEP`` (any opponent, not only the target: a respawned one may land
        next to the CPU while it fights someone else), or ``None``."""
        for other in self._seen().fighters:
            if other.index == self.player or not other.in_play or not other.invincible:
                continue
            if me.team >= 0 and other.team == me.team:
                continue
            away = me.pos.xy - other.pos.xy
            if away.length() > config.CPU_INVINCIBLE_KEEP:
                continue
            if away.length() == 0.0:
                away = me.facing.world * -1.0
            spot = other.pos.xy + away.normalized() * config.CPU_RESPECT_RANGE
            return safe_spot(self.stage, Vec3(spot.x, spot.y, me.pos.z), me.pos)
        return None

    def _out_of_hazards(
        self, me: FighterView, goal: Vec3, zones: Sequence[HazardView]
    ) -> Vec3 | None:
        """A goal outside the hazards that are about to hit, if the CPU or its goal is in
        one (``None`` if neither is, or no ground is out there)."""
        for point in (me.pos, goal):
            out = crowd.clear_of(point, zones)
            if out is None:
                continue
            floor = ground_below(self.live, out.x, out.y, point.z + config.CPU_STEP_HEIGHT)
            if floor is None:
                continue
            return Vec3(out.x, out.y, floor)
        return None

    def _read(
        self, world: WorldView, me: FighterView, target: FighterView, threat: Threat | None
    ) -> intercept.Reading:
        """Read the situation once for everything this decision weighs."""
        index = target.index
        theirs = self.knowledge[index]
        # Where the target is, the CPU sees a few frames late: start the track from then and
        # drop those frames, so that a launched or running target is where it is now.
        lead = round(self.level.tracking_frames * self.level.prediction)
        stale = replace(
            target,
            state_frame=max(target.state_frame - lead, 1),
            hitstun=target.hitstun + lead if target.hitstun > 0 else 0,
            hitlag=target.hitlag + lead if target.hitlag > 0 else 0,
        )
        ahead = predict.track(
            self.live, stale, self.characters[index], theirs, intercept.LOOKAHEAD + lead
        )
        track = predict.Track(ahead.points[lead:], ahead.spread[lead:], max(ahead.locked - lead, 0))
        their_action = None
        if target.state is StateId.ATTACK:
            table = theirs.ground_by_move if target.grounded else theirs.air_by_move
            their_action = (
                table.get(target.move_id)
                or theirs.ground_by_move.get(target.move_id)
                or theirs.air_by_move.get(target.move_id)
            )
        patience = config.CPU_PATIENCE_FRAMES * self.style.patience
        waited = (world.frame - self._last_attack) / patience
        urge = min(max(waited, 0.0), 1.0) * config.CPU_IMPATIENCE_VALUE
        return intercept.Reading(
            stage=self.live,
            me=me,
            target=target,
            track=track,
            character=self.characters[index],
            theirs=theirs,
            mine=self.knowledge[self.player],
            their_action=their_action,
            their_frame=(their_action.move_start + target.state_frame - 1 if their_action else 0),
            caution=(1.0 + me.damage / config.CPU_CAUTION_PERCENT) / max(self.style.risk, 0.1),
            urge=urge,
            threat_frames=threat[0] if threat is not None else 0,
            passive=min(
                max(
                    (world.frame - self._their_attack.get(index, 0)) / patience,
                    0.0,
                ),
                1.0,
            ),
        )

    def _choose(self, reading: intercept.Reading) -> intercept.Candidate | None:
        """The best of everything that could reach the target, if any of it is worth doing."""
        me, target = reading.me, reading.target
        off = not target.grounded and not over_ground(self.live, target.pos)
        self._edgeguard_ok = (
            off and self.level.edgeguard_depth > 0.0 and not self.style.stays_on_stage
        )
        self._own_air_jumps = self.characters[self.player].movement.air_jumps
        if target.invincible or (target.intangible and reading.track.locked == 0):
            return None
        eager = min(self.level.aggression * self.style.aggression, 1.0)
        if reading.track.locked == 0 and self.rng.random() >= eager:
            return None  # the lower levels let a free opponent be (until M20 group 7)
        knowledge = self.knowledge[self.player]
        # Run-ups and walk-ups are recorded from a standstill: from a run they go further.
        still = me.grounded and me.vel.xy.length() <= config.CPU_STILL_SPEED
        approaches = knowledge.approaches if still else ()
        actions = chain(knowledge.actions, knowledge.extras, approaches)
        zones = crowd.danger_zones(self._seen().hazards)

        def allowed(action: Action, aim: Vec2) -> bool:
            if not self._safe(me, action, aim):
                return False
            if not zones:
                return True
            # Never swing into a hazard that will be hitting while the move lasts (most of
            # the lightning hits on Storm Galleon landed during the CPU's own attacks).
            steps = range(0, action.commit + 1, config.CPU_PATH_CHECK)
            path = [(f, _rotate(action.offset_at(f), aim)) for f in steps]
            return not crowd.hit_during(me.pos, path, zones)

        found = intercept.search(reading, actions, allowed)
        found = [replace(c, value=c.value + self._flavour(c, target.index)) for c in found]
        allies = self._allies(me)
        if allies:
            found = [
                replace(
                    c,
                    value=c.value
                    - config.CPU_FRIENDLY_FIRE_COST * crowd.ally_risk(me, c.action, c.aim, allies),
                )
                for c in found
            ]
        return intercept.choose(found, self.level.temperature, self.rng.random())

    def _flavour(self, candidate: intercept.Candidate, target: int | None = None) -> float:
        """What its style, its target's habits and its own recent moves add to a
        candidate's value: grabs, projectiles and aerials by taste, grabs against an
        opponent seen shielding more than most, favourite and avoided moves, and less for a
        move it has just been using (so its play is no pattern)."""
        style = self.style
        action = candidate.action
        bonus = 0.0
        if action.grab:
            bonus += (style.grab_rate - 1.0) * config.CPU_STYLE_GRAB_VALUE
            if target is not None:
                prior = config.CPU_GUARD_GUESS
                shields = self.habits.guard(target, prior) - prior
                bonus += max(shields, 0.0) * config.CPU_HABIT_GRAB_VALUE
        if action.projectile:
            bonus += (style.zoning - 1.0) * config.CPU_STYLE_ZONING_VALUE
        if action.start is Start.AIR or action.name.startswith(("sh_", "fh_")):
            bonus += (style.air_bias - 1.0) * config.CPU_STYLE_AIR_VALUE
        if action.move_id in style.favourites:
            bonus += config.CPU_FAVOURITE_VALUE
        if action.move_id in style.avoid:
            bonus -= config.CPU_FAVOURITE_VALUE
        repeat = self.own.share(action.move_id or action.name) * config.CPU_REPEAT_PENALTY
        return bonus * candidate.chance - repeat

    def _zoner(self, index: int) -> bool:
        """Whether that opponent has been repeating its projectiles (as far as it trusts).
        Not acted on yet: rushing such an opponent down ran the CPU into the projectiles
        (the orb bot landed 27% instead of 21%); jumping them on the way in is for later."""
        moves = self._projectiles.get(index, frozenset())
        return bool(moves) and self.habits.share(index, moves) >= config.CPU_HABIT_ZONER_SHARE

    def _attack(
        self,
        world: WorldView,
        target: FighterView,
        choice: intercept.Candidate,
        reading: intercept.Reading,
    ) -> InputFrame:
        """Start the chosen action; remember a run-up so it can be called off."""
        action = choice.action
        self.plan = Plan("attack", action.name)
        self._last_attack = world.frame
        self.own.used(action.move_id or action.name)
        self._enqueue(frames_for(action.steps, self._jitter(choice.aim)))
        self._queued = (action, world.frame) if action.start is Start.GROUND else None
        if action.lead > 0:
            expected, _spread = reading.track.at(choice.frame)
            self._committed = (
                world.frame + choice.frame,
                world.frame + action.lead,
                target.index,
                expected,
            )
        return self._emit()

    def _run_up_fails(self, world: WorldView) -> bool:
        """Whether the target of a run-up in progress is no longer where it was expected
        (looked at every few frames while the CPU is still running)."""
        committed = self._committed
        if committed is None:
            return False
        due, run_ends, index, expected = committed
        left = run_ends - world.frame
        if left <= 0:
            self._committed = None
            return False
        if left % 4:
            return False
        target = self._seen().fighters[index]
        frames = max(due - world.frame, 1)
        track = predict.track(
            self.live, target, self.characters[index], self.knowledge[index], frames
        )
        feet, _spread = track.at(frames)
        if target.in_play and (feet - expected).length() <= config.CPU_ABORT_DRIFT:
            return False
        self._committed = None
        self.plan = Plan("attack", "called off")
        return True

    def _position(
        self, world: WorldView, me: FighterView, target: FighterView, reading: intercept.Reading
    ) -> Vec3:
        """Where to stand when nothing is worth doing: just outside the opponent's quick
        reach (never quite still), on top of an opponent that is open, well away from one that
        cannot be hit, and at the ledge or in the middle when it is off the stage."""
        where = target.pos
        read = self._habit_spot(target)
        if read is not None:
            self.plan = Plan("advantage", f"read {read[1]}")
            return read[0]
        if target.state is StateId.LEDGE_HANG and not target.invincible:
            trap = advantage.ledge_trap_point(self.live, target)
            if trap is not None:
                self.plan = Plan("advantage", "ledge trap")
                return trap
        if reading.track.locked >= config.CPU_OPENING_FRAMES and not target.invincible:
            chase = advantage.chase_point(self.live, reading.track, me, config.CPU_CHASE_FRAMES)
            if chase is not None and self._ground_between(me.pos, chase):
                self.plan = Plan("advantage", "chase")
                return chase
        if not target.grounded and not over_ground(self.live, where):
            return self._goal(me, target, 0.0)
        away = me.pos.xy - where.xy
        distance = away.length()
        direction = away.normalized() if distance > 0.0 else me.facing.world * -1.0
        if target.invincible:
            self.plan = Plan("space", "give way")
            spot = where.xy + direction * config.CPU_RESPECT_RANGE
            return safe_spot(self.stage, Vec3(spot.x, spot.y, where.z), me.pos)
        if reading.track.locked >= config.CPU_OPENING_FRAMES:
            self.plan = Plan("space", "close in")
            return where
        if world.frame >= self._sway_until:
            low, high = config.CPU_SWAY
            self._sway = low + (high - low) * self.rng.random()
            short, long = config.CPU_SWAY_FRAMES
            self._sway_until = world.frame + short + int(self.rng.random() * (long - short))
        mine = self.knowledge[self.player]
        hover = reading.theirs.threat_reach + target.hurtbox.radius + config.CPU_HOVER_MARGIN
        hover = min(hover, config.CPU_HOVER_MAX)
        under = me.pos.z if me.grounded else ground_below(self.live, me.pos.x, me.pos.y, me.pos.z)
        level = abs(where.z - (me.pos.z if under is None else under)) <= config.CPU_ZONER_HEIGHT
        if not level and target.grounded and world.frame >= self._climb_blocked_until:
            # On other ground (a platform, a higher island): go there, by the route.
            self.plan = Plan("space", "climb")
            return where
        if not level and target.grounded:
            # A climb that failed a moment ago: wait on its own ground for the opponent.
            self.plan = Plan("space", "wait below")
            return me.pos
        if self.style.far and mine.projectile_reach >= config.CPU_ZONER_REACH and level:
            hover = max(hover, config.CPU_ZONER_RANGE)
        # A close style trims the margin, never into the opponent's own striking reach (there
        # every slow move would be beaten to the punch, and it only stood and waited).
        outside = reading.theirs.strike_reach + target.hurtbox.radius
        hover = max(hover + RANGE_OFFSET.get(self.style.range, 0.0), min(hover, outside))
        # The longer nothing has been worth doing, the closer it comes: an opponent that
        # never approaches must not stall the match (the shield bot did, forever).
        waited = (world.frame - self._last_attack) / (
            config.CPU_PATIENCE_FRAMES * self.style.patience
        )
        closing = min(max(waited - 1.0, 0.0), 1.0)
        jab = mine.action("jab").envelope
        reach = jab.radius if jab is not None else config.CPU_CLOSE_RANGE
        close = min(config.CPU_CLOSE_RANGE, reach + target.hurtbox.radius - config.CPU_CLOSE_INSIDE)
        hover -= closing * max(hover - close, 0.0)
        hover += self._sway * (1.0 - closing)
        if abs(distance - hover) <= config.CPU_HOVER_BAND and level:
            self.plan = Plan("space", "hold")
            return me.pos
        spot = where.xy + direction * hover
        floor = ground_below(self.live, spot.x, spot.y, where.z + config.CPU_STEP_HEIGHT)
        blocked = floor is None or abs(floor - me.pos.z) > config.CPU_STEP_HEIGHT
        if not blocked and floor is not None:
            blocked = not self._ground_between(me.pos, Vec3(spot.x, spot.y, floor))
        if distance < hover and blocked:
            # Nowhere to back off to: go at the opponent instead of waiting on the edge.
            self.plan = Plan("space", "cornered")
            return where
        self.plan = Plan("space", "back off" if distance < hover else "close in")
        if floor is None or blocked:
            return where
        return Vec3(spot.x, spot.y, floor)

    def _habit_spot(self, target: FighterView) -> tuple[Vec3, str] | None:
        """Where to wait for an opponent hanging from a ledge or lying down that has a habit
        there: just beyond where its usual roll or getup ends (from level 5)."""
        if target.invincible:
            return None
        if target.state is StateId.LEDGE_HANG:
            situation, menu = habits.LEDGE, predict.ledge_options
        elif target.state is StateId.KNOCKDOWN:
            situation, menu = habits.GETUP, predict.getup_options
        else:
            return None
        expected = self.habits.expected(target.index, situation)
        if expected is None or expected[0] in ("jump", "drop"):
            return None
        name = expected[0]
        for option in menu(self.live, target, self.characters[target.index]):
            if option.name != name:
                continue
            points = option.track.points
            end = points[min(max(option.free, 1), len(points)) - 1]
            inward = self.stage.respawn - end.xy
            if inward.length() > 0.0:
                inward = inward.normalized()
            spot = end.xy + inward * config.CPU_HABIT_STAND_OFF
            floor = ground_below(self.live, spot.x, spot.y, end.z + config.CPU_STEP_HEIGHT)
            if floor is None:
                return None
            return Vec3(spot.x, spot.y, floor), name
        return None

    # --- defence -------------------------------------------------------------------------

    def _threat(
        self,
        seen: WorldView,
        me: FighterView,
        delay: int,
        horizon: int = config.CPU_THREAT_FRAMES,
    ) -> Threat | None:
        """The soonest hit (or, on the ground, grab) the CPU can see coming at it within
        ``horizon`` frames, or ``None``."""
        if me.intangible:
            return None
        low, high, radius = self._hurt(me, me.pos)
        soonest: Threat | None = None
        for other in seen.fighters:
            if other.index == self.player or not other.in_play:
                continue
            if me.team >= 0 and other.team == me.team:
                continue
            knowledge = self.knowledge[other.index]
            action: Action | None = None
            if other.state is StateId.ATTACK:
                table = knowledge.ground_by_move if other.grounded else knowledge.air_by_move
                action = (
                    table.get(other.move_id)
                    or knowledge.ground_by_move.get(other.move_id)
                    or knowledge.air_by_move.get(other.move_id)
                )
            elif me.grounded and other.state in GRABBING:
                name = "dash_grab" if other.state is StateId.DASH_GRAB else "grab"
                action = next((a for a in knowledge.actions if a.name == name), None)
            if action is None:
                continue
            now = action.move_start + other.state_frame - 1  # a belief's count runs on
            here = action.offset_at(now)
            forward = other.facing.world
            for hit_frame in action.hit_frames:
                if hit_frame.frame <= now:
                    continue
                if hit_frame.frame > now + horizon:
                    break
                for sphere in hit_frame.spheres:
                    if sphere.grab and not me.grounded:
                        continue
                    centre = other.pos + _rotate(sphere.centre - here, forward)
                    reach = sphere.radius + radius + config.CPU_THREAT_SLACK
                    if _segment_distance(centre, low, high) <= reach:
                        frames = hit_frame.frame - now
                        key = (other.index, seen.frame - other.state_frame)
                        if soonest is None or frames < soonest.frames:
                            soonest = Threat(frames, hash(key), sphere.grab, other.pos)
                        break
        for projectile in seen.projectiles:
            if projectile.owner == self.player:
                continue
            for frame in range(1, horizon + 1):
                t = frame + delay
                centre = projectile.pos + projectile.vel * t
                if _segment_distance(centre, low, high) <= projectile.radius + radius:
                    if soonest is None or frame < soonest.frames:
                        shot = hash(("projectile", projectile.owner, seen.frame))
                        soonest = Threat(frame, shot, False, projectile.pos)
                    break
        return soonest

    def _defend(self, world: WorldView, me: FighterView, threat: Threat) -> InputFrame | None:
        """Deal with a hit (or grab) seen coming, if the level's dice say it reacts; each
        threat is judged once. In the air: air dodge. On the ground, the best of
        :func:`~isofightr.ai.disadvantage.defence_options`: shield a hit (not with a worn
        shield), spot dodge or jump away from a grab, roll away when that is all that is
        left."""
        frames, key, grab, source = threat
        if (self.player, key) in self._defended:
            return None
        if not me.grounded and (me.air_dodge_used or frames > config.CPU_AIR_DODGE_FRAMES):
            return None  # too soon to dodge in the air: look again nearer the hit
        self._defended.add((self.player, key))
        if self.rng.random() >= self.level.defend_chance:
            return None
        if me.grounded:
            options = disadvantage.defence_options(
                self.knowledge[self.player], frames, grab, me.shield_hp, 0
            )
            if self.level.level <= BASIC_LEVEL:
                options = [option for option in options if option.name == "shield"]
            for option in options:
                done = self._defend_with(world, me, option.name, frames, source)
                if done is not None:
                    return done
            return None
        self.plan = Plan("defend", "air dodge")
        return self._press(InputFrame(held=int(Button.SHIELD)))

    def _defend_with(
        self, world: WorldView, me: FighterView, name: str, frames: int, source: Vec3 | None
    ) -> InputFrame | None:
        """Start one defence (``None`` if it cannot be done from here)."""
        utilities = self.knowledge[self.player].utilities
        if name == "shield":
            self._shield_until = world.frame + frames + config.CPU_SHIELD_HOLD_EXTRA
            self.plan = Plan("defend", "shield")
            self.queue.clear()
            return InputFrame(held=int(Button.SHIELD))
        if name == "spot dodge":
            steps = utilities["spot_dodge"].steps
            self.queue.clear()
            self._enqueue(frames_for(steps, me.facing.world))
            self.plan = Plan("defend", "spot dodge")
            return self._emit()
        away = self._escape_direction(me, source)
        if name == "roll away" and away is not None:
            steps = utilities["roll_back"].steps
            self.queue.clear()
            self._enqueue(frames_for(steps, away * -1.0))
            self.plan = Plan("defend", "roll away")
            return self._emit()
        if name == "jump":
            self.queue.clear()
            self.plan = Plan("defend", "jump away")
            return self._press(InputFrame(move=away or ZERO2, held=int(Button.JUMP)))
        return None

    # --- attacking -----------------------------------------------------------------------

    def _safe(self, me: FighterView, action: Action, aim: Vec2) -> bool:
        """Whether an action keeps the CPU over ground (it never lunges off the stage), well
        inside the blast zone (a Zephyr high up once flew its up special out through the
        top), and, for a move that never leaves the ground, on the ground all the way."""
        drift = Vec3(me.vel.x, me.vel.y, 0.0) if action.start is Start.AIR else None
        zone = self.stage.blast_zone
        margin = config.CPU_BLAST_MARGIN
        on_ground = action.start is Start.GROUND
        for frame in range(config.CPU_PATH_CHECK, action.commit + 1, config.CPU_PATH_CHECK):
            point = me.pos + _rotate(action.offset_at(frame), aim)
            if drift is not None:
                point = point + drift * float(frame)
            if point.z > zone.z_max - margin or point.z < zone.z_min + margin:
                return False
            if not zone.x_min + margin < point.x < zone.x_max - margin:
                return False
            if not zone.y_min + margin < point.y < zone.y_max - margin:
                return False
            # Every frame its feet were on the ground in the recording must be over ground here
            # (a run-up into a short hop ran off an edge on Twin Isles before it jumped).
            footed = on_ground and action.offset_at(frame).z <= config.CPU_FOOTED_HEIGHT
            if footed and not over_ground(self.live, Vec3(point.x, point.y, me.pos.z)):
                return False
        end = me.pos + _rotate(action.offset_at(action.commit), aim)
        if drift is not None:
            end = end + drift * float(action.commit)
        if not over_ground(self.live, Vec3(end.x, end.y, me.pos.z + 1.0)):
            # Off the stage: only to edgeguard, only at the levels that do, never helpless,
            # and only if it can get back from where the action leaves it.
            if not self._edgeguard_ok or action.helpless:
                return False
            jumps = me.air_jumps_left if action.start is Start.AIR else self._own_air_jumps
            low = Vec3(end.x, end.y, min(end.z, me.pos.z + action.offset_at(action.commit).z))
            return advantage.can_return(self.live, low, jumps, self.knowledge[self.player])
        if action.helpless:
            inside = end.xy + (self.stage.respawn - end.xy).normalized() * HELPLESS_ARRIVAL
            # Probed from above, like the end: the recording's own landing height is where it
            # came down on the flat test stage, not anything here.
            return over_ground(self.live, Vec3(inside.x, inside.y, me.pos.z + 1.0))
        return True

    # --- movement ------------------------------------------------------------------------

    def _goal(self, me: FighterView, target: FighterView, lead: float) -> Vec3:
        """Where the CPU wants to be: near the target (at its preferred range), but never off
        the stage. With the target recovering, maybe at the ledge it is heading for."""
        where = self._predict(target, lead)
        if not target.grounded and not over_ground(self.live, where):
            self._edgeguarding = self._roll("edgeguard") < self.level.edgeguard_chance
            if not self._edgeguarding:
                return safe_spot(
                    self.stage, Vec3(self.stage.respawn.x, self.stage.respawn.y, me.pos.z), me.pos
                )
            return safe_spot(self.stage, where, me.pos)
        knowledge = self.knowledge[self.player]
        keep = config.CPU_CLOSE_RANGE
        away = me.pos.xy - where.xy
        zoner = knowledge.projectile_reach >= config.CPU_ZONER_REACH
        if zoner and abs(where.z - me.pos.z) <= config.CPU_ZONER_HEIGHT and away.length() > 0.0:
            line = facing_from_move(away) or me.facing
            spot = where.xy + line.world * config.CPU_ZONER_RANGE
            floor = ground_below(self.live, spot.x, spot.y, where.z)
            if floor is not None and abs(floor - where.z) <= config.CPU_STEP_HEIGHT:
                spot_region = region_of(self.stage, Vec3(spot.x, spot.y, floor))
                if spot_region is not None and spot_region == region_of(self.stage, where):
                    return Vec3(spot.x, spot.y, floor)
        if away.length() > keep:
            return where
        if away.length() == 0.0:
            return me.pos
        spot = where.xy + away.normalized() * keep
        return safe_spot(self.stage, Vec3(spot.x, spot.y, where.z), me.pos)

    def _move_toward(self, me: FighterView, goal: Vec3) -> InputFrame:
        """Walk, run, jump or drop toward ``goal``; never walk off an edge by accident."""
        if not me.grounded:
            return self._air_move(me, self._waypoint or goal)
        self._waypoint = None
        hop = self._next_hop(me, goal)
        if hop is not None:
            start, end = hop
            if (start.xy - me.pos.xy).length() > config.CPU_TAKEOFF_RADIUS:
                goal = start
            else:
                self._waypoint = end
                return self._leave_region(me, end)
        delta = goal.xy - me.pos.xy
        distance = delta.length()
        rise = goal.z - me.pos.z
        if distance < TARGET_REACHED and abs(rise) <= config.CPU_STEP_HEIGHT:
            self.plan = Plan("wait")
            return self._face(me)
        direction = self._jitter(delta.normalized()) if distance > 0.0 else ZERO2
        if (
            rise < -config.CPU_STEP_HEIGHT
            and me.on_platform
            and distance < config.CPU_WALK_RANGE
            and self._ground_under_platform(me)
        ):
            self.plan = Plan("move", "drop through")
            return self._press(InputFrame(vertical=VERTICAL_DOWN))
        knowledge = self.knowledge[self.player]
        if rise > config.CPU_STEP_HEIGHT and distance < config.CPU_WALK_RANGE * 2:
            # Keep where it means to land, so that if the jump takes it over a gap the
            # recovery carries on to it instead of turning back to the ledge (a floe at rest).
            self._waypoint = goal
            return self._jump_toward(me, goal, direction)
        if not level_ground_ahead(self.live, me.pos, direction, self._edge_lookahead):
            ahead = me.pos.xy + direction * self._edge_lookahead
            below = ground_below(self.live, ahead.x, ahead.y, me.pos.z)
            if (
                below is not None
                and below < me.pos.z
                and goal.z < me.pos.z - config.CPU_STEP_HEIGHT
            ):
                self.plan = Plan("move", "step down")
                return InputFrame(move=direction)
            reach = knowledge.full_hop_rise + knowledge.air_jump_rise
            if over_ground(self.live, goal) and distance <= reach + config.CPU_WALK_RANGE:
                return self._jump_toward(me, goal, direction)
            self.plan = Plan("wait", "edge")
            return NEUTRAL_INPUT
        self.plan = Plan("move", "approach")
        if distance < config.CPU_WALK_RANGE:
            return InputFrame(move=direction * config.CPU_WALK_TILT)
        return InputFrame(move=direction)

    def _next_hop(self, me: FighterView, goal: Vec3) -> tuple[Vec3, Vec3] | None:
        """If ``goal`` is on other ground, the takeoff and landing points of the first jump
        of the way there."""
        here = region_of(self.stage, me.pos)
        floor = ground_below(self.live, goal.x, goal.y, goal.z)
        if here is None or floor is None:
            return None
        there = region_of(self.stage, Vec3(goal.x, goal.y, floor))
        if there is None or there == here:
            return None
        knowledge = self.knowledge[self.player]
        reach = knowledge.jump_distance * config.CPU_JUMP_REACH_SHARE
        rise = (knowledge.full_hop_rise + knowledge.air_jump_rise) * config.CPU_JUMP_RISE_SHARE
        chain = route(self.stage, here, there, reach, rise)
        if not chain:
            # No way there on the jumps it trusts: stretch them before giving up (two Brambles
            # on Lily Pads waited on their own pads for whole matches). A jump that falls
            # short is a recovery like any other.
            stretched = knowledge.jump_distance * config.CPU_JUMP_REACH_STRETCH
            chain = route(self.stage, here, there, stretched, rise)
        if not chain:
            return None
        return chain[0].start, chain[0].end

    def _ground_under_platform(self, me: FighterView) -> bool:
        """Whether dropping through the platform here lands on something (a drifting bridge
        over a gap does not: Bramble dropped through Twin Isles' bridge into the gap)."""
        below = me.pos.z - config.CPU_STEP_HEIGHT
        return ground_below(self.live, me.pos.x, me.pos.y, below) is not None

    def _leave_region(self, me: FighterView, end: Vec3) -> InputFrame:
        """At a takeoff point: drop through the platform to lower ground, or jump."""
        delta = end.xy - me.pos.xy
        direction = delta.normalized() if delta.length() > 0.0 else ZERO2
        if (
            me.on_platform
            and end.z < me.pos.z - config.CPU_STEP_HEIGHT
            and self._ground_under_platform(me)
        ):
            self.plan = Plan("move", "drop through")
            self._enqueue([NEUTRAL_INPUT, InputFrame(vertical=VERTICAL_DOWN)])
            return self._emit()
        return self._jump_toward(me, end, direction)

    def _face(self, me: FighterView) -> InputFrame:
        """Standing at the goal: turn around if the target is behind."""
        if self._facing_target is None or not me.free:
            return NEUTRAL_INPUT
        toward = self._facing_target.xy - me.pos.xy
        wanted = facing_from_move(toward) if toward.length() > 0.0 else None
        if wanted is None or wanted is me.facing:
            return NEUTRAL_INPUT
        return InputFrame(move=wanted.world * config.CPU_TURN_TILT)

    def _jump_toward(self, me: FighterView, goal: Vec3, direction: Vec2) -> InputFrame:
        """A full hop toward higher ground or across a gap."""
        self.plan = Plan("move", "jump")
        self._destination = goal.xy
        frame = InputFrame(move=direction, held=int(Button.JUMP))
        self._enqueue([frame] * JUMP_PRESS_FRAMES)
        return self._emit()

    def _air_move(self, me: FighterView, goal: Vec3) -> InputFrame:
        """Drift toward ``goal``; air jump if it is above and the CPU is falling short."""
        delta = goal.xy - me.pos.xy
        direction = delta.normalized() if delta.length() > TARGET_REACHED else ZERO2
        if goal.z > me.pos.z + config.CPU_STEP_HEIGHT and me.vel.z <= 0.0 and me.air_jumps_left > 0:
            self.plan = Plan("move", "air jump")
            return self._press(InputFrame(move=direction, held=int(Button.JUMP)))
        return InputFrame(move=direction)
