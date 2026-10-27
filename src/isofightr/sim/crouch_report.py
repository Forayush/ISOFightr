"""Which non-aerial moves can hit a standing and a crouching target, from the real sim.

Plan note "16 - Testing Debug and Tooling" (``crouch_report.py``, decision D-069). Each move
(and the standing and dash grabs) is performed on the stage's respawn point; the other
fighter is parked behind the attacker and made intangible, so nothing is hit and nothing
freezes. Every tick the volumes the attacker has out (hitboxes, its grab box, its own
projectiles) are tested against still capsules of the same character, standing and crouching,
at each distance in front of it. A target is reached **first** when a volume of the move's
first hitbox window (a grab's box; a move without windows: its projectiles) touches it, and
**later** when only a later window, a follow-up move or a projectile does.

D-069's balance guard: the actions in :data:`GUARD_SLOTS` must reach a crouching target first
at every distance where they reach a standing one first.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from isofightr.sim.character_def import CharacterDef, HurtboxDef
from isofightr.sim.combat.grab import grab_box
from isofightr.sim.combat.hitbox import active_hitboxes, hurtbox_capsule
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Capsule, Vec3, capsules_overlap
from isofightr.sim.move_def import MoveKind
from isofightr.sim.stage import Stage
from isofightr.sim.states.base import change_state
from isofightr.sim.states.interrupts import start_move

SCANNED_KINDS: Final[tuple[MoveKind, ...]] = (
    MoveKind.JAB,
    MoveKind.TILT,
    MoveKind.DASH_ATTACK,
    MoveKind.SMASH,
    MoveKind.SPECIAL,
)
DEFAULT_DISTANCES: Final[tuple[float, ...]] = (1.0, 1.5)
"""How far in front of the attacker the targets stand, in units."""
DEFAULT_CROUCH_SHARE: Final[float] = 0.62
"""D-069's first crouch capsule: its top at this share of the standing height above ``z0``."""
GRABS: Final[tuple[str, ...]] = ("grab", "dash_grab")
GUARD_SLOTS: Final[tuple[str, ...]] = (
    "jab1",
    "ftilt",
    "dtilt",
    "dash_attack",
    "fsmash",
    "dsmash",
    *GRABS,
)
"""What must still reach a crouching target (D-069). ``jab1`` is the first jab."""
FACING: Final[Dir8] = Dir8.SE
PARK_DISTANCE: Final[float] = 4.0
"""How far behind the attacker the other fighter is parked."""
SCAN_TICKS: Final[int] = 240
"""A move that is not over by this tick is cut off."""
STANDING: Final[str] = "stand"
CROUCHING: Final[str] = "crouch"
POSES: Final[tuple[str, ...]] = (STANDING, CROUCHING)


class Reach(Enum):
    """How a move reaches one target."""

    FIRST = "yes"
    """With its first hitbox window."""
    LATER = "later"
    """Only with a later window, a follow-up or a projectile."""
    NONE = "-"


type Target = tuple[float, str]
"""A target: its distance in front of the attacker and its pose (``stand`` or ``crouch``)."""


@dataclass(frozen=True, slots=True)
class CrouchRow:
    """What one action reaches."""

    action: str
    """A move id, ``grab`` or ``dash_grab``."""
    guarded: bool
    """Whether D-069's guard list holds it to reaching a crouching target."""
    reach: Mapping[Target, Reach]
    top: float
    """The highest point its volumes reach above the attacker's feet, in units (0 if none)."""

    def reaches(self, distance: float, pose: str) -> bool:
        """Return whether the action reaches the target at all."""
        return self.reach[(distance, pose)] is not Reach.NONE

    @property
    def passes_over(self) -> tuple[float, ...]:
        """The distances where it reaches a standing target but not a crouching one."""
        distances = sorted({distance for distance, _ in self.reach})
        return tuple(
            distance
            for distance in distances
            if self.reaches(distance, STANDING) and not self.reaches(distance, CROUCHING)
        )

    @property
    def loses_first(self) -> tuple[float, ...]:
        """The distances where its first window reaches a standing target but not a
        crouching one."""
        distances = sorted({distance for distance, _ in self.reach})
        return tuple(
            distance
            for distance in distances
            if self.reach[(distance, STANDING)] is Reach.FIRST
            and self.reach[(distance, CROUCHING)] is not Reach.FIRST
        )

    @property
    def guard_failure(self) -> bool:
        """Whether a guarded action loses a crouching target its first window should reach."""
        return self.guarded and bool(self.loses_first)


def crouch_shape(standing: HurtboxDef, share: float = DEFAULT_CROUCH_SHARE) -> HurtboxDef:
    """Return a crouch capsule like ``standing`` (same radius and ``z0``) whose top is at
    ``share`` of the standing height above ``z0``, never lower than a sphere."""
    top = standing.z0 + share * (standing.z1 - standing.z0)
    return HurtboxDef(standing.radius, standing.z0, max(top, standing.z0 + 2 * standing.radius))


def guarded_actions(character: CharacterDef) -> dict[str, str]:
    """Return the action of each guard slot (``jab1`` is the first jab)."""
    moveset = character.moveset
    slots = {
        "jab1": moveset.jab[0],
        "ftilt": moveset.ftilt,
        "dtilt": moveset.dtilt,
        "dash_attack": moveset.dash_attack,
        "fsmash": moveset.fsmash,
        "dsmash": moveset.dsmash,
    }
    return slots | {grab: grab for grab in GRABS}


def scanned_actions(character: CharacterDef) -> list[str]:
    """Return the moves the report covers (sorted by id), then the grabs."""
    moves = sorted(
        move_id for move_id, move in character.moves.items() if move.kind in SCANNED_KINDS
    )
    return [*moves, *GRABS]


def scan_action(
    stage: Stage,
    character: CharacterDef,
    action: str,
    crouch: HurtboxDef,
    distances: Sequence[float] = DEFAULT_DISTANCES,
) -> CrouchRow:
    """Return what ``action`` reaches: targets of ``character`` standing (its hurtbox) and
    crouching (``crouch``) at each of ``distances`` in front of it."""
    match = Match.create(stage, [character, character], rules=MatchRules(stocks=None))
    attacker, parked = match.fighters
    spot = stage.respawn
    top = stage.surface_top(spot.x, spot.y)
    assert top is not None, "the attacker must stand on solid ground"
    attacker.pos = Vec3(spot.x, spot.y, top)
    attacker.facing = FACING
    behind = spot - FACING.world * PARK_DISTANCE
    parked.pos = Vec3(behind.x, behind.y, stage.surface_top(behind.x, behind.y) or top)
    parked.intangible_frames = SCAN_TICKS + 1
    shapes = {STANDING: character.body.hurtbox, CROUCHING: crouch}
    targets: dict[Target, Capsule] = {}
    for distance in distances:
        ahead = spot + FACING.world * distance
        for pose, shape in shapes.items():
            targets[(distance, pose)] = hurtbox_capsule(Vec3(ahead.x, ahead.y, top), shape)

    grab = action in GRABS
    move = None if grab else character.moves[action]
    first_window = None
    if move is not None and move.windows:
        first_window = min(move.windows, key=lambda window: window.frames.first)
    if grab:
        change_state(match, attacker, StateId.GRAB if action == "grab" else StateId.DASH_GRAB)
    else:
        start_move(match, attacker, action)

    reach = dict.fromkeys(targets, Reach.NONE)
    highest = 0.0
    for _ in range(SCAN_TICKS):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        first: list[Capsule] = []
        later: list[Capsule] = []
        if grab:
            box = grab_box(attacker)
            if box is not None:
                first.append(box)
        elif attacker.state is StateId.ATTACK:
            volumes = [box.volume for box in active_hitboxes(attacker)]
            in_first = (
                first_window is not None
                and attacker.move_id == action
                and attacker.state_frame in first_window.frames
            )
            (first if in_first else later).extend(volumes)
        shots = [shot.volume for shot in match.projectiles if shot.owner == attacker.player_index]
        (first if first_window is None and not grab else later).extend(shots)
        for volume in (*first, *later):
            highest = max(highest, max(volume.start.z, volume.end.z) + volume.radius - top)
        for key, target in targets.items():
            if any(capsules_overlap(volume, target) for volume in first):
                reach[key] = Reach.FIRST
            elif reach[key] is Reach.NONE and any(
                capsules_overlap(volume, target) for volume in later
            ):
                reach[key] = Reach.LATER
        if attacker.state is StateId.IDLE and match.frame > 2 and not shots:
            break
    guarded = action in guarded_actions(character).values()
    return CrouchRow(action, guarded, reach, highest)


def scan(
    stage: Stage,
    character: CharacterDef,
    crouch: HurtboxDef | None = None,
    distances: Sequence[float] = DEFAULT_DISTANCES,
    actions: Sequence[str] | None = None,
) -> list[CrouchRow]:
    """Return a row for every move the report covers (or ``actions``), with ``crouch`` as
    the crouching capsule (default: D-069's first value)."""
    shape = crouch or crouch_shape(character.body.hurtbox)
    return [
        scan_action(stage, character, action, shape, distances)
        for action in (actions or scanned_actions(character))
    ]


def table(rows: Sequence[CrouchRow], distances: Sequence[float] = DEFAULT_DISTANCES) -> list[str]:
    """Return the rows as a text table (``*`` marks D-069's guard list)."""
    heads = [f"{distance:g} {pose}" for distance in distances for pose in POSES]
    lines = ["  move           " + "".join(f"{head:>11}" for head in heads) + "  top z"]
    for row in rows:
        cells = "".join(
            f"{row.reach[(distance, pose)].value:>11}" for distance in distances for pose in POSES
        )
        mark = "*" if row.guarded else " "
        lines.append(f"  {mark}{row.action:<14}{cells}  {row.top:5.2f}")
    return lines


def findings(rows: Sequence[CrouchRow]) -> list[str]:
    """Return a line for every row that loses a crouching target, worst first."""
    lines = []
    for row in rows:
        if row.guard_failure:
            where = ", ".join(f"{distance:g}" for distance in row.loses_first)
            lines.append(f"GUARD {row.action}: its first window misses a crouch at {where}")
    for row in rows:
        if row.passes_over:
            where = ", ".join(f"{distance:g}" for distance in row.passes_over)
            lines.append(f"passes over a crouch: {row.action} at {where}")
        elif row.loses_first and not row.guard_failure:
            where = ", ".join(f"{distance:g}" for distance in row.loses_first)
            lines.append(f"first window misses a crouch: {row.action} at {where}")
    return lines
