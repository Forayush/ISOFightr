"""Move knowledge, built automatically by performing every move in a private simulation.

Plan note "15 - CPU AI" ("Move knowledge (auto-built)"). For each thing a CPU can do (a jab,
a short-hop forward air, an up special in the air, a grab...) this module plays the exact
inputs the CPU would send, alone on a large flat test stage, and records frame by frame:
where the fighter's own feet went, which hitboxes, grab boxes and projectiles were out (as
spheres), when the move was over, and whether it ended helpless. Everything is stored in the
fighter's local frame (forward, left, up) relative to where it started, so at run time a CPU
only rotates and offsets the recording to ask "would this hit there?".

Because the recording runs the real sim, scripted specials, scripted motion, jump arcs,
projectiles and landing lag are all measured, and a new character needs no hand tuning. The
recording never touches a live match.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from functools import cache
from typing import Final

from isofightr.ai.view import view_fighter
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat.hitbox import active_hitboxes, local_to_world
from isofightr.sim.combat.knockback import knockback
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import (
    NEUTRAL_INPUT,
    VERTICAL_DOWN,
    VERTICAL_NONE,
    VERTICAL_UP,
    Button,
    Dir8,
    InputFrame,
)
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.move_def import HitboxDef
from isofightr.sim.stage import Stage, build_stage

RECORD_FRAMES: Final[int] = 150
"""Longest a recording runs (projectiles are followed until they are gone or this ends)."""
ARENA_SIZE: Final[int] = 41
"""Cells per side of the flat test stage: wide enough that nothing reaches an edge."""
ARENA_BLAST: Final[float] = 30.0
AIR_START_JUMP_FRAMES: Final[int] = 12
"""Jump is held this long to reach the apex an air action is recorded from."""
FACING: Final[Dir8] = Dir8.SE
"""Every recording starts facing this way; it defines the local frame."""
REFERENCE_PERCENT: Final[float] = 100.0
"""Percent at which moves are compared by knockback."""


class Start(Enum):
    """Where an action can be started from."""

    GROUND = "ground"
    AIR = "air"


class Stick(Enum):
    """A stick direction relative to the fighter's facing."""

    NONE = "none"
    FORWARD = "forward"
    BACK = "back"


@dataclass(frozen=True, slots=True)
class Step:
    """Input held for some frames, in local terms."""

    buttons: int = 0
    stick: Stick = Stick.NONE
    vertical: int = VERTICAL_NONE
    frames: int = 1
    cstick: bool = False
    """Flick the right stick along ``stick`` instead of moving the left stick."""


@dataclass(frozen=True, slots=True)
class Sphere:
    """Something dangerous: a hitbox, a grab box or a projectile, in local space."""

    centre: Vec3
    radius: float
    grab: bool = False
    projectile: bool = False


@dataclass(frozen=True, slots=True)
class HitFrame:
    """The spheres out on one frame of an action (frame 1 is the first input's tick)."""

    frame: int
    spheres: tuple[Sphere, ...]


@dataclass(frozen=True, slots=True)
class Action:
    """One thing a CPU can do, with its recorded geometry and timing."""

    name: str
    start: Start
    steps: tuple[Step, ...]
    move_id: str
    """The move it performs ("" for a grab)."""
    turns: bool
    """It faces the stick when it starts, so it can be aimed in any of 8 directions."""
    path: tuple[Vec3, ...]
    """The fighter's feet offset after each frame (index 0 = frame 1), in local space."""
    hit_frames: tuple[HitFrame, ...]
    move_start: int
    """Action frame on which the move's own frame 1 falls (after a jumpsquat, for example)."""
    commit: int
    """First action frame on which the fighter is free again (``RECORD_FRAMES`` if never)."""
    helpless: bool
    damage: float
    knockback_100: float
    """Knockback of its strongest hit on a 100-weight target at ``REFERENCE_PERCENT``."""
    strongest: HitboxDef | None
    grab: bool = False
    projectile: bool = False

    @property
    def first_hit(self) -> int:
        """First action frame with anything out (0 if it never has)."""
        return self.hit_frames[0].frame if self.hit_frames else 0

    @property
    def last_hit(self) -> int:
        """Last action frame with anything out."""
        return self.hit_frames[-1].frame if self.hit_frames else 0

    def offset_at(self, frame: int) -> Vec3:
        """The feet offset after ``frame`` (clamped to the recording)."""
        if not self.path:
            return Vec3(0.0, 0.0, 0.0)
        return self.path[min(max(frame, 1), len(self.path)) - 1]


@dataclass(frozen=True, slots=True)
class CharacterKnowledge:
    """Everything a CPU knows about one character's options."""

    character_id: str
    actions: tuple[Action, ...]
    ground_by_move: dict[str, Action] = field(default_factory=dict)
    air_by_move: dict[str, Action] = field(default_factory=dict)
    up_special: Action | None = None
    """The up special performed in the air, aimed forward and up: the recovery move."""
    full_hop_rise: float = 0.0
    air_jump_rise: float = 0.0
    jump_distance: float = 0.0
    """How far a full hop plus an air jump carries, landing back at the starting height."""
    projectile_reach: float = 0.0
    """How far ahead its longest-reaching projectile hits, in units (0 = none)."""

    def action(self, name: str) -> Action:
        """Return an action by name."""
        for candidate in self.actions:
            if candidate.name == name:
                return candidate
        raise KeyError(name)

    @property
    def up_special_rise(self) -> float:
        """Height the up special gains at best (from its recording)."""
        if self.up_special is None or not self.up_special.path:
            return 0.0
        return max(0.0, max(offset.z for offset in self.up_special.path))

    @property
    def up_special_reach(self) -> float:
        """Forward distance the up special covers by the time it peaks."""
        action = self.up_special
        if action is None or not action.path:
            return 0.0
        peak = max(range(len(action.path)), key=lambda index: action.path[index].z)
        return max(0.0, action.path[peak].x)


def _f(buttons: int = 0, **values: object) -> Step:
    return Step(buttons=buttons, **values)  # type: ignore[arg-type]


def _ground_recipes(jumpsquat: int) -> list[tuple[str, tuple[Step, ...], bool]]:
    """Return (name, steps, aimable) for everything started from the ground."""
    fwd, back = Stick.FORWARD, Stick.BACK
    attack, strong, special = Button.ATTACK, Button.STRONG, Button.SPECIAL
    hold = jumpsquat + 1
    """Stick and modifier are held until takeoff, where the aerial reads them."""
    recipes: list[tuple[str, tuple[Step, ...], bool]] = [
        ("jab", (_f(attack),), False),
        ("ftilt", (_f(attack, stick=fwd),), True),
        ("utilt", (_f(attack, vertical=VERTICAL_UP),), False),
        ("dtilt", (_f(attack, vertical=VERTICAL_DOWN),), False),
        ("dash_attack", (_f(stick=fwd), _f(attack, stick=fwd)), True),
        ("fsmash", (_f(strong, stick=fwd),), True),
        ("usmash", (_f(strong, vertical=VERTICAL_UP),), False),
        ("dsmash", (_f(strong, vertical=VERTICAL_DOWN),), False),
        ("grab", (_f(Button.GRAB),), False),
        ("dash_grab", (_f(stick=fwd), _f(Button.GRAB, stick=fwd)), True),
        ("nspecial", (_f(special),), False),
        ("sspecial", (_f(special, stick=fwd),), True),
        ("uspecial", (_f(special, vertical=VERTICAL_UP),), False),
        ("dspecial", (_f(special, vertical=VERTICAL_DOWN),), False),
    ]
    # Short hop: jump tapped for one frame together with the attack; works with or without
    # the short-hop macro rule. The stick and modifier stay held until takeoff.
    sh_jump = Button.JUMP | attack
    recipes += [
        ("sh_nair", (_f(sh_jump), _f(frames=hold)), False),
        ("sh_fair", (_f(sh_jump, stick=fwd), _f(stick=fwd, frames=hold)), False),
        ("sh_bair", (_f(sh_jump, stick=back), _f(stick=back, frames=hold)), False),
        (
            "sh_uair",
            (_f(sh_jump, vertical=VERTICAL_UP), _f(vertical=VERTICAL_UP, frames=hold)),
            False,
        ),
        (
            "sh_dair",
            (_f(sh_jump, vertical=VERTICAL_DOWN), _f(vertical=VERTICAL_DOWN, frames=hold)),
            False,
        ),
    ]
    # Full hop with the aerial right after takeoff (against airborne or higher targets).
    rise = _f(Button.JUMP, frames=hold)
    fh_attack = Button.JUMP | attack
    recipes += [
        ("fh_nair", (rise, _f(fh_attack)), False),
        ("fh_fair", (rise, _f(fh_attack, stick=fwd)), False),
        ("fh_bair", (rise, _f(fh_attack, stick=back)), False),
        ("fh_uair", (rise, _f(fh_attack, vertical=VERTICAL_UP)), False),
    ]
    return recipes


def _air_recipes() -> list[tuple[str, tuple[Step, ...], bool]]:
    """Return (name, steps, aimable) for everything started in the air."""
    fwd, back = Stick.FORWARD, Stick.BACK
    attack, special = Button.ATTACK, Button.SPECIAL
    up, down = VERTICAL_UP, VERTICAL_DOWN
    return [
        ("air_nair", (_f(attack),), False),
        ("air_fair", (_f(attack, stick=fwd),), False),
        ("air_bair", (_f(attack, stick=back),), False),
        ("air_uair", (_f(attack, vertical=up),), False),
        ("air_dair", (_f(attack, vertical=down),), False),
        ("air_nspecial", (_f(special),), False),
        ("air_sspecial", (_f(special, stick=fwd),), True),
        ("air_dspecial", (_f(special, vertical=down),), False),
        # The recovery: aimed forward and up, held for the whole move.
        (
            "air_uspecial",
            (_f(special, stick=fwd, vertical=up), _f(stick=fwd, vertical=up, frames=60)),
            False,
        ),
    ]


def frames_for(steps: Sequence[Step], facing: Vec2) -> list[InputFrame]:
    """Turn local steps into world ``InputFrame``s for a fighter facing ``facing``."""
    frames = []
    for step in steps:
        direction = Vec2(0.0, 0.0)
        if step.stick is Stick.FORWARD:
            direction = facing
        elif step.stick is Stick.BACK:
            direction = facing * -1.0
        if step.cstick:
            frame = InputFrame(vertical=step.vertical, held=int(step.buttons), cstick=direction)
        else:
            frame = InputFrame(move=direction, vertical=step.vertical, held=int(step.buttons))
        frames += [frame] * step.frames
    return frames


@cache
def arena() -> Stage:
    """A large flat stage with nothing near the middle."""
    row = "0" * ARENA_SIZE
    middle = ARENA_SIZE / 2
    spawns = [
        Vec2(middle - 6.0, middle),
        Vec2(middle + 6.0, middle),
        Vec2(middle, middle - 6.0),
        Vec2(middle, middle + 6.0),
    ]
    return build_stage(
        id="cpu_arena",
        display_name="CPU arena",
        tileset="grid",
        grid_rows=[row] * ARENA_SIZE,
        legend={},
        soft_platforms=[],
        spawns=spawns,
        respawn=Vec2(middle, middle),
        blast_side=ARENA_BLAST,
        blast_top=ARENA_BLAST,
        blast_bottom=-ARENA_BLAST,
        camera_margin=1.0,
    )


def _fresh(character: CharacterDef, airborne: bool) -> tuple[Match, Fighter]:
    """A private match with the character standing in the middle (or at a jump's apex)."""
    stage = arena()
    match = Match.create(stage, [character], seed=0, rules=MatchRules(stocks=None))
    fighter = match.fighters[0]
    middle = ARENA_SIZE / 2
    fighter.pos = Vec3(middle, middle, 0.0)
    fighter.facing = FACING
    if airborne:
        match.tick([InputFrame(held=int(Button.JUMP))] * 1)
        for _ in range(AIR_START_JUMP_FRAMES - 1):
            match.tick([InputFrame(held=int(Button.JUMP))])
        while fighter.vel.z > 0.0:
            match.tick([NEUTRAL_INPUT])
    return match, fighter


def _to_local(offset: Vec3, facing: Vec2) -> Vec3:
    left = facing.perpendicular_left()
    return Vec3(
        offset.x * facing.x + offset.y * facing.y, offset.x * left.x + offset.y * left.y, offset.z
    )


def _spheres(match: Match, fighter: Fighter, start: Vec3, facing: Vec2) -> tuple[Sphere, ...]:
    spheres = [
        Sphere(_to_local(box.centre - start, facing), box.definition.radius)
        for box in active_hitboxes(fighter)
    ]
    grabs = fighter.character.grabs
    for state, grab in ((StateId.GRAB, grabs.standing), (StateId.DASH_GRAB, grabs.dash)):
        if fighter.state is state and fighter.state_frame in grab.frames:
            centre = local_to_world(fighter.pos, fighter.facing.world, grab.offset)
            spheres.append(Sphere(_to_local(centre - start, facing), grab.radius, grab=True))
    for projectile in match.projectiles:
        if projectile.alive and projectile.owner == fighter.player_index:
            spheres.append(
                Sphere(
                    _to_local(projectile.pos - start, facing),
                    projectile.hitbox.radius,
                    projectile=True,
                )
            )
    return tuple(spheres)


@dataclass(slots=True)
class _Recording:
    path: list[Vec3] = field(default_factory=list)
    hit_frames: list[HitFrame] = field(default_factory=list)
    move_start: int = 0
    commit: int = RECORD_FRAMES
    helpless: bool = False
    final_facing: Dir8 = FACING
    move_id: str = ""


def _record(character: CharacterDef, steps: Sequence[Step], start: Start) -> _Recording:
    match, fighter = _fresh(character, airborne=start is Start.AIR)
    origin = fighter.pos
    facing = FACING.world
    inputs = frames_for(steps, facing)
    recording = _Recording()
    started = False
    for frame in range(1, RECORD_FRAMES + 1):
        match.tick([inputs[frame - 1] if frame <= len(inputs) else NEUTRAL_INPUT])
        recording.path.append(_to_local(fighter.pos - origin, facing))
        spheres = _spheres(match, fighter, origin, facing)
        if spheres:
            recording.hit_frames.append(HitFrame(frame, spheres))
        if fighter.state in (StateId.ATTACK, StateId.GRAB, StateId.DASH_GRAB):
            if not started:
                recording.move_start = frame - fighter.state_frame + 1
                recording.move_id = fighter.move_id if fighter.state is StateId.ATTACK else ""
                recording.final_facing = fighter.facing
            started = True
        if fighter.state is StateId.HELPLESS:
            recording.helpless = True
        if started and recording.commit == RECORD_FRAMES and view_fighter(fighter).free:
            recording.commit = frame
        owned = any(p.alive and p.owner == fighter.player_index for p in match.projectiles)
        if recording.commit < RECORD_FRAMES and not owned:
            break
    return recording


def _strength(character: CharacterDef, move_id: str) -> tuple[float, float, HitboxDef | None]:
    """Return (largest damage, knockback of the strongest hit at 100%, that hitbox)."""
    move = character.moves.get(move_id)
    if move is None:
        return 0.0, 0.0, None
    boxes: list[HitboxDef] = [box for window in move.windows for box in window.hitboxes]
    boxes += [projectile.hitbox for projectile in move.projectiles]
    best: tuple[float, float, HitboxDef | None] = (0.0, 0.0, None)
    for box in boxes:
        kb = knockback(REFERENCE_PERCENT + box.damage, box.damage, 100.0, box.bkb, box.kbg, box.fkb)
        if kb > best[1]:
            best = (max(best[0], box.damage), kb, box)
        else:
            best = (max(best[0], box.damage), best[1], best[2])
    return best


def _throw_strength(character: CharacterDef) -> tuple[float, float]:
    throws = character.grabs
    damage = max(t.damage for t in (throws.forward, throws.back, throws.up, throws.down))
    kb = max(
        knockback(REFERENCE_PERCENT + t.damage, t.damage, 100.0, t.bkb, t.kbg)
        for t in (throws.forward, throws.back, throws.up, throws.down)
    )
    return damage, kb


def _rise(character: CharacterDef, vz: float) -> float:
    """Height gained by a jump with initial speed ``vz`` (gravity applies before moving)."""
    stats = character.movement
    height, speed = 0.0, vz
    while True:
        speed -= stats.gravity
        if speed <= 0.0:
            return height
        height += speed


def _rising_frames(character: CharacterDef, vz: float) -> int:
    frames, speed = 0, vz
    while speed - character.movement.gravity > 0.0:
        speed -= character.movement.gravity
        frames += 1
    return frames


def _jump_distance(character: CharacterDef) -> float:
    """Horizontal distance of a full hop and an air jump at the apex, back to the start height."""
    stats = character.movement
    frames = _rising_frames(character, stats.full_hop_vz)
    frames += _rising_frames(character, stats.double_jump_vz)
    height = _rise(character, stats.full_hop_vz) + _rise(character, stats.double_jump_vz)
    speed = 0.0
    while height > 0.0:
        speed = min(speed + stats.gravity, stats.max_fall)
        height -= speed
        frames += 1
    return frames * stats.air_speed


def _build(character: CharacterDef) -> CharacterKnowledge:
    actions: list[Action] = []
    recipes = [(r, Start.GROUND) for r in _ground_recipes(character.movement.jumpsquat)]
    recipes += [(r, Start.AIR) for r in _air_recipes()]
    for (name, steps, aimable), start in recipes:
        recording = _record(character, steps, start)
        turns = False
        if aimable:
            backwards = tuple(
                Step(
                    s.buttons,
                    Stick.BACK if s.stick is Stick.FORWARD else s.stick,
                    s.vertical,
                    s.frames,
                    s.cstick,
                )
                for s in steps
            )
            turns = _record(character, backwards, start).final_facing is not FACING
        grab = name in ("grab", "dash_grab")
        if grab:
            damage, kb = _throw_strength(character)
            strongest = None
        else:
            damage, kb, strongest = _strength(character, recording.move_id)
        hit_frames = tuple(recording.hit_frames)
        projectile = any(s.projectile for f in hit_frames for s in f.spheres)
        actions.append(
            Action(
                name=name,
                start=start,
                steps=steps,
                move_id=recording.move_id,
                turns=turns,
                path=tuple(recording.path),
                hit_frames=hit_frames,
                move_start=recording.move_start,
                commit=recording.commit,
                helpless=recording.helpless,
                damage=damage,
                knockback_100=kb,
                strongest=strongest,
                grab=grab,
                projectile=projectile,
            )
        )
    ground_by_move: dict[str, Action] = {}
    air_by_move: dict[str, Action] = {}
    for action in actions:
        if not action.move_id:
            continue
        table = ground_by_move if action.start is Start.GROUND else air_by_move
        if action.name.startswith(("sh_", "fh_")):
            table = air_by_move  # an aerial seen in the air is closest to the air recording
            if action.move_id in table:
                continue
        table.setdefault(action.move_id, action)
    reach = 0.0
    for action in actions:
        for hit_frame in action.hit_frames:
            for sphere in hit_frame.spheres:
                if sphere.projectile:
                    reach = max(reach, sphere.centre.x + sphere.radius)
    stats = character.movement
    up_special = next(a for a in actions if a.name == "air_uspecial")
    return CharacterKnowledge(
        character_id=character.id,
        actions=tuple(actions),
        ground_by_move=ground_by_move,
        air_by_move=air_by_move,
        up_special=up_special if up_special.move_id else None,
        full_hop_rise=_rise(character, stats.full_hop_vz),
        air_jump_rise=_rise(character, stats.double_jump_vz),
        jump_distance=_jump_distance(character),
        projectile_reach=reach,
    )


_CACHE: dict[str, tuple[CharacterDef, CharacterKnowledge]] = {}


def knowledge_for(character: CharacterDef) -> CharacterKnowledge:
    """Return (and cache) what a CPU knows about a character. Reloaded character data
    (a new ``CharacterDef``) is recorded again."""
    cached = _CACHE.get(character.id)
    if cached is not None and cached[0] is character:
        return cached[1]
    built = _build(character)
    _CACHE[character.id] = (character, built)
    return built
