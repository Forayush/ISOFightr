"""Scenario-test helpers: build a match, script inputs, run it (plan note 16, "Test helpers").

A scenario test scripts ``InputFrame``s against a real ``Match`` and asserts on the outcome,
which is how every gameplay mechanic is tested.
"""

from collections.abc import Sequence

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame, stick_to_world
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import ZERO2, ZERO3, Vec2, Vec3
from isofightr.sim.rng import Rng
from isofightr.sim.stage import NO_PLATFORM, Stage, build_stage

type Direction = Dir8 | tuple[float, float] | None


def make_match(
    stage: str | Stage = "training_grid",
    fighters: Sequence[str] = ("rook", "rook"),
    seed: int = 1,
    stocks: int | None = 3,
) -> Match:
    """Create a match on a stage (by id, or an already built ``Stage``)."""
    built = load_stage(stage) if isinstance(stage, str) else stage
    characters = [load_character(character_id) for character_id in fighters]
    return Match.create(built, characters, seed=seed, rules=MatchRules(stocks=stocks))


def make_stage(
    rows: Sequence[str], platforms: Sequence[tuple[int, int, int, int, float]] = ()
) -> Stage:
    """Build a small synthetic stage from grid rows; spawns sit on the first solid cell."""
    from isofightr.sim.stage import SoftPlatform

    cy, cx = next((y, x) for y, row in enumerate(rows) for x, s in enumerate(row) if s != ".")
    spawn = Vec2(cx + 0.5, cy + 0.5)
    return build_stage(
        id="test",
        display_name="Test",
        tileset="grid",
        grid_rows=list(rows),
        legend={},
        soft_platforms=[SoftPlatform(*platform) for platform in platforms],
        spawns=[spawn] * 4,
        respawn=spawn,
        blast_side=7.0,
        blast_top=14.0,
        blast_bottom=-8.0,
        camera_margin=4.0,
    )


def world_direction(direction: Direction, magnitude: float = 1.0) -> Vec2:
    """Turn a ``Dir8`` or a screen-relative stick ``(u, v)`` into a world move vector."""
    if direction is None:
        return ZERO2
    if isinstance(direction, Dir8):
        return direction.world * magnitude
    return stick_to_world(direction[0], direction[1]).normalized() * magnitude


def hold(
    direction: Direction = None,
    buttons: int = 0,
    frames: int = 10,
    vertical: int = 0,
    magnitude: float = 1.0,
) -> list[InputFrame]:
    """Return ``frames`` identical input frames: a direction and/or buttons held."""
    frame = InputFrame(
        move=world_direction(direction, magnitude), vertical=vertical, held=int(buttons)
    )
    return [frame] * frames


def neutral(frames: int = 1) -> list[InputFrame]:
    """Return ``frames`` frames of no input."""
    return [NEUTRAL_INPUT] * frames


def run(
    match: Match,
    p1_inputs: Sequence[InputFrame],
    p2_inputs: Sequence[InputFrame] | None = None,
) -> Match:
    """Tick the match once per P1 frame. Other players (and a short P2 list) get neutral."""
    for index, frame in enumerate(p1_inputs):
        frames = [NEUTRAL_INPUT] * len(match.fighters)
        frames[0] = frame
        if p2_inputs is not None and index < len(p2_inputs) and len(frames) > 1:
            frames[1] = p2_inputs[index]
        match.tick(frames)
    return match


def run_until(match: Match, fighter: Fighter, state: StateId, limit: int = 600) -> int:
    """Tick with neutral input until ``fighter`` reaches ``state``; return the ticks taken."""
    for ticks in range(limit + 1):
        if fighter.state is state:
            return ticks
        match.tick([NEUTRAL_INPUT] * len(match.fighters))
    raise AssertionError(f"never reached {state} within {limit} ticks (now {fighter.state})")


def place(
    match: Match,
    fighter: Fighter,
    x: float,
    y: float,
    z: float | None = None,
    facing: Dir8 = Dir8.SE,
    damage: float = 0.0,
) -> None:
    """Teleport a fighter and reset its motion.

    With ``z`` omitted the fighter stands on whatever is highest under ``(x, y)``. With ``z``
    given it stands there if a surface is at exactly that height, and is airborne otherwise.
    """
    stage = match.stage
    surfaces = [platform.z for platform in stage.soft_platforms if platform.contains(x, y)]
    top = stage.surface_top(x, y)
    if top is not None:
        surfaces.append(top)
    height = max(surfaces) if z is None else z
    fighter.pos = Vec3(x, y, height)
    fighter.vel = ZERO3
    fighter.kb_vel = ZERO3
    fighter.drive = ZERO2
    fighter.facing = facing
    fighter.damage = damage
    fighter.fast_falling = False
    fighter.drop_platform = NO_PLATFORM
    fighter.air_jumps_left = fighter.character.movement.air_jumps
    fighter.state_frame = 1
    fighter.platform = NO_PLATFORM
    if height in surfaces:
        on_platform = [
            index
            for index, platform in enumerate(stage.soft_platforms)
            if platform.contains(x, y) and platform.z == height
        ]
        fighter.ground = GroundKind.PLATFORM if on_platform else GroundKind.CELL
        fighter.platform = on_platform[0] if on_platform else NO_PLATFORM
        fighter.state = StateId.IDLE
    else:
        fighter.ground = GroundKind.NONE
        fighter.state = StateId.FALL


def random_inputs(seed: int, frames: int, players: int = 2) -> list[list[InputFrame]]:
    """Return ``frames`` ticks of plausible random input for every player.

    Deterministic for a given seed (it uses the sim's own PRNG, not Python's ``random``).
    Each player holds directions for a while and taps jump and the vertical modifiers now
    and then, which exercises walks, dashes, runs, turns, skids, jumps, fast falls, platform
    drops, KOs and respawns while still spending most of the time on the ground.
    """
    rng = Rng.seeded(seed)
    directions: list[Vec2] = [ZERO2] * players
    walking = [False] * players
    jump_frames = [0] * players
    vertical_frames = [0] * players
    verticals = [0] * players
    ticks: list[list[InputFrame]] = []
    for _ in range(frames):
        tick: list[InputFrame] = []
        for player in range(players):
            if rng.below(25) == 0:
                choice = rng.below(len(Dir8) + 4)
                directions[player] = Dir8(choice).world if choice < len(Dir8) else ZERO2
            if rng.below(90) == 0:
                walking[player] = not walking[player]
            if jump_frames[player] > 0:
                jump_frames[player] -= 1
            elif rng.below(50) == 0:
                jump_frames[player] = rng.between(1, 10)
            if vertical_frames[player] > 0:
                vertical_frames[player] -= 1
            elif rng.below(40) == 0:
                vertical_frames[player] = rng.between(1, 8)
                verticals[player] = -1 if rng.below(3) else 1
            held = (Button.JUMP if jump_frames[player] else 0) | (
                Button.WALK if walking[player] else 0
            )
            vertical = verticals[player] if vertical_frames[player] else 0
            tick.append(InputFrame(move=directions[player], vertical=vertical, held=held))
        ticks.append(tick)
    return ticks
