"""The CPU opponent: sees the match a little late, decides by utility, acts through inputs.

Plan note "15 - CPU AI". Three layers:

1. **Perception.** Each tick the CPU copies the match into a :class:`~isofightr.ai.view.
   WorldView` and keeps a short history. It reads its opponents ``reaction_frames`` in the past
   (and extrapolates their motion by a level-dependent share of that delay); it knows its own
   state as it is now.
2. **Decision.** Situations that only concern itself (being launched, tumbling, lying down,
   hanging from a ledge, being grabbed, holding someone, being off the stage) are handled
   every frame. In neutral it re-plans every ``decision_frames``: defend against a hit it
   sees coming, punish end lag, attack with the move that best reaches the predicted target
   (scored by damage, KO potential and speed), or move: approach to its preferred range,
   jump to higher ground or across a gap, or guard the ledge.
3. **Execution.** Attacks and other multi-frame inputs are queued as ``InputFrame``s built
   from the recorded recipe of each action (:mod:`isofightr.ai.knowledge`), with a release
   frame first whenever a press would otherwise not be fresh.

A CPU only ever returns ``InputFrame``s, so replays record it like any player, and all its
randomness comes from its own seeded :class:`~isofightr.sim.rng.Rng`: the same match seed
gives the same CPU every time.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from isofightr import config
from isofightr.ai.knowledge import Action, CharacterKnowledge, Start, frames_for, knowledge_for
from isofightr.ai.levels import CpuLevel, cpu_level
from isofightr.ai.terrain import (
    ground_below,
    level_ground_ahead,
    over_ground,
    recovery_ledge,
    region_of,
    route,
    safe_spot,
)
from isofightr.ai.view import FighterView, WorldView, observe
from isofightr.sim.combat import constants as combat
from isofightr.sim.combat.knockback import knockback, launch_speed
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
LOOKAHEAD_LIMIT: Final[int] = 70
"""Hit frames later than this are not counted on when picking an attack."""
PREDICT_LIMIT: Final[int] = 30
"""Motion is extrapolated at most this many frames ahead."""
KILL_BONUS: Final[float] = 3.0
GRAB_SHIELD_BONUS: Final[float] = 2.5
SHIELDED_PENALTY: Final[float] = 0.35
LATE_PUNISH_PENALTY: Final[float] = 0.3
SPEED_SCALE: Final[float] = 12.0
"""A move whose hit comes this many frames later is worth half as much."""
HELPLESS_ARRIVAL: Final[float] = 0.3
"""A helpless move must end at least this far inside the stage to be considered."""
TECH_ROLL_SHARE: Final[float] = 0.4
LEDGE_OPTIONS: Final[tuple[tuple[str, float], ...]] = (
    ("getup", 0.35),
    ("jump", 0.25),
    ("attack", 0.2),
    ("roll", 0.2),
)
THROW_KILL_PERCENT: Final[float] = 90.0
MAX_PUMMELS: Final[int] = 2
PUMMEL_EVERY: Final[int] = 12
BASIC_LEVEL: Final[int] = 2
"""Levels at or below this always take the plain options (ledge getup, neutral getup)."""
TARGET_REACHED: Final[float] = 0.3


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
        self.history: deque[WorldView] = deque(maxlen=self.level.reaction_frames + 1)
        self.queue: deque[InputFrame] = deque()
        self.last = NEUTRAL_INPUT
        self.plan = Plan("idle")
        self.knowledge: dict[int, CharacterKnowledge] = {}
        self.hurtboxes: dict[int, tuple[float, float, float]] = {}
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
                box = fighter.character.body.hurtbox
                self.hurtboxes[index] = (box.z0, box.z1, box.radius)
                self.gravity[index] = fighter.character.movement.gravity
                if index == self.player:
                    stats = fighter.character.movement
                    skid = stats.run_speed * stats.run_speed / (2.0 * stats.traction)
                    self._edge_lookahead = max(
                        config.CPU_EDGE_LOOKAHEAD, skid + config.CPU_EDGE_MARGIN
                    )
        if world is None:
            world = observe(match)
        self.history.append(world)
        frame = self._decide(world)
        self.last = frame
        return frame

    def _seen(self) -> WorldView:
        """The world as the CPU perceives its opponents: ``reaction_frames`` ago."""
        return self.history[0]

    def _delay(self, now: WorldView) -> int:
        return now.frame - self._seen().frame

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
            return self._directional_influence(me)
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
        if self.queue:
            return self._emit()
        if me.state in SHIELDING:
            return self._shielding(world, me)
        if not me.grounded and not over_ground(self.stage, me.pos):
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
        floor = ground_below(self.stage, pos.x, pos.y, target.pos.z)
        return Vec3(pos.x, pos.y, max(z, floor) if floor is not None else z)

    def _hurt(self, index: int, feet: Vec3) -> tuple[Vec3, Vec3, float]:
        z0, z1, radius = self.hurtboxes[index]
        return (
            Vec3(feet.x, feet.y, feet.z + z0 + radius),
            Vec3(feet.x, feet.y, feet.z + z1 - radius),
            radius,
        )

    # --- self-centred situations ---------------------------------------------------------

    def _directional_influence(self, me: FighterView) -> InputFrame:
        """Hold the stick across the launch, toward the middle of the stage (survival DI)."""
        launch = me.launch
        assert launch is not None
        if self._roll("di") >= self.level.di_quality:
            return NEUTRAL_INPUT
        across = launch.heading.perpendicular_left()
        centre = self.stage.respawn - me.pos.xy
        if across.dot(centre) < 0.0:
            across = across * -1.0
        return InputFrame(move=across)

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
        roll = self._roll("tech_roll") < TECH_ROLL_SHARE
        return InputFrame(move=drift if roll else ZERO2, held=int(Button.SHIELD))

    def _frames_to_land(self, me: FighterView) -> int | None:
        """Frames until a tumbling fighter reaches the ground below it, or ``None``."""
        floor = ground_below(self.stage, me.pos.x, me.pos.y, me.pos.z)
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
        """Lying down: get up attacking if someone is close, roll, or stand up."""
        if (world.frame - self._situation) % 2 == 1:
            return NEUTRAL_INPUT
        target = self._target(self._seen(), me)
        near = target is not None and (target.pos - me.pos).length() < config.CPU_CLOSE_RANGE
        option = self._roll("getup")
        if self.level.level <= BASIC_LEVEL:
            return InputFrame(vertical=VERTICAL_UP)
        if near and option < 0.5:
            return InputFrame(held=int(Button.ATTACK))
        if option < 0.8:
            toward = self.stage.respawn - me.pos.xy
            if target is not None and option < 0.65:
                toward = me.pos.xy - target.pos.xy
            if toward.length() > 0.0:
                return InputFrame(move=toward.normalized())
        return InputFrame(vertical=VERTICAL_UP)

    def _ledge_option(self, world: WorldView, me: FighterView) -> None:
        """Hanging: wait a little (releasing whatever was held), then pick a ledge option."""
        waited = world.frame - self._situation
        wait = int(self._roll("ledge_wait") * (self.level.ledge_wait_max + 1))
        if waited < max(wait, 2):
            self.queue.append(NEUTRAL_INPUT)
            return
        option = "getup"
        if self.level.level > BASIC_LEVEL:
            die = self._roll("ledge_option")
            for name, share in LEDGE_OPTIONS:
                if die < share:
                    option = name
                    break
                die -= share
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
        """Holding someone: pummel a little, then throw toward the nearest edge for a KO,
        or down or up otherwise."""
        victim = world.fighters[me.grab_partner] if me.grab_partner >= 0 else None
        pummels = (
            0 if self.level.level <= BASIC_LEVEL else int(self._roll("pummels") * (MAX_PUMMELS + 1))
        )
        if self._pummels_done < pummels:
            self._pummels_done += 1
            self._enqueue([InputFrame(held=int(Button.ATTACK))] + [NEUTRAL_INPUT] * PUMMEL_EVERY)
            return
        if victim is not None and victim.damage >= THROW_KILL_PERCENT:
            ledge = recovery_ledge(self.stage, me.pos, math.inf, None)
            if ledge is not None:
                out = ledge.point - me.pos.xy
                if out.length() > 0.0:
                    self.plan = Plan("throw", "toward the edge")
                    self._enqueue([NEUTRAL_INPUT, InputFrame(move=out.normalized())])
                    return
        die = self._roll("throw")
        self.plan = Plan("throw", "down" if die < 0.6 else "up")
        vertical = VERTICAL_DOWN if die < 0.6 else VERTICAL_UP
        self._enqueue([NEUTRAL_INPUT, InputFrame(vertical=vertical), NEUTRAL_INPUT])

    def _shielding(self, world: WorldView, me: FighterView) -> InputFrame:
        """Keep the shield up until the threat has passed, then let go."""
        if me.state is StateId.SHIELD and world.frame >= self._shield_until:
            return NEUTRAL_INPUT
        return InputFrame(held=int(Button.SHIELD))

    def _hold_course(self, me: FighterView) -> InputFrame:
        """Busy (attacking, landing, dodging): keep drifting toward the goal in the air, and
        keep aiming the up special while it is still being steered."""
        if me.grounded:
            return NEUTRAL_INPUT
        return self._steer_air(me, self._waypoint or self._move_goal)

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
            ledge = recovery_ledge(self.stage, me.pos, reach, self._destination)
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
        """The opponent to fight: the nearest one still in play."""
        best: FighterView | None = None
        best_distance = math.inf
        for other in seen.fighters:
            if other.index == self.player or not other.in_play or other.state in IGNORED:
                continue
            if me.team >= 0 and other.team == me.team:
                continue
            distance = (other.pos - me.pos).length()
            if distance < best_distance:
                best, best_distance = other, distance
        return best

    def _neutral(self, world: WorldView, me: FighterView) -> InputFrame:
        seen = self._seen()
        delay = self._delay(world)
        threat = self._threat(seen, me, delay)
        if threat is not None:
            defended = self._defend(world, me, threat)
            if defended is not None:
                return defended
        target = self._target(seen, me)
        if target is None:
            self._move_goal = None
            return NEUTRAL_INPUT
        self._facing_target = target.pos
        if world.frame >= self._next_decision:
            self._next_decision = world.frame + self.level.decision_frames
            lead = delay * self.level.prediction
            choice = self._choose_attack(me, target, lead)
            if choice is not None:
                action, aim, _value = choice
                self.plan = Plan("attack", action.name)
                self._enqueue(frames_for(action.steps, aim))
                return self._emit()
            self._move_goal = self._goal(me, target, lead)
        if self._move_goal is None:
            self._move_goal = self._goal(me, target, delay * self.level.prediction)
        return self._move_toward(me, self._move_goal)

    # --- defence -------------------------------------------------------------------------

    def _threat(self, seen: WorldView, me: FighterView, delay: int) -> tuple[int, int] | None:
        """The soonest hit the CPU can see coming at it within ``CPU_THREAT_FRAMES``:
        (frames until it lands, a key identifying it), or ``None``."""
        if me.intangible:
            return None
        low, high, radius = self._hurt(self.player, me.pos)
        soonest: tuple[int, int] | None = None
        for other in seen.fighters:
            if other.index == self.player or not other.in_play or other.state is not StateId.ATTACK:
                continue
            if me.team >= 0 and other.team == me.team:
                continue
            knowledge = self.knowledge[other.index]
            table = knowledge.ground_by_move if other.grounded else knowledge.air_by_move
            action = (
                table.get(other.move_id)
                or knowledge.ground_by_move.get(other.move_id)
                or knowledge.air_by_move.get(other.move_id)
            )
            if action is None:
                continue
            now = action.move_start + other.state_frame - 1 + delay
            here = action.offset_at(now)
            forward = other.facing.world
            for hit_frame in action.hit_frames:
                if hit_frame.frame <= now:
                    continue
                if hit_frame.frame > now + config.CPU_THREAT_FRAMES:
                    break
                for sphere in hit_frame.spheres:
                    if sphere.grab:
                        continue
                    centre = other.pos + _rotate(sphere.centre - here, forward)
                    reach = sphere.radius + radius + config.CPU_THREAT_SLACK
                    if _segment_distance(centre, low, high) <= reach:
                        frames = hit_frame.frame - now
                        key = (other.index, seen.frame - other.state_frame)
                        if soonest is None or frames < soonest[0]:
                            soonest = (frames, hash(key))
                        break
        for projectile in seen.projectiles:
            if projectile.owner == self.player:
                continue
            for frame in range(1, config.CPU_THREAT_FRAMES + 1):
                t = frame + delay
                centre = projectile.pos + projectile.vel * t
                if _segment_distance(centre, low, high) <= projectile.radius + radius:
                    if soonest is None or frame < soonest[0]:
                        soonest = (frame, hash(("projectile", projectile.owner, seen.frame)))
                    break
        return soonest

    def _defend(
        self, world: WorldView, me: FighterView, threat: tuple[int, int]
    ) -> InputFrame | None:
        """Shield (on the ground) or air dodge (in the air) a hit seen coming, if the level's
        dice say it reacts. Each threat is judged once."""
        frames, key = threat
        if (self.player, key) in self._defended:
            return None
        self._defended.add((self.player, key))
        if self.rng.random() >= self.level.defend_chance:
            return None
        if me.grounded:
            self._shield_until = world.frame + frames + config.CPU_SHIELD_HOLD_EXTRA
            self.plan = Plan("defend", "shield")
            self.queue.clear()
            return InputFrame(held=int(Button.SHIELD))
        if not me.air_dodge_used and frames <= config.CPU_AIR_DODGE_FRAMES:
            self.plan = Plan("defend", "air dodge")
            return self._press(InputFrame(held=int(Button.SHIELD)))
        return None

    # --- attacking -----------------------------------------------------------------------

    def _choose_attack(
        self, me: FighterView, target: FighterView, lead: float
    ) -> tuple[Action, Vec2, float] | None:
        """The best action that reaches the target, if the CPU feels like attacking."""
        if target.intangible or target.invincible:
            return None
        lag = self._opening(target)
        if lag is None and self.rng.random() >= self.level.aggression:
            return None
        knowledge = self.knowledge[self.player]
        start = Start.GROUND if me.grounded else Start.AIR
        best: tuple[Action, Vec2, float] | None = None
        for action in knowledge.actions:
            if action.start is not start or not action.hit_frames:
                continue
            if action.grab and (not target.grounded or not me.grounded):
                continue
            aim = self._aim_for(me, target, action)
            if not self._safe(me, action, aim):
                continue
            frame = self._connects(me, target, action, aim, lead)
            if frame is None:
                continue
            value = self._value(action, target, frame, lag)
            if best is None or value > best[2]:
                best = (action, aim, value)
        return best

    def _opening(self, target: FighterView) -> int | None:
        """Frames the target is stuck for (end lag, landing lag, a broken shield), or
        ``None`` when it can act."""
        if target.state in DOWNED:
            return max(target.stun_frames, config.CPU_DOWNED_OPENING_FRAMES)
        if target.state is StateId.LAND and target.land_lag > 0:
            return max(target.land_lag - target.state_frame, 0)
        if target.state is StateId.ATTACK:
            action = self.knowledge[target.index].ground_by_move.get(target.move_id)
            if action is None:
                action = self.knowledge[target.index].air_by_move.get(target.move_id)
            if action is not None:
                now = action.move_start + target.state_frame - 1
                if now > action.last_hit:
                    return max(action.commit - now, 0)
        return None

    def _aim_for(self, me: FighterView, target: FighterView, action: Action) -> Vec2:
        """The facing an action would be performed with: toward the target for actions that
        turn, the current facing otherwise."""
        if not action.turns:
            return me.facing.world
        toward = target.pos.xy - me.pos.xy
        facing = facing_from_move(self._jitter(toward.normalized())) if toward.length() else None
        return (facing or me.facing).world

    def _safe(self, me: FighterView, action: Action, aim: Vec2) -> bool:
        """Whether an action keeps the CPU over ground (it never lunges off the stage)."""
        end = me.pos + _rotate(action.offset_at(action.commit), aim)
        if action.start is Start.AIR:
            end = end + Vec3(me.vel.x, me.vel.y, 0.0) * float(action.commit)
        if not over_ground(self.stage, Vec3(end.x, end.y, me.pos.z + 1.0)):
            return False
        if action.helpless:
            inside = end.xy + (self.stage.respawn - end.xy).normalized() * HELPLESS_ARRIVAL
            return over_ground(self.stage, Vec3(inside.x, inside.y, end.z))
        return True

    def _connects(
        self, me: FighterView, target: FighterView, action: Action, aim: Vec2, lead: float
    ) -> int | None:
        """The first action frame on which the action would hit the target, or ``None``."""
        drift = Vec3(me.vel.x, me.vel.y, me.vel.z) if action.start is Start.AIR else None
        slack = config.CPU_HIT_SLACK
        for hit_frame in action.hit_frames:
            frame = hit_frame.frame
            if frame > LOOKAHEAD_LIMIT:
                return None
            where = self._predict(target, lead + frame)
            low, high, radius = self._hurt(target.index, where)
            for sphere in hit_frame.spheres:
                if sphere.grab and not target.grounded:
                    continue
                centre = me.pos + _rotate(sphere.centre, aim)
                if drift is not None and not sphere.projectile:
                    centre = centre + drift * float(min(frame, PREDICT_LIMIT))
                if _segment_distance(centre, low, high) <= sphere.radius + radius + slack:
                    return frame
        return None

    def _value(self, action: Action, target: FighterView, frame: int, lag: int | None) -> float:
        """How good landing ``action`` on ``target`` at ``frame`` would be."""
        value = max(action.damage, 1.0)
        if self._kills(action, target):
            value *= 1.0 + KILL_BONUS
        if target.state in SHIELDING:
            value *= GRAB_SHIELD_BONUS if action.grab else SHIELDED_PENALTY
        value /= 1.0 + frame / SPEED_SCALE
        if lag is not None and frame + self.level.punish_margin > lag:
            value *= LATE_PUNISH_PENALTY
        noise = (config.CPU_MAX_LEVEL - self.level.level) / config.CPU_MAX_LEVEL
        return value * (1.0 + (self.rng.random() - 0.5) * noise)

    def _kills(self, action: Action, target: FighterView) -> bool:
        """Whether the action's strongest hit would carry the target past the blast zone."""
        box = action.strongest
        if box is None:
            return False
        percent = target.damage + box.damage
        kb = knockback(percent, box.damage, target.weight, box.bkb, box.kbg, box.fkb)
        speed = launch_speed(kb)
        travel = speed * speed / (2.0 * combat.KB_DECAY)
        zone = self.stage.blast_zone
        pos = target.pos
        nearest_side = min(
            pos.x - zone.x_min, zone.x_max - pos.x, pos.y - zone.y_min, zone.y_max - pos.y
        )
        return travel + config.CPU_KILL_HEADROOM >= nearest_side

    # --- movement ------------------------------------------------------------------------

    def _goal(self, me: FighterView, target: FighterView, lead: float) -> Vec3:
        """Where the CPU wants to be: near the target (at its preferred range), but never off
        the stage. With the target recovering, maybe at the ledge it is heading for."""
        where = self._predict(target, lead)
        if not target.grounded and not over_ground(self.stage, where):
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
            floor = ground_below(self.stage, spot.x, spot.y, where.z)
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
        if rise < -config.CPU_STEP_HEIGHT and me.on_platform and distance < config.CPU_WALK_RANGE:
            self.plan = Plan("move", "drop through")
            return self._press(InputFrame(vertical=VERTICAL_DOWN))
        knowledge = self.knowledge[self.player]
        if rise > config.CPU_STEP_HEIGHT and distance < config.CPU_WALK_RANGE * 2:
            return self._jump_toward(me, goal, direction)
        if not level_ground_ahead(self.stage, me.pos, direction, self._edge_lookahead):
            ahead = me.pos.xy + direction * self._edge_lookahead
            below = ground_below(self.stage, ahead.x, ahead.y, me.pos.z)
            if (
                below is not None
                and below < me.pos.z
                and goal.z < me.pos.z - config.CPU_STEP_HEIGHT
            ):
                self.plan = Plan("move", "step down")
                return InputFrame(move=direction)
            reach = knowledge.full_hop_rise + knowledge.air_jump_rise
            if over_ground(self.stage, goal) and distance <= reach + config.CPU_WALK_RANGE:
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
        floor = ground_below(self.stage, goal.x, goal.y, goal.z)
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
            return None
        return chain[0].start, chain[0].end

    def _leave_region(self, me: FighterView, end: Vec3) -> InputFrame:
        """At a takeoff point: drop through the platform to lower ground, or jump."""
        delta = end.xy - me.pos.xy
        direction = delta.normalized() if delta.length() > 0.0 else ZERO2
        if me.on_platform and end.z < me.pos.z - config.CPU_STEP_HEIGHT:
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
