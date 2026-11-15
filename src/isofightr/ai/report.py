"""How well do the CPUs play? Matches, measurements, metrics and targets (decision D-071).

Plan note "15 - CPU AI" ("Tuning and proof"); the command line is ``tools/cpu_report.py``.
This module plays fixed, seeded matches and counts what the CPUs do in them:

- :func:`suites` lists the matches: a **ladder** (each level against the next), a **matrix**
  (every character against every character at level 9), **versus** (the game's CPU against
  the frozen M10 one, :mod:`isofightr.ai.classic`), **bots** (the scripted cheap strategies of
  :mod:`isofightr.ai.bots`), **low** (levels 1 and 5 against the one-button bots), and
  four-player **ffa**, **mix** and **teams** matches.
- :func:`play` plays one match and returns a :class:`MatchReport`: for every player, what
  became of each move it used (hit, blocked, nothing), whether it followed its hits up,
  whether it punished what missed it and what it blocked, what it was doing when it was hit,
  where its KOs came from, and so on.
- :func:`summarise` turns the reports into named metrics, :data:`TARGETS` says what M20 wants
  each to be, and :func:`report_lines` prints both.

The **subject** is the player written ``cpu:<level>``: the game's CPU, or with
``subject="classic"`` the frozen one, which is how the baseline is reproduced.

What counts as what:

- A **use** is one move from its first frame until the fighter is out of it. A move the
  fighter cannot start by itself (Quake Slam's landing, a counter's reply) belongs to the use
  it came out of. A use **hit** if any of its hitboxes or projectiles damaged someone, was
  **blocked** if a shield took it, was **stuffed** if it was cut short before any of its
  hitboxes came out, and otherwise **whiffed**.
- A **follow-up**: after a use that launched someone (knockback of ``LAUNCH_KNOCKBACK`` or
  more), another use by the same player hits the same target within ``FOLLOW_UP_FRAMES``.
- A **whiff punished**: a move that whiffed with the player within ``WHIFF_RANGE`` of it, and
  the player hit or grabbed its user after its hitboxes were gone: in its end lag, or within
  ``WHIFF_PUNISH_FRAMES`` of its end. (A move with no hitbox at all, a counter, is punished
  by any hit during it.)
- A **block punished**: the player shielded a move and hit or grabbed its user within
  ``BLOCK_PUNISH_FRAMES``.

It never reads a clock (the tool measures cost) and never changes a match except by the
inputs the players return. Pure Python (no ``arcade``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from isofightr.ai.bots import BOTS, ONE_BUTTON, Brain, bot_def, make_bot
from isofightr.ai.classic import ClassicCpu
from isofightr.ai.classic.terrain import over_ground
from isofightr.ai.classic.view import view_fighter
from isofightr.ai.controller import CpuController
from isofightr.ai.view import observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat.hitbox import active_hitboxes
from isofightr.sim.events import (
    GrabEvent,
    HazardHitEvent,
    HitEvent,
    KoEvent,
    ProjectileEvent,
    ShieldHitEvent,
)
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.stage import Stage

GAME: Final[str] = "game"
CLASSIC: Final[str] = "classic"
CHARACTERS: Final[tuple[str, ...]] = ("rook", "bramble", "zephyr", "mote")
STAGES: Final[tuple[str, ...]] = (
    "sky_ruins",
    "final_plateau",
    "training_grid",
    "twin_isles",
    "lily_pads",
    "ember_forge",
    "frostpeak",
    "neon_circuit",
    "dune_bazaar",
    "glowcap_grove",
    "storm_galleon",
)
BOT_STAGES: Final[tuple[str, ...]] = ("final_plateau", "sky_ruins")
TOP_LEVEL: Final[int] = 9
STOCKS: Final[int] = 3
MINUTES: Final[float] = 6.0
OVERTIME_FRAMES: Final[int] = 1800
"""A match is given this long after its clock for a sudden death, then counted unfinished."""
MOVE_STATES: Final[frozenset[StateId]] = frozenset(
    {StateId.ATTACK, StateId.GRAB, StateId.DASH_GRAB}
)
SHIELD_STATES: Final[frozenset[StateId]] = frozenset(
    {StateId.SHIELD, StateId.SHIELD_STUN, StateId.SHIELD_DROP}
)
HURT_STATES: Final[frozenset[StateId]] = frozenset({StateId.FLINCH, StateId.TUMBLE})
SMASHES: Final[frozenset[str]] = frozenset({"fsmash", "usmash", "dsmash"})
LIGHT_MOVES: Final[frozenset[str]] = frozenset(
    {"jab1", "jab2", "jab3", "ftilt", "utilt", "dtilt", "grab", "dash_grab"}
)
"""Jabs, tilts and grabs: the small moves a neutral game is made of."""
LAUNCH_KNOCKBACK: Final[float] = 30.0
"""A hit this strong opens a follow-up chance."""
FOLLOW_UP_FRAMES: Final[int] = 45
WHIFF_RANGE: Final[float] = 3.5
WHIFF_PUNISH_FRAMES: Final[int] = 20
BLOCK_PUNISH_FRAMES: Final[int] = 40
CREDIT_FRAMES: Final[int] = 300
"""A projectile's hit is credited to the use that fired it for this long."""
NEAR_INVINCIBLE: Final[float] = 2.0
"""Standing this close to an opponent that cannot be hit is time wasted."""


# --- what is played --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchSpec:
    """One match of a suite. ``players`` are ``cpu:<level>`` (the subject), ``classic:<level>``
    (the frozen M10 CPU) or ``bot:<name>``."""

    suite: str
    tag: str
    stage: str
    characters: tuple[str, ...]
    players: tuple[str, ...]
    seed: int
    stocks: int = STOCKS
    minutes: float = MINUTES
    hazards: bool = True
    teams: tuple[int, ...] | None = None
    friendly_fire: bool = False

    def is_subject(self, player: int) -> bool:
        """Whether ``player`` is the CPU being measured."""
        return self.players[player].startswith("cpu:")

    def level(self, player: int) -> int:
        """A CPU player's level (0 for a bot)."""
        kind, _, value = self.players[player].partition(":")
        return int(value) if kind in ("cpu", "classic") else 0


def make_brain(spec: str, player: int, seed: int, stage: Stage, subject: str = GAME) -> Brain:
    """Build the player a spec string names. ``subject`` says which CPU ``cpu:`` means."""
    kind, _, value = spec.partition(":")
    if kind == "cpu":
        if subject == CLASSIC:
            return ClassicCpu(player, int(value), seed, stage)
        return CpuController(player, int(value), seed, stage)
    if kind == "classic":
        return ClassicCpu(player, int(value), seed, stage)
    if kind == "bot":
        return make_bot(value, player, seed, stage)
    raise ValueError(f"unknown player {spec!r}: use cpu:<level>, classic:<level> or bot:<name>")


def _ladder() -> list[MatchSpec]:
    out: list[MatchSpec] = []
    for index, character in enumerate(CHARACTERS):
        for low, high in ((1, 3), (3, 5), (5, 7), (7, 9), (8, 9)):
            for seed in range(6):
                levels = (low, high) if seed % 2 == 0 else (high, low)
                out.append(
                    MatchSpec(
                        suite="ladder",
                        tag=f"{low}v{high}",
                        stage=STAGES[(seed + index * 3) % len(STAGES)],
                        characters=(character, character),
                        players=tuple(f"cpu:{level}" for level in levels),
                        seed=seed,
                    )
                )
    return out


def _pairs(suite: str, other: str, first_seed: int) -> list[MatchSpec]:
    """Every character against every character, six seeds each, over all the stages."""
    out: list[MatchSpec] = []
    count = 0
    for mine in CHARACTERS:
        for theirs in CHARACTERS:
            for seed in range(6):
                subject = f"cpu:{TOP_LEVEL}"
                # The subject changes side on odd seeds, so a side's advantage cancels out.
                swap = other != subject and seed % 2 == 1
                out.append(
                    MatchSpec(
                        suite=suite,
                        tag=f"{mine} v {theirs}",
                        stage=STAGES[count % len(STAGES)],
                        characters=(theirs, mine) if swap else (mine, theirs),
                        players=(other, subject) if swap else (subject, other),
                        seed=first_seed + seed,
                    )
                )
                count += 1
    return out


def _bots() -> list[MatchSpec]:
    out: list[MatchSpec] = []
    for character in CHARACTERS:
        for bot in BOTS:
            for stage in BOT_STAGES:
                for seed in range(2):
                    out.append(
                        MatchSpec(
                            suite="bots",
                            tag=bot.name,
                            stage=stage,
                            characters=(character, bot.character),
                            players=(f"cpu:{TOP_LEVEL}", f"bot:{bot.name}"),
                            seed=30 + seed,
                            hazards=False,
                        )
                    )
    return out


def _low() -> list[MatchSpec]:
    out: list[MatchSpec] = []
    for level in (1, 5):
        for name in ONE_BUTTON:
            for stage in BOT_STAGES:
                for seed in range(3):
                    out.append(
                        MatchSpec(
                            suite="low",
                            tag=f"{level} v {name}",
                            stage=stage,
                            characters=("rook", bot_def(name).character),
                            players=(f"cpu:{level}", f"bot:{name}"),
                            seed=80 + seed,
                            hazards=False,
                        )
                    )
    return out


def _four() -> list[MatchSpec]:
    out: list[MatchSpec] = []
    top = tuple(f"cpu:{TOP_LEVEL}" for _ in CHARACTERS)
    for index, stage in enumerate(STAGES):
        for seed in range(2):
            out.append(MatchSpec("ffa", stage, stage, CHARACTERS, top, 50 + seed))
        for turn in range(4):
            levels = tuple(f"cpu:{(9, 7, 5, 3)[(slot + turn) % 4]}" for slot in range(4))
            out.append(MatchSpec("mix", stage, stage, CHARACTERS, levels, 60 + turn))
        out.append(
            MatchSpec(
                "teams",
                stage,
                stage,
                CHARACTERS,
                top,
                70 + index,
                teams=(0, 0, 1, 1),
                friendly_fire=True,
            )
        )
    return out


SUITES: Final[tuple[str, ...]] = (
    "ladder",
    "matrix",
    "versus",
    "bots",
    "low",
    "ffa",
    "mix",
    "teams",
)
QUICK_STRIDE: Final[dict[str, int]] = {
    "ladder": 24,
    "matrix": 12,
    "versus": 12,
    "bots": 16,
    "low": 9,
    "ffa": 11,
    "mix": 22,
    "teams": 6,
}
"""``quick`` keeps every n-th match of a suite: about forty matches, under a minute."""


def suites(quick: bool = False, only: Sequence[str] = ()) -> list[MatchSpec]:
    """The matches of a report, in a fixed order. ``quick`` keeps a thin, fixed sample;
    ``only`` keeps the named suites."""
    everything = (
        _ladder()
        + _pairs("matrix", f"cpu:{TOP_LEVEL}", 10)
        + _pairs("versus", f"classic:{TOP_LEVEL}", 20)
        + _bots()
        + _low()
        + _four()
    )
    out: list[MatchSpec] = []
    seen: dict[str, int] = {}
    for spec in everything:
        if only and spec.suite not in only:
            continue
        index = seen.get(spec.suite, 0)
        seen[spec.suite] = index + 1
        if quick and index % QUICK_STRIDE[spec.suite] != 0:
            continue
        out.append(spec)
    return out


# --- what is measured ------------------------------------------------------------------------


def _bump(counts: dict[str, int], key: str, amount: int = 1) -> None:
    counts[key] = counts.get(key, 0) + amount


@dataclass(slots=True)
class PlayerReport:
    """What one player did in one match."""

    spec: str
    character: str
    subject: bool
    won: bool = False
    ticks: int = 0
    """Ticks spent in play (not waiting to respawn)."""
    uses: int = 0
    uses_hit: int = 0
    uses_blocked: int = 0
    uses_stuffed: int = 0
    """Uses cut short before a hitbox came out (hit out of the start-up, mostly)."""
    moves: dict[str, int] = field(default_factory=dict)
    """Uses by move id (``grab`` and ``dash_grab`` for grabs)."""
    hits: int = 0
    combo_hits: int = 0
    """Hits on a target still in hitstun from another of this player's uses."""
    launches: int = 0
    """Uses that launched someone: follow-up chances."""
    follow_ups: int = 0
    whiff_chances: int = 0
    whiff_punishes: int = 0
    blocks: int = 0
    """Opponents' uses this player shielded."""
    block_punishes: int = 0
    taken: dict[str, int] = field(default_factory=dict)
    """Hits taken by what the player was doing: ``free``, ``own_move``, ``hitstun``,
    ``shield`` (a poke through it) or ``lag``."""
    entries: dict[str, int] = field(default_factory=dict)
    """How many times each state was entered."""
    grabs: int = 0
    grabbed: int = 0
    kos: int = 0
    falls: int = 0
    self_destructs: int = 0
    ko_moves: dict[str, int] = field(default_factory=dict)
    offstage_hits: int = 0
    """Hits on a target that was off the stage or hanging from a ledge."""
    offstage_kos: int = 0
    offstage_trips: int = 0
    offstage_deaths: int = 0
    team_hits: int = 0
    hazard_hits: int = 0
    hazard_blocks: int = 0
    near_invincible: int = 0
    """Ticks spent within ``NEAR_INVINCIBLE`` units of an opponent that could not be hit."""
    damage_given: float = 0.0
    damage_taken: float = 0.0
    longest_combo: int = 0


@dataclass(slots=True)
class MatchReport:
    """How one match went."""

    spec: MatchSpec
    ticks: int
    ended: bool
    timed_out: bool
    winners: tuple[int, ...]
    players: list[PlayerReport]
    state_hash: str


@dataclass(slots=True)
class _Use:
    serial: int
    moves: set[str]
    name: str
    start: int
    connected: bool = False
    blocked: bool = False
    projectile: bool = False
    stuffed: bool = False
    has_hitbox: bool = True
    """Whether the move has a hitbox or grab box at all (a counter has none)."""
    active_seen: bool = False
    active_now: bool = False
    punished_by: list[int] = field(default_factory=list)
    """Players who hit the user after its hitboxes were gone."""


@dataclass(frozen=True, slots=True)
class _Before:
    """A fighter just before the tick: what a hit this tick finds it doing."""

    state: StateId
    hitstun: int
    free: bool
    offstage: bool


@dataclass(slots=True)
class _Chance:
    other: int
    serial: int
    deadline: int


class _Recorder:
    """Counts what happens in one match. ``before`` and ``after`` wrap every tick."""

    def __init__(self, match: Match, spec: MatchSpec) -> None:
        self.spec = spec
        count = len(match.fighters)
        self.players = [
            PlayerReport(spec.players[index], spec.characters[index], spec.is_subject(index))
            for index in range(count)
        ]
        self.slot_moves = [set(fighter.character.moveset.all_ids()) for fighter in match.fighters]
        self.uses: list[list[_Use]] = [[] for _ in range(count)]
        self.current: list[_Use | None] = [None] * count
        self.serial = 0
        self.previous: list[tuple[StateId, str, int]] = [
            (fighter.state, fighter.move_id, fighter.state_frame) for fighter in match.fighters
        ]
        self.snapshot: list[_Before] = []
        self.follow: list[_Chance | None] = [None] * count
        self.block: list[_Chance | None] = [None] * count
        self.blocked_uses: set[tuple[int, int]] = set()
        self.whiffs: list[list[_Chance]] = [[] for _ in range(count)]
        self.last_hit: list[tuple[int, str, bool, int] | None] = [None] * count
        self.away = [False] * count

    # -- per tick ---------------------------------------------------------------------------

    def before(self, match: Match) -> None:
        """Note what every fighter is doing before the tick."""
        self.snapshot = [
            _Before(
                state=fighter.state,
                hitstun=fighter.hitstun,
                free=view_fighter(fighter).free,
                offstage=self._offstage(match, fighter),
            )
            for fighter in match.fighters
        ]

    @staticmethod
    def _offstage(match: Match, fighter: Fighter) -> bool:
        if fighter.state is StateId.LEDGE_HANG:
            return True
        return not fighter.grounded and not over_ground(match.stage, fighter.pos)

    def after(self, match: Match) -> None:
        """Count this tick's events and what every fighter turned to."""
        frame = match.frame
        for event in match.events:
            if isinstance(event, HitEvent):
                self._hit(match, event, frame)
            elif isinstance(event, ShieldHitEvent):
                self._shield_hit(event, frame)
            elif isinstance(event, GrabEvent):
                if not event.clash:
                    self._grab(event, frame)
            elif isinstance(event, ProjectileEvent):
                use = self.current[event.owner]
                if event.spawned and use is not None:
                    use.projectile = True
            elif isinstance(event, HazardHitEvent):
                report = self.players[event.target]
                report.hazard_hits += 1
                report.hazard_blocks += int(event.blocked)
            elif isinstance(event, KoEvent):
                self._ko(event)
        for index, fighter in enumerate(match.fighters):
            self._fighter(match, index, fighter, frame)
        for index in range(len(self.whiffs)):
            self.whiffs[index] = [c for c in self.whiffs[index] if c.deadline >= frame]

    def _use_for(self, player: int, move_id: str, frame: int) -> _Use | None:
        """The use a hit by ``move_id`` belongs to: the current one, or the latest one that
        fired a projectile of that move."""
        current = self.current[player]
        if current is not None and (
            move_id in current.moves or move_id not in self.slot_moves[player]
        ):
            return current
        for use in reversed(self.uses[player][-12:]):
            if move_id in use.moves and frame - use.start <= CREDIT_FRAMES:
                return use
        return None

    def _hit(self, match: Match, event: HitEvent, frame: int) -> None:
        attacker, target = event.attacker, event.target
        if attacker == target:
            return
        mine, theirs = self.players[attacker], self.players[target]
        if match.fighters[attacker].allied_with(match.fighters[target]):
            mine.team_hits += 1
        was = self.snapshot[target]
        mine.hits += 1
        if was.state in HURT_STATES or was.hitstun > 0:
            category = "hitstun"
        elif was.state in SHIELD_STATES:
            category = "shield"
        elif was.state in MOVE_STATES and not was.free:
            category = "own_move"
        elif was.free:
            category = "free"
        else:
            category = "lag"
        _bump(theirs.taken, category)
        if was.offstage:
            mine.offstage_hits += 1
        use = self._use_for(attacker, event.move_id, frame)
        if use is None:
            self.serial += 1
            serial = self.serial  # a throw or a pummel: a use of its own
        else:
            use.connected = True
            serial = use.serial
        self._caught(attacker, target)
        self._answered(attacker, target, frame)
        last = self.last_hit[target]
        chained = last is not None and last[0] == attacker and last[3] != serial
        if category == "hitstun" and chained:
            mine.combo_hits += 1
        chance = self.follow[attacker]
        if chance is not None and chance.other == target and frame <= chance.deadline:
            if chance.serial == serial:
                chance.deadline = frame + FOLLOW_UP_FRAMES  # a later hit of the same move
            else:
                mine.follow_ups += 1
                self.follow[attacker] = chance = None
        if event.knockback >= LAUNCH_KNOCKBACK and (chance is None or chance.serial != serial):
            mine.launches += 1
            self.follow[attacker] = _Chance(target, serial, frame + FOLLOW_UP_FRAMES)
        self.last_hit[target] = (attacker, event.move_id, was.offstage, serial)

    def _caught(self, player: int, victim: int) -> None:
        """``player`` hit or grabbed ``victim`` in the middle of a move: note whether that was
        after the move's hitboxes had come and gone."""
        use = self.current[victim]
        if use is None:
            return
        if not use.has_hitbox or (use.active_seen and not use.active_now):
            use.punished_by.append(player)

    def _answered(self, player: int, victim: int, frame: int) -> None:
        """``player`` hit or grabbed ``victim``: settle what that punishes."""
        mine = self.players[player]
        blocked = self.block[player]
        if blocked is not None and blocked.other == victim and frame <= blocked.deadline:
            mine.block_punishes += 1
            self.block[player] = None
        for chance in list(self.whiffs[player]):
            if chance.other == victim and frame <= chance.deadline:
                mine.whiff_punishes += 1
                self.whiffs[player].remove(chance)

    def _shield_hit(self, event: ShieldHitEvent, frame: int) -> None:
        attacker, target = event.attacker, event.target
        use = self.current[attacker]
        if use is None:
            for older in reversed(self.uses[attacker][-12:]):
                if older.projectile and frame - older.start <= CREDIT_FRAMES:
                    use = older
                    break
        if use is None:
            return
        use.blocked = True
        if (target, use.serial) in self.blocked_uses:
            return
        self.blocked_uses.add((target, use.serial))
        self.players[target].blocks += 1
        self.block[target] = _Chance(attacker, use.serial, frame + BLOCK_PUNISH_FRAMES)

    def _grab(self, event: GrabEvent, frame: int) -> None:
        self.players[event.grabber].grabs += 1
        self.players[event.target].grabbed += 1
        use = self.current[event.grabber]
        if use is not None:
            use.connected = True
        self._caught(event.grabber, event.target)
        self._answered(event.grabber, event.target, frame)

    def _ko(self, event: KoEvent) -> None:
        victim = self.players[event.player]
        victim.falls += 1
        if self.away[event.player]:
            victim.offstage_deaths += 1
            self.away[event.player] = False
        last = self.last_hit[event.player]
        self.last_hit[event.player] = None
        if event.credited_to is None:
            victim.self_destructs += 1
            return
        killer = self.players[event.credited_to]
        killer.kos += 1
        if last is not None and last[0] == event.credited_to:
            _bump(killer.ko_moves, last[1])
            killer.offstage_kos += int(last[2])

    def _fighter(self, match: Match, index: int, fighter: Fighter, frame: int) -> None:
        report = self.players[index]
        state, move_id, state_frame = fighter.state, fighter.move_id, fighter.state_frame
        was_state, was_move, was_frame = self.previous[index]
        self.previous[index] = (state, move_id, state_frame)
        if not fighter.in_play:
            self._end_use(match, index, frame)
            return
        report.ticks += 1
        if state is not was_state:
            _bump(report.entries, state.value)
        in_move = state in MOVE_STATES
        name = move_id if state is StateId.ATTACK else state.value
        started = in_move and (
            was_state not in MOVE_STATES
            or state is not was_state
            or (state is StateId.ATTACK and move_id != was_move)
            or state_frame < was_frame
        )
        current = self.current[index]
        if started:
            follows = (
                current is not None
                and state is StateId.ATTACK
                and name not in self.slot_moves[index]
            )
            if follows and current is not None:
                current.moves.add(name)
            else:
                self._end_use(match, index, frame)
                self.serial += 1
                use = _Use(self.serial, {name}, name, frame, has_hitbox=self._armed(fighter))
                self.current[index] = use
                self.uses[index].append(use)
        elif not in_move and current is not None:
            self._end_use(match, index, frame)
        current = self.current[index]
        if current is not None:
            current.active_now = self._active(fighter)
            current.active_seen = current.active_seen or current.active_now
        for other in match.fighters:
            if other is fighter or not other.in_play or fighter.allied_with(other):
                continue
            if other.invincible and (other.pos - fighter.pos).length() < NEAR_INVINCIBLE:
                report.near_invincible += 1
                break
        offstage = self._offstage(match, fighter)
        if offstage and state is not StateId.LEDGE_HANG:
            if not self.away[index]:
                self.away[index] = True
                report.offstage_trips += 1
        elif fighter.grounded or state is StateId.LEDGE_HANG:
            self.away[index] = False

    @staticmethod
    def _armed(fighter: Fighter) -> bool:
        """Whether the move a fighter just started has a hitbox or a grab box."""
        if fighter.state is not StateId.ATTACK:
            return True
        move = fighter.move
        return move is None or any(window.hitboxes for window in move.windows)

    @staticmethod
    def _active(fighter: Fighter) -> bool:
        """Whether a hitbox or grab box of the fighter's move is out on this frame."""
        grabs = fighter.character.grabs
        if fighter.state is StateId.GRAB:
            return fighter.state_frame in grabs.standing.frames
        if fighter.state is StateId.DASH_GRAB:
            return fighter.state_frame in grabs.dash.frames
        return bool(active_hitboxes(fighter))

    def _end_use(self, match: Match, index: int, frame: int) -> None:
        """A use is over: if it whiffed, everyone near it had a chance to punish it."""
        use = self.current[index]
        if use is None:
            return
        self.current[index] = None
        if use.connected or use.blocked or use.projectile:
            return
        if use.has_hitbox and not use.active_seen:
            use.stuffed = True
            return
        fighter = match.fighters[index]
        for other in match.fighters:
            if other is fighter or not other.in_play or fighter.allied_with(other):
                continue
            if (other.pos - fighter.pos).length() > WHIFF_RANGE:
                continue
            mine = self.players[other.player_index]
            mine.whiff_chances += 1
            if other.player_index in use.punished_by:
                mine.whiff_punishes += 1
            else:
                self.whiffs[other.player_index].append(
                    _Chance(index, use.serial, frame + WHIFF_PUNISH_FRAMES)
                )

    # -- the result -------------------------------------------------------------------------

    def report(self, match: Match, time_frames: int) -> MatchReport:
        """Close the books when the match is over (or was cut off)."""
        winners = tuple(match.result.winners) if match.result is not None else ()
        for index, report in enumerate(self.players):
            for use in self.uses[index]:
                report.uses += 1
                _bump(report.moves, use.name)
                if use.connected:
                    report.uses_hit += 1
                elif use.blocked:
                    report.uses_blocked += 1
                elif use.stuffed:
                    report.uses_stuffed += 1
            stats = match.stats[index]
            report.damage_given = stats.damage_given
            report.damage_taken = stats.damage_taken
            report.longest_combo = stats.longest_combo
            report.won = index in winners
        return MatchReport(
            spec=self.spec,
            ticks=match.frame,
            ended=match.result is not None,
            timed_out=match.result is not None and match.frame >= time_frames,
            winners=winners,
            players=self.players,
            state_hash=match.state_hash(),
        )


def play(spec: MatchSpec, subject: str = GAME) -> MatchReport:
    """Play one match to its end and return what happened in it."""
    stage = load_stage(spec.stage)
    time_frames = round(spec.minutes * 3600)
    rules = MatchRules(
        stocks=spec.stocks,
        time_frames=time_frames,
        stage_hazards=spec.hazards,
        teams=spec.teams,
        friendly_fire=spec.friendly_fire,
    )
    characters = [load_character(character) for character in spec.characters]
    match = Match.create(stage, characters, seed=spec.seed, rules=rules)
    brains = [
        make_brain(player, index, spec.seed, stage, subject)
        for index, player in enumerate(spec.players)
    ]
    recorder = _Recorder(match, spec)
    limit = time_frames + OVERTIME_FRAMES
    while match.result is None and match.frame < limit:
        world = observe(match)
        recorder.before(match)
        match.tick([brain.think(match, world) for brain in brains])
        recorder.after(match)
    return recorder.report(match, time_frames)


def trace(spec: MatchSpec, player: int, ticks: int, subject: str = GAME) -> list[str]:
    """One player's decision timeline: a line each time its plan changes or it hits, is hit
    or loses a stock. For a brain without a ``plan`` only the events are listed."""
    stage = load_stage(spec.stage)
    rules = MatchRules(stocks=spec.stocks, stage_hazards=spec.hazards, teams=spec.teams)
    characters = [load_character(character) for character in spec.characters]
    match = Match.create(stage, characters, seed=spec.seed, rules=rules)
    brains = [
        make_brain(name, index, spec.seed, stage, subject)
        for index, name in enumerate(spec.players)
    ]
    lines: list[str] = []
    last = ""
    for _ in range(ticks):
        if match.result is not None:
            break
        world = observe(match)
        inputs = [brain.think(match, world) for brain in brains]
        plan = getattr(brains[player], "plan", None)
        text = "" if plan is None else f"{plan.kind} {plan.detail}".strip()
        me = match.fighters[player]
        if text != last:
            last = text
            others = [f for f in match.fighters if f is not me and f.in_play]
            near = min(((f.pos - me.pos).length() for f in others), default=0.0)
            lines.append(
                f"{match.frame:6d}  {text:24s} {me.state.value:12s} "
                f"{me.damage:5.1f}%  nearest {near:4.1f}"
            )
        match.tick(inputs)
        for event in match.events:
            if isinstance(event, HitEvent) and player in (event.attacker, event.target):
                verb = "hits with" if event.attacker == player else "is hit by"
                lines.append(f"{match.frame:6d}    {verb} {event.move_id} ({event.damage:.1f}%)")
            elif isinstance(event, KoEvent) and event.player == player:
                lines.append(f"{match.frame:6d}    loses a stock")
    return lines


# --- metrics ---------------------------------------------------------------------------------


@dataclass(slots=True)
class Tally:
    """Several players' reports added up."""

    matches: int = 0
    wins: int = 0
    total: PlayerReport = field(default_factory=lambda: PlayerReport("", "", False))

    def add(self, report: PlayerReport) -> None:
        """Add one player's match."""
        self.matches += 1
        self.wins += int(report.won)
        total = self.total
        for name in PlayerReport.__dataclass_fields__:
            value = getattr(report, name)
            if isinstance(value, (bool, str)):
                continue
            if isinstance(value, dict):
                mine: dict[str, int] = getattr(total, name)
                for key, amount in value.items():
                    _bump(mine, key, amount)
            elif name == "longest_combo":
                total.longest_combo = max(total.longest_combo, value)
            else:
                setattr(total, name, getattr(total, name) + value)

    @property
    def minutes(self) -> float:
        """Minutes in play."""
        return self.total.ticks / 3600.0


def share(part: float, whole: float) -> float:
    """``part / whole``, or 0 when there is nothing to divide by."""
    return part / whole if whole else 0.0


def tally(reports: Iterable[MatchReport], suite: str, subjects: bool = True) -> Tally:
    """Add up a suite's players: the subjects, or (``subjects=False``) everyone else."""
    out = Tally()
    for report in reports:
        if report.spec.suite != suite:
            continue
        for player in report.players:
            if player.subject == subjects:
                out.add(player)
    return out


def _top_share(reports: Sequence[MatchReport], suite: str) -> tuple[float, str]:
    """The largest share any one move has of a character's moves, and which."""
    best, label = 0.0, ""
    for character in CHARACTERS:
        moves: dict[str, int] = {}
        for report in reports:
            if report.spec.suite != suite:
                continue
            for player in report.players:
                if player.subject and player.character == character:
                    for key, amount in player.moves.items():
                        _bump(moves, key, amount)
        total = sum(moves.values())
        for key, amount in moves.items():
            if share(amount, total) > best:
                best, label = share(amount, total), f"{character} {key}"
    return best, label


def _win_share(reports: Sequence[MatchReport], suite: str, tags: Sequence[str] = ()) -> float:
    """Share of a suite's two-player matches the subject won; in ``ladder`` the higher
    level. A match without a result counts as not won."""
    won = played = 0
    for report in reports:
        spec = report.spec
        if spec.suite != suite or (tags and spec.tag not in tags):
            continue
        played += 1
        if suite == "ladder":
            side = max(range(len(spec.players)), key=spec.level)
        else:
            side = next(i for i in range(len(spec.players)) if not spec.is_subject(i))
            side = 1 - side
        won += int(side in report.winners)
    return share(won, played)


def summarise(reports: Sequence[MatchReport]) -> dict[str, float]:
    """Turn match reports into the named metrics of D-071. A metric whose suite was not
    played is left out."""
    present = {report.spec.suite for report in reports}
    out: dict[str, float] = {}
    out["unfinished"] = float(sum(1 for report in reports if not report.ended))
    if "matrix" in present:
        m = tally(reports, "matrix")
        t = m.total
        taken = sum(t.taken.values())
        known_kos = sum(t.ko_moves.values())
        smash_kos = sum(amount for key, amount in t.ko_moves.items() if key in SMASHES)
        matches = [report for report in reports if report.spec.suite == "matrix"]
        whiffed = t.uses - t.uses_hit - t.uses_blocked - t.uses_stuffed
        out["whiff_rate"] = share(whiffed, t.uses)
        out["stuffed_rate"] = share(t.uses_stuffed, t.uses)
        out["top_move_share"] = _top_share(reports, "matrix")[0]
        out["light_share"] = share(sum(t.moves.get(k, 0) for k in LIGHT_MOVES), t.uses)
        out["jab_chain_rate"] = share(t.moves.get("jab2", 0), t.moves.get("jab1", 0))
        out["rolls_per_min"] = share(t.entries.get("roll", 0), m.minutes)
        out["spot_dodges_per_min"] = share(t.entries.get("spot_dodge", 0), m.minutes)
        out["crouches_per_min"] = share(t.entries.get("crouch", 0), m.minutes)
        out["follow_up_rate"] = share(t.follow_ups, t.launches)
        out["whiff_punish_rate"] = share(t.whiff_punishes, t.whiff_chances)
        out["block_punish_rate"] = share(t.block_punishes, t.blocks)
        out["own_move_hit_share"] = share(t.taken.get("own_move", 0), taken)
        out["damage_per_stock"] = share(t.damage_taken, t.falls)
        out["other_ko_share"] = share(known_kos - smash_kos, known_kos)
        out["offstage_hit_share"] = share(t.offstage_hits, t.hits)
        out["offstage_ko_share"] = share(t.offstage_kos, t.kos)
        out["timeout_share"] = share(sum(1 for r in matches if r.timed_out), len(matches))
        wins = []
        for character in CHARACTERS:
            mine = Tally()
            for report in matches:
                for player in report.players:
                    if player.character == character:
                        mine.add(player)
            wins.append(share(mine.wins, mine.matches))
        out["character_win_low"] = min(wins)
        out["character_win_high"] = max(wins)
    if "versus" in present:
        out["versus_win_rate"] = _win_share(reports, "versus")
    if "ladder" in present:
        out["ladder_two_apart"] = _win_share(reports, "ladder", ("1v3", "3v5", "5v7", "7v9"))
        out["ladder_one_apart"] = _win_share(reports, "ladder", ("8v9",))
    if "bots" in present:
        land = damage = 0.0
        lost = 0
        for bot in BOTS:
            theirs, mine = Tally(), Tally()
            for report in reports:
                if report.spec.suite == "bots" and report.spec.tag == bot.name:
                    for player in report.players:
                        (mine if player.subject else theirs).add(player)
            lost += mine.matches - mine.wins
            if bot.action and bot.approach:
                land = max(land, share(theirs.total.uses_hit, theirs.total.uses))
            damage = max(damage, share(theirs.total.damage_given, mine.total.damage_given))
        out["bot_land_rate"] = land
        out["bot_damage_ratio"] = damage
        out["bot_matches_lost"] = float(lost)
    if "low" in present:
        for level in (1, 5):
            tags = [f"{level} v {name}" for name in ONE_BUTTON]
            out[f"level{level}_bot_win_rate"] = 1.0 - _win_share(reports, "low", tags)
    fours = [suite for suite in ("ffa", "mix", "teams") if suite in present]
    if fours:
        falls = destructs = 0
        worst = 0.0
        by_stage: dict[str, list[int]] = {}
        for report in reports:
            if report.spec.suite not in fours:
                continue
            cell = by_stage.setdefault(report.spec.stage, [0, 0])
            for player in report.players:
                falls += player.falls
                destructs += player.self_destructs
                cell[0] += player.self_destructs
                cell[1] += player.falls
        for cell in by_stage.values():
            worst = max(worst, share(cell[0], cell[1]))
        out["self_destruct_share"] = share(destructs, falls)
        out["self_destruct_worst_stage"] = worst
    if "ffa" in present:
        f = tally(reports, "ffa")
        out["near_invincible_seconds"] = share(f.total.near_invincible / 60.0, f.minutes)
        storm = Tally()
        for report in reports:
            if report.spec.suite == "ffa" and report.spec.stage == "storm_galleon":
                for player in report.players:
                    storm.add(player)
        if storm.matches:
            out["lightning_per_min"] = share(storm.total.hazard_hits, storm.minutes / 4.0)
    if "teams" in present:
        t = tally(reports, "teams").total
        out["team_hit_share"] = share(t.team_hits, t.hits)
    return out


@dataclass(frozen=True, slots=True)
class Target:
    """What M20 wants a metric to be (the roadmap's exit criteria)."""

    metric: str
    at_least: bool
    """True: the value must be this or more. False: this or less."""
    value: float
    baseline: float
    """What the frozen M10 CPU scores (``tools/cpu_report.py --subject classic``)."""
    what: str
    percent: bool = True

    def met(self, value: float) -> bool:
        """Whether ``value`` meets the target."""
        return value >= self.value if self.at_least else value <= self.value


COST_METRICS: Final[tuple[str, ...]] = ("think_ms", "think_worst_ms")
"""Measured by the tool, which may read a clock (this module may not)."""
HOLD: Final[frozenset[str]] = frozenset(
    {
        "ladder_two_apart",
        "ladder_one_apart",
        "self_destruct_share",
        "self_destruct_worst_stage",
        "level5_bot_win_rate",
        "think_ms",
    }
)
"""Metrics the M10 CPU already meets: the new CPU must not lose them."""

TARGETS: Final[tuple[Target, ...]] = (
    Target("versus_win_rate", True, 0.75, 0.4, "wins against the frozen M10 CPU"),
    Target("ladder_two_apart", True, 0.85, 0.97, "two levels apart, the higher wins"),
    Target("ladder_one_apart", True, 0.6, 0.625, "one level apart (8 v 9), the higher wins"),
    Target("whiff_rate", False, 0.25, 0.44, "moves that whiff"),
    Target("stuffed_rate", False, 0.08, 0.12, "moves stuffed before they come out"),
    Target("top_move_share", False, 0.25, 0.52, "the most repeated move's share"),
    Target("light_share", True, 0.2, 0.02, "jabs, tilts and grabs among its moves"),
    Target("jab_chain_rate", True, 0.3, 0.0, "jabs continued into the chain"),
    Target("rolls_per_min", True, 0.2, 0.0, "rolls a minute", percent=False),
    Target("spot_dodges_per_min", True, 0.2, 0.0, "spot dodges a minute", percent=False),
    Target("crouches_per_min", True, 0.1, 0.0, "crouches a minute", percent=False),
    Target("follow_up_rate", True, 0.3, 0.1, "launching hits followed up"),
    Target("whiff_punish_rate", True, 0.5, 0.29, "whiffs next to it punished"),
    Target("block_punish_rate", True, 0.5, 0.25, "blocked moves punished"),
    Target("own_move_hit_share", False, 0.3, 0.44, "hits taken inside its own move"),
    Target("bot_land_rate", False, 0.3, 0.87, "the best a one-move bot lands"),
    Target("bot_damage_ratio", False, 0.5, 0.83, "a bot's damage against the CPU's, at most"),
    Target("bot_matches_lost", False, 0.0, 1.0, "matches lost to a bot", percent=False),
    Target("damage_per_stock", False, 165.0, 203.0, "damage taken per stock lost", percent=False),
    Target("other_ko_share", True, 0.35, 0.19, "KOs that are not smashes"),
    Target("offstage_hit_share", True, 0.08, 0.035, "hits on a target off the stage"),
    Target("offstage_ko_share", True, 0.25, 0.14, "KOs on a target off the stage"),
    Target("character_win_low", True, 0.35, 0.23, "the weakest character's wins"),
    Target("character_win_high", False, 0.65, 0.77, "the strongest character's wins"),
    Target("team_hit_share", False, 0.08, 0.25, "hits on a teammate (friendly fire)"),
    Target(
        "lightning_per_min",
        False,
        5.0,
        10.4,
        "lightning hits a minute, Storm Galleon",
        percent=False,
    ),
    Target(
        "near_invincible_seconds",
        False,
        0.7,
        1.43,
        "seconds a minute beside an invincible foe",
        percent=False,
    ),
    Target("self_destruct_share", False, 0.02, 0.007, "falls that are self-destructs"),
    Target("self_destruct_worst_stage", False, 0.04, 0.04, "the same, on the worst stage"),
    Target("timeout_share", False, 0.02, 0.052, "level 9 matches that go to the clock"),
    Target("unfinished", False, 0.0, 3.0, "matches never settled", percent=False),
    Target("level1_bot_win_rate", True, 0.5, 0.39, "one-button bots' wins against level 1"),
    Target("level5_bot_win_rate", False, 0.1, 0.056, "one-button bots' wins against level 5"),
    Target("think_ms", False, 0.25, 0.05, "ms per CPU per tick", percent=False),
    Target("think_worst_ms", False, 4.0, 7.4, "worst single think, ms", percent=False),
)
"""M20's exit criteria (roadmap), each with what the frozen M10 CPU scored on 2026-11-15
(``tools/cpu_report.py --subject classic``; the two cost rows are measured by the tool).
"""


def check(metrics: dict[str, float]) -> list[tuple[Target, float, bool]]:
    """Each target whose metric was measured, with the value and whether it is met."""
    return [
        (target, metrics[target.metric], target.met(metrics[target.metric]))
        for target in TARGETS
        if target.metric in metrics
    ]


# --- the printed report ----------------------------------------------------------------------


def _percent(value: float) -> str:
    return f"{value * 100:.0f}%"


def _top(counts: dict[str, int], limit: int) -> str:
    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return ", ".join(f"{key} {_percent(share(amount, total))}" for key, amount in ranked) or "-"


def tally_lines(name: str, t: Tally) -> list[str]:
    """A few lines describing how a group of players played."""
    p = t.total
    taken = sum(p.taken.values())
    e = p.entries
    minutes = t.minutes
    whiffed = p.uses - p.uses_hit - p.uses_blocked - p.uses_stuffed
    return [
        f"{name}: {t.matches} played, {t.wins} won; {share(p.damage_given, minutes):.0f}% a "
        f"minute given, {share(p.damage_taken, minutes):.0f}% taken; a stock lost at "
        f"{share(p.damage_taken, p.falls):.0f}%",
        f"  moves {share(p.uses, minutes):.1f} a minute: hit "
        f"{_percent(share(p.uses_hit, p.uses))}, blocked "
        f"{_percent(share(p.uses_blocked, p.uses))}, stuffed "
        f"{_percent(share(p.uses_stuffed, p.uses))}, whiffed {_percent(share(whiffed, p.uses))}",
        f"  most used: {_top(p.moves, 6)}",
        f"  follow-ups {p.follow_ups}/{p.launches} ({_percent(share(p.follow_ups, p.launches))}); "
        f"whiffs punished {p.whiff_punishes}/{p.whiff_chances} "
        f"({_percent(share(p.whiff_punishes, p.whiff_chances))}); blocks punished "
        f"{p.block_punishes}/{p.blocks} ({_percent(share(p.block_punishes, p.blocks))}); "
        f"longest combo {p.longest_combo}",
        f"  hit while: in its own move {_percent(share(p.taken.get('own_move', 0), taken))}, "
        f"free {_percent(share(p.taken.get('free', 0), taken))}, in hitstun "
        f"{_percent(share(p.taken.get('hitstun', 0), taken))}, other lag "
        f"{_percent(share(p.taken.get('lag', 0) + p.taken.get('shield', 0), taken))}",
        f"  a minute: shields {share(e.get('shield', 0), minutes):.1f}, rolls "
        f"{share(e.get('roll', 0), minutes):.2f}, spot dodges "
        f"{share(e.get('spot_dodge', 0), minutes):.2f}, air dodges "
        f"{share(e.get('air_dodge', 0), minutes):.2f}, crouches "
        f"{share(e.get('crouch', 0), minutes):.2f}, grabs landed {share(p.grabs, minutes):.2f}, "
        f"techs {share(e.get('tech', 0) + e.get('tech_roll', 0), minutes):.1f}",
        f"  KOs {p.kos} ({_top(p.ko_moves, 4)}); on a target off the stage "
        f"{p.offstage_kos}; hits on one {p.offstage_hits}/{p.hits}; falls {p.falls}, "
        f"self-destructs {p.self_destructs}",
    ]


def report_lines(reports: Sequence[MatchReport], metrics: dict[str, float]) -> list[str]:
    """The whole report as text: each suite, then the targets."""
    present = [suite for suite in SUITES if any(r.spec.suite == suite for r in reports)]
    unfinished = sum(1 for report in reports if not report.ended)
    clock = sum(1 for report in reports if report.timed_out)
    lines: list[str] = [
        f"{len(reports)} matches: " + ", ".join(present),
        f"{clock} went to the clock; {unfinished} were not settled within "
        f"{OVERTIME_FRAMES // 60} s after it",
    ]
    if "ladder" in present:
        lines += ["", "LADDER: how often the higher level wins"]
        tags = sorted({r.spec.tag for r in reports if r.spec.suite == "ladder"})
        for tag in tags:
            count = sum(1 for r in reports if r.spec.suite == "ladder" and r.spec.tag == tag)
            won = round(_win_share(reports, "ladder", (tag,)) * count)
            lines.append(f"  {tag}: {won}/{count}")
    if "matrix" in present:
        lines += ["", f"MATRIX: level {TOP_LEVEL} against level {TOP_LEVEL}, every character pair"]
        lines += tally_lines("all", tally(reports, "matrix"))
        for character in CHARACTERS:
            mine = Tally()
            for report in reports:
                if report.spec.suite == "matrix":
                    for player in report.players:
                        if player.character == character:
                            mine.add(player)
            lines += tally_lines(character, mine)
        label = _top_share(reports, "matrix")[1]
        lines.append(f"  the most repeated move: {label}")
    if "versus" in present:
        count = sum(1 for r in reports if r.spec.suite == "versus")
        won = round(_win_share(reports, "versus") * count)
        lines += ["", f"VERSUS the frozen M10 CPU at level {TOP_LEVEL}: won {won}/{count}"]
    if "bots" in present:
        lines += ["", f"BOTS: a level {TOP_LEVEL} CPU against each cheap strategy"]
        for bot in BOTS:
            theirs, mine = Tally(), Tally()
            for report in reports:
                if report.spec.suite == "bots" and report.spec.tag == bot.name:
                    for player in report.players:
                        (mine if player.subject else theirs).add(player)
            if not mine.matches:
                continue
            b, c = theirs.total, mine.total
            lines.append(
                f"  {bot.name:13s} CPU won {mine.wins}/{mine.matches}; CPU "
                f"{share(c.damage_given, mine.minutes):4.0f}% a minute, bot "
                f"{share(b.damage_given, mine.minutes):4.0f}%; the bot's move landed "
                f"{b.uses_hit}/{b.uses} ({_percent(share(b.uses_hit, b.uses))}); CPU blocked "
                f"{c.blocks}, grabbed {c.grabs}, was grabbed {c.grabbed}"
            )
    if "low" in present:
        lines += ["", "LOW LEVELS against the one-button bots (the bot's wins)"]
        for level in (1, 5):
            parts = []
            for name in ONE_BUTTON:
                tag = f"{level} v {name}"
                count = sum(1 for r in reports if r.spec.suite == "low" and r.spec.tag == tag)
                if count:
                    lost = count - round(_win_share(reports, "low", (tag,)) * count)
                    parts.append(f"{name} {lost}/{count}")
            if parts:
                lines.append(f"  level {level}: " + ", ".join(parts))
    for suite, title in (
        ("ffa", f"FREE-FOR-ALL: four level {TOP_LEVEL} CPUs on every stage"),
        ("mix", "MIXED LEVELS: 9, 7, 5 and 3 on every stage"),
        ("teams", "TEAMS: two against two with friendly fire"),
    ):
        if suite not in present:
            continue
        played = [r for r in reports if r.spec.suite == suite]
        falls = sum(p.falls for r in played for p in r.players)
        destructs = sum(p.self_destructs for r in played for p in r.players)
        ended = sum(1 for r in played if r.ended)
        seconds = share(sum(r.ticks for r in played), len(played)) / 60.0
        lines += [
            "",
            title,
            f"  {len(played)} matches, {ended} ended, {seconds:.0f} s on average; falls {falls}, "
            f"self-destructs {destructs} ({_percent(share(destructs, falls))})",
        ]
        if suite == "ffa":
            wins = dict.fromkeys(CHARACTERS, 0)
            for report in played:
                for index, player in enumerate(report.players):
                    wins[player.character] += int(index in report.winners)
            lines.append("  wins: " + ", ".join(f"{c} {n}" for c, n in wins.items()))
            hazards: dict[str, int] = {}
            for report in played:
                struck = sum(p.hazard_hits for p in report.players)
                if struck:
                    _bump(hazards, report.spec.stage, struck)
            if hazards:
                lines.append("  hazard hits: " + ", ".join(f"{s} {n}" for s, n in hazards.items()))
        if suite == "mix":
            by_level: dict[int, int] = {}
            for report in played:
                for index in report.winners:
                    level = report.spec.level(index)
                    by_level[level] = by_level.get(level, 0) + 1
            lines.append(
                "  wins by level: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_level.items()))
            )
        if suite == "teams":
            total = tally(reports, "teams").total
            lines.append(f"  hits on a teammate: {total.team_hits}/{total.hits}")
    results = check(metrics)
    if results:
        lines += ["", "TARGETS (M20 exit criteria; baseline = the frozen M10 CPU)"]
        for target, value, met in results:
            shown = _percent(value) if target.percent else f"{value:.2f}"
            wanted = _percent(target.value) if target.percent else f"{target.value:g}"
            base = _percent(target.baseline) if target.percent else f"{target.baseline:.2f}"
            sign = "at least" if target.at_least else "at most"
            verdict = "ok  " if met else "MISS"
            lines.append(
                f"  {verdict} {target.what:46s} {shown:>6s}  ({sign} {wanted}; baseline {base})"
            )
        missed = sum(1 for _, _, met in results if not met)
        lines.append(f"  {len(results) - missed} of {len(results)} targets met")
    return lines
