"""``Fighter`` entity: position, velocity, damage %, stocks and state.

Plan notes "04 - Movement and Physics" ("Fighter body") and "07 - Fighter State Machine and
Move Data". A fighter is plain mutable data; all behaviour lives in the state classes
(:mod:`isofightr.sim.states`) and the physics functions (:mod:`isofightr.sim.physics`), so a
fighter deep-copies and hashes exactly (replays, tests, future rollback).
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum

from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat.constants import SHIELD_MAX_HP
from isofightr.sim.input_frame import Dir8, InputBuffer
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3
from isofightr.sim.move_def import MoveDef
from isofightr.sim.stage import NO_PLATFORM


class StateId(Enum):
    """Every state a fighter can be in so far (plan note 07, "State list").

    Specials arrive in M5.
    """

    IDLE = "idle"
    WALK = "walk"
    DASH = "dash"
    RUN = "run"
    RUN_TURN = "run_turn"
    SKID = "skid"
    TURN = "turn"
    JUMP_SQUAT = "jump_squat"
    LAND = "land"
    PLATFORM_DROP = "platform_drop"
    JUMP = "jump"
    DOUBLE_JUMP = "double_jump"
    FALL = "fall"
    ATTACK = "attack"
    REBOUND = "rebound"
    FLINCH = "flinch"
    TUMBLE = "tumble"
    KNOCKDOWN = "knockdown"
    GETUP = "getup"
    SHIELD = "shield"
    SHIELD_STUN = "shield_stun"
    SHIELD_DROP = "shield_drop"
    SHIELD_BREAK = "shield_break"
    DIZZY = "dizzy"
    SPOT_DODGE = "spot_dodge"
    ROLL = "roll"
    AIR_DODGE = "air_dodge"
    HELPLESS = "helpless"
    GRAB = "grab"
    DASH_GRAB = "dash_grab"
    GRAB_HOLD = "grab_hold"
    GRABBED = "grabbed"
    THROW = "throw"
    GRAB_RELEASE = "grab_release"
    LEDGE_HANG = "ledge_hang"
    LEDGE_GETUP = "ledge_getup"
    LEDGE_ATTACK = "ledge_attack"
    LEDGE_ROLL = "ledge_roll"
    LEDGE_TRUMPED = "ledge_trumped"
    TECH = "tech"
    TECH_ROLL = "tech_roll"
    WALL_TECH = "wall_tech"
    GETUP_ROLL = "getup_roll"
    REVIVAL = "revival"
    KO = "ko"


class GroundKind(IntEnum):
    """What a fighter is standing on."""

    NONE = 0
    """Airborne."""
    CELL = 1
    """The top of a solid stage cell."""
    PLATFORM = 2
    """A soft platform deck (``Fighter.platform`` says which)."""
    REVIVAL = 3
    """The revival platform after a KO: not part of the stage, and nothing moves you off it."""


NO_PARTNER = -1
NO_LEDGE = -1


@dataclass(frozen=True, slots=True)
class Launch:
    """A hit waiting to send its target flying when hitlag ends (DI is read at that moment)."""

    knockback: float
    heading: Vec2
    """Horizontal launch direction before DI, a unit world vector."""
    elevation: float
    """Launch elevation in degrees, already resolved (Sakurai angle, meteor bounce)."""
    tumble: bool
    carry: Vec3 = ZERO3
    """Extra velocity added to the launch: the attacker's own, for autolink hits that drag
    the target along with a moving attacker."""


def _no_hits() -> dict[tuple[int, int], int]:
    return {}


def _no_centres() -> dict[int, Vec3]:
    return {}


def _empty_queue() -> list[str]:
    return []


@dataclass(slots=True)
class Fighter:
    """One fighter's complete runtime state."""

    player_index: int
    character: CharacterDef
    pos: Vec3
    """Feet position: ``x``, ``y`` on the ground plane, ``z`` up."""
    facing: Dir8
    vel: Vec3 = ZERO3
    """Self velocity: movement the fighter controls (walk, run, jump, drift)."""
    kb_vel: Vec3 = ZERO3
    """Knockback velocity, kept separate as in Smash. Decays every frame."""
    state: StateId = StateId.IDLE
    state_frame: int = 1
    """Frames in the current state, 1-indexed: the tick a state is entered is its frame 1."""
    ground: GroundKind = GroundKind.CELL
    platform: int = NO_PLATFORM
    """Index of the soft platform stood on, when ``ground`` is ``PLATFORM``."""
    drop_platform: int = NO_PLATFORM
    """Soft platform being dropped through: it cannot be landed on until the feet clear it."""
    air_jumps_left: int = 0
    fast_falling: bool = False
    drive: Vec2 = ZERO2
    """Unit ground direction of the current dash, run or run turnaround."""
    damage: float = 0.0
    stocks: int | None = None
    """Stocks left, or ``None`` for infinite."""
    invincible_frames: int = 0
    """Frames of invincibility left after leaving the revival platform."""
    land_lag: int = 0
    """Length of the current landing lag (normal, or an aerial's own)."""
    move_id: str = ""
    """The move being performed while in the ``ATTACK`` state."""
    charge_frames: int = 0
    """Frames the current smash attack has been charged."""
    hit_log: dict[tuple[int, int], int] = field(default_factory=_no_hits)
    """``(target, hitbox group)`` to the move frame it last hit, for the current move."""
    move_connected: bool = False
    move_stale: float = 1.0
    """Stale-move damage multiplier of the current move, fixed when the move starts."""
    """Whether the current move has already been added to the stale queue."""
    hitbox_centres: dict[int, Vec3] = field(default_factory=_no_centres)
    """World centres of last tick's active hitboxes by id, to sweep fast moves."""
    hitlag: int = 0
    """Freeze frames left: while above 0 the fighter does not step or move."""
    hitstun: int = 0
    """Frames left before a hit fighter can act."""
    launch: Launch | None = None
    """The hit that launches this fighter when its hitlag ends."""
    sdi_mult: float = 1.0
    stale_queue: list[str] = field(default_factory=_empty_queue)
    """The last moves that connected, newest first (at most ``STALE_QUEUE_LENGTH``)."""
    last_knockback: float = 0.0
    """Knockback of the last hit taken, for the debug panel."""
    shield_hp: float = SHIELD_MAX_HP
    intangible_frames: int = 0
    """Frames left during which nothing can hit or grab the fighter (dodges, ledge, tech)."""
    stun_frames: int = 0
    """Frames left of shieldstun, dizziness or ledge-trump lag (whichever state is active)."""
    air_dodge_used: bool = False
    """One air dodge per airtime."""
    dodge_dir: Vec3 = ZERO3
    """Direction of the current air dodge (zero for a neutral one)."""
    dodge_stale: int = 0
    """Recent dodges: each one adds end lag to the next."""
    dodge_stale_timer: int = 0
    dodge_lag: int = 0
    """Extra end lag of the current dodge, from staling."""
    grab_partner: int = NO_PARTNER
    """Player index of the fighter being held, or holding this one."""
    grab_timer: int = 0
    """Frames left before a held fighter breaks free (counted on the grabber)."""
    pummel_cooldown: int = 0
    throw_id: str = ""
    """The throw being performed while in the ``THROW`` state."""
    ledge: int = NO_LEDGE
    """Index of the stage ledge line being hung from or climbed."""
    ledge_point: Vec2 = ZERO2
    """The point on that ledge line."""
    ledge_cooldown: int = 0
    """Frames before a ledge can be grabbed again."""
    ledge_grabs: int = 0
    """Ledge grabs since last touching the ground or being launched."""
    air_frames: int = 0
    """Frames since last standing on the ground."""
    tech_window: int = 0
    """Frames left in which touching ground or a wall techs."""
    tech_lockout: int = 0
    last_hit_by: int = NO_PARTNER
    """Player index of the last fighter that hit this one (for KO credit), or -1."""
    last_hit_timer: int = 0
    combo_hits: int = 0
    """Hits taken in a row without becoming able to act."""
    combo_by: int = NO_PARTNER
    counter_damage: float = 0.0
    """Damage the current move deals at least (set when it is the reply of a counter)."""
    air_moves_used: list[str] = field(default_factory=_empty_queue)
    """Once-per-airtime moves already used since last touching the ground or a ledge."""
    buffer: InputBuffer = field(default_factory=InputBuffer)

    @property
    def entity_id(self) -> int:
        """Unique and stable id for rendering: the player index."""
        return self.player_index

    @property
    def grounded(self) -> bool:
        """Whether the fighter is standing on something."""
        return self.ground is not GroundKind.NONE

    @property
    def in_play(self) -> bool:
        """Whether the fighter exists in the world (false while KO'd and waiting to respawn)."""
        return self.state is not StateId.KO

    @property
    def move(self) -> MoveDef | None:
        """The move being performed, or ``None`` when not attacking."""
        if self.state is not StateId.ATTACK:
            return None
        return self.character.moves[self.move_id]

    @property
    def invincible(self) -> bool:
        """Whether hits currently do no damage or knockback."""
        return self.invincible_frames > 0 or self.ground is GroundKind.REVIVAL

    @property
    def intangible(self) -> bool:
        """Whether hits and grabs pass through the fighter right now."""
        return self.intangible_frames > 0

    @property
    def on_revival_platform(self) -> bool:
        """Whether the fighter is standing on the revival platform."""
        return self.ground is GroundKind.REVIVAL

    @property
    def eliminated(self) -> bool:
        """Whether the fighter is out of stocks."""
        return self.stocks is not None and self.stocks <= 0
