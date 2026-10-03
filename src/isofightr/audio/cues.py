"""Which sound each thing that happens in a match makes.

Plan note "14 - Audio" ("Approach", "Mixing rules"). Audio is driven by the sim's events
(``match.events``), by what the fighters' states changed to since the last tick (swings,
dashes, shields, dodges and throws have no event), and by the countdown. This module only
decides *what* to play; :mod:`isofightr.audio.sound_director` plays it. The sim never knows.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from isofightr import config
from isofightr.sim import events as ev
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.match import Match
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect, MoveKind
from isofightr.sim.rules import MatchPhase

PUMMEL_MOVE = "pummel"
HIT_TIER_NAMES = ("hit_light", "hit_medium", "hit_heavy", "hit_ko")
SWING_BY_KIND: dict[MoveKind, str] = {
    MoveKind.JAB: "swing_light",
    MoveKind.TILT: "swing_light",
    MoveKind.DASH_ATTACK: "swing_medium",
    MoveKind.AERIAL: "swing_medium",
    MoveKind.RECOVERY: "swing_medium",
    MoveKind.SMASH: "swing_heavy",
    MoveKind.SPECIAL: "special",
}
STATE_SOUNDS: dict[StateId, str] = {
    StateId.DASH: "dash",
    StateId.SKID: "skid",
    StateId.RUN_TURN: "skid",
    StateId.PLATFORM_DROP: "platform_drop",
    StateId.SHIELD: "shield_up",
    StateId.SPOT_DODGE: "dodge",
    StateId.ROLL: "dodge",
    StateId.AIR_DODGE: "dodge",
    StateId.TECH_ROLL: "dodge",
    StateId.GETUP_ROLL: "dodge",
    StateId.LEDGE_ROLL: "dodge",
    StateId.GRAB: "swing_light",
    StateId.DASH_GRAB: "swing_light",
    StateId.THROW: "throw",
}
TICKS_PER_SECOND = config.TICK_RATE


@dataclass(frozen=True, slots=True)
class Cue:
    """One sound to play."""

    name: str
    position: Vec3 | None = None
    """Where it happened, for stereo pan (``None`` = centred)."""
    vary: bool = False
    """Vary the pitch a little (sounds that repeat a lot)."""
    duck: bool = False
    """Duck the music while it plays."""


def hit_sound(knockback: float, effect: Effect) -> str:
    """The hit sound for a knockback tier and element (plan note 14, "Hit SFX tier")."""
    tier = sum(knockback >= threshold for threshold in config.AUDIO_HIT_TIERS)
    name = HIT_TIER_NAMES[tier]
    return name if effect is Effect.NORMAL else f"{name}_{effect.value}"


def event_cues(events: Sequence[object]) -> list[Cue]:
    """The sounds of one tick's sim events."""
    cues: list[Cue] = []
    for event in events:
        if isinstance(event, ev.HitEvent):
            if event.move_id == PUMMEL_MOVE:
                cues.append(Cue("pummel", event.position, vary=True))
            else:
                name = hit_sound(event.knockback, event.effect)
                cues.append(Cue(name, event.position, vary=True))
        elif isinstance(event, ev.JumpEvent):
            name = "double_jump" if event.kind is ev.JumpKind.AIR else "jump"
            cues.append(Cue(name, event.position, vary=True))
        elif isinstance(event, ev.LandEvent):
            heavy = event.fall_speed >= config.AUDIO_HEAVY_LANDING_SPEED
            cues.append(Cue("land_heavy" if heavy else "land_light", event.position, vary=True))
        elif isinstance(event, ev.KoEvent):
            cues.append(Cue("ko_blast", event.position, duck=True))
        elif isinstance(event, ev.RespawnEvent):
            cues.append(Cue("respawn", event.position))
        elif isinstance(event, ev.ClankEvent):
            cues.append(Cue("clank", event.position, vary=True))
        elif isinstance(event, ev.ShieldHitEvent):
            cues.append(Cue("parry" if event.parried else "shield_hit", event.position, vary=True))
        elif isinstance(event, ev.ShieldBreakEvent):
            cues.append(Cue("shield_break", event.position))
        elif isinstance(event, ev.GrabEvent):
            cues.append(Cue("clank" if event.clash else "grab", event.position))
        elif isinstance(event, ev.LedgeGrabEvent):
            cues.append(Cue("ledge_grab", event.position))
        elif isinstance(event, ev.TechEvent):
            cues.append(Cue("tech", event.position))
        elif isinstance(event, ev.WallBounceEvent):
            cues.append(Cue("wall_bounce", event.position))
        elif isinstance(event, ev.ProjectileEvent):
            if event.spawned:
                cues.append(Cue("shoot", event.position, vary=True))
        elif isinstance(event, ev.ShockwaveEvent):
            cues.append(Cue("shockwave", event.position))
        elif isinstance(event, ev.CounterEvent):
            cues.append(Cue("counter", event.position))
        elif isinstance(event, ev.SuddenDeathEvent):
            cues.append(Cue("sudden_death"))
        elif isinstance(event, ev.MatchEndEvent):
            cues.append(Cue("game", duck=True))
    return cues


def _no_states() -> dict[int, tuple[StateId, str, int]]:
    return {}


@dataclass(slots=True)
class MatchSounds:
    """Remembers last tick's fighter states and countdown, to hear what changed."""

    seen: dict[int, tuple[StateId, str, int]] = field(default_factory=_no_states)
    """Per player: state, move id and state frame last tick."""
    countdown: int = 0
    phase: MatchPhase | None = None

    def observe(self, match: Match) -> list[Cue]:
        """Return the sounds of what changed since the last call (once per sim tick)."""
        cues = self._flow(match)
        for fighter in match.fighters:
            cues += self._fighter(fighter)
        return cues

    def reset(self) -> None:
        """Forget everything (a new match)."""
        self.seen = {}
        self.countdown = 0
        self.phase = None

    def _flow(self, match: Match) -> list[Cue]:
        cues: list[Cue] = []
        if match.phase is MatchPhase.COUNTDOWN:
            # One beep as each second of the countdown begins ("3", "2", "1").
            second = -(-match.countdown // TICKS_PER_SECOND)
            before = -(-self.countdown // TICKS_PER_SECOND)
            if match.countdown > 0 and (self.phase is not MatchPhase.COUNTDOWN or second < before):
                cues.append(Cue("countdown"))
        elif self.phase is MatchPhase.COUNTDOWN and match.phase is MatchPhase.PLAYING:
            cues.append(Cue("go"))
        self.countdown = match.countdown
        self.phase = match.phase
        return cues

    def _fighter(self, fighter: Fighter) -> list[Cue]:
        now = (fighter.state, fighter.move_id, fighter.state_frame)
        before = self.seen.get(fighter.player_index)
        self.seen[fighter.player_index] = now
        if before is None or fighter.hitlag > 0:
            return []
        entered = before[0] is not fighter.state or fighter.state_frame < before[2]
        if fighter.state is StateId.ATTACK:
            if not entered and before[1] == fighter.move_id:
                return []
            move = fighter.move
            name = SWING_BY_KIND.get(move.kind) if move is not None else None
            return [Cue(name, fighter.pos, vary=True)] if name else []
        if not entered:
            return []
        name = STATE_SOUNDS.get(fighter.state)
        return [Cue(name, fighter.pos, vary=True)] if name else []


def required_sounds() -> set[str]:
    """Every sound name this module can ask for (the build must provide them all)."""
    names = {"pummel", "double_jump", "jump", "land_heavy", "land_light", "ko_blast"}
    names |= {"respawn", "clank", "parry", "shield_hit", "shield_break", "grab", "ledge_grab"}
    names |= {"tech", "wall_bounce", "shoot", "shockwave", "counter", "sudden_death", "game"}
    names |= {"countdown", "go"}
    names |= set(SWING_BY_KIND.values()) | set(STATE_SOUNDS.values())
    for tier in HIT_TIER_NAMES:
        names.add(tier)
        names |= {f"{tier}_{effect.value}" for effect in Effect if effect is not Effect.NORMAL}
    return names
