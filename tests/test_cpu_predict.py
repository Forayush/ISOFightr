"""Tests for the CPU's predictions (plan note "15 - CPU AI", decision D-071): where a
fighter can be over the coming frames, each kind compared with what the real sim then does.
"""

from collections.abc import Callable

import pytest

from helpers import place
from isofightr.ai import predict
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.view import FighterView, view_fighter
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as combat
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, VERTICAL_UP, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.states.base import change_state
from isofightr.sim.states.interrupts import start_move

GRID = load_stage("training_grid")
SE = Dir8.SE.world
EXACT = 0.02


def fresh(first: str = "rook", second: str = "rook") -> tuple[Match, Fighter, Fighter]:
    """Two fighters on Training Grid: the first in the middle, the second in its reach."""
    characters = [load_character(first), load_character(second)]
    match = Match.create(GRID, characters, rules=MatchRules(stocks=None))
    one, two = match.fighters
    place(match, one, 5.0, 6.0, facing=Dir8.SE)
    place(match, two, 5.0 + SE.x * 0.9, 6.0 + SE.y * 0.9, facing=Dir8.NW)
    return match, one, two


def track_of(match: Match, fighter: Fighter, frames: int = 60) -> predict.Track:
    view = view_fighter(fighter)
    return predict.track(
        match.stage, view, fighter.character, knowledge_for(fighter.character), frames
    )


def options_of(match: Match, fighter: Fighter) -> dict[str, predict.Option]:
    view = view_fighter(fighter)
    found = predict.options(match.stage, view, fighter.character, knowledge_for(fighter.character))
    if found:
        assert sum(option.weight for option in found) == pytest.approx(1.0)
    return {option.name: option for option in found}


def play_on(
    match: Match, fighter: Fighter, frames: int, first: InputFrame = NEUTRAL_INPUT
) -> list[tuple[Vec3, FighterView]]:
    """Tick with ``first`` on the first tick for ``fighter`` and nothing after; return where
    it was and how it looked after each tick."""
    seen = []
    for index in range(frames):
        inputs = [NEUTRAL_INPUT] * len(match.fighters)
        if index == 0:
            inputs[fighter.player_index] = first
        match.tick(inputs)
        seen.append((fighter.pos, view_fighter(fighter)))
    return seen


def first_free(seen: list[tuple[Vec3, FighterView]]) -> int:
    return next(index + 1 for index, (_, view) in enumerate(seen) if view.free)


def assert_follows(
    track: predict.Track, seen: list[tuple[Vec3, FighterView]], upto: int, slack: float = EXACT
) -> None:
    for index in range(min(upto, len(seen))):
        point, spread = track.at(index + 1)
        assert (seen[index][0] - point).length() <= spread + slack, f"frame {index + 1}"


def launched(move: str, percent: float) -> tuple[Match, Fighter]:
    """A Rook hit by another Rook's move: frozen in hitlag with the launch pending."""
    match, striker, victim = fresh()
    victim.damage = percent
    start_move(match, striker, move)
    for _ in range(60):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if victim.launch is not None:
            return match, victim
    raise AssertionError(f"{move} never hit")


# --- tracks -------------------------------------------------------------------------------


def test_a_jump_follows_its_arc_and_lands() -> None:
    match, jumper, other = fresh()
    place(match, other, 10.0, 2.0)
    for _ in range(12):
        match.tick([InputFrame(move=SE, held=int(Button.JUMP)), NEUTRAL_INPUT])
    assert jumper.state is StateId.JUMP
    track = track_of(match, jumper, 70)
    assert track.locked == 0 and track.spread[20] > track.spread[5] > 0.0
    seen = play_on(match, jumper, 70)
    landed = next(index for index, (_, view) in enumerate(seen) if view.grounded)
    for index in range(landed):
        assert (seen[index][0] - track.points[index]).length() <= EXACT, f"frame {index + 1}"
    assert track.points[-1].z == pytest.approx(0.0), "it comes down onto the stage"


@pytest.mark.parametrize(
    ("move", "percent", "slack"),
    [
        ("fsmash", 80.0, EXACT),
        ("usmash", 60.0, EXACT),
        ("dtilt", 20.0, EXACT),
        ("ftilt", 30.0, 0.15),
    ],
)
def test_a_launch_is_predicted_from_the_hit_and_from_the_middle_of_the_flight(
    move: str, percent: float, slack: float
) -> None:
    match, victim = launched(move, percent)
    wait = victim.hitlag
    track = track_of(match, victim, 50)
    assert track.locked > wait and track.sure(wait + 1) and not track.sure(track.locked + 1)
    assert track.spread[wait - 1] == 0.0, "frozen until the hitlag ends"
    assert track.spread[min(wait + 20, 49)] > 0.0, "then as wide as DI could make it"
    seen = play_on(match, victim, 50)
    for index in range(min(track.locked, 50)):
        assert (seen[index][0] - track.points[index]).length() <= slack, f"frame {index + 1}"

    match, victim = launched(move, percent)
    play_on(match, victim, wait + 6)
    if victim.hitstun > 0:
        track = track_of(match, victim, 40)
        assert track.locked == victim.hitstun
        assert_follows(track, play_on(match, victim, 40), track.locked, slack)


@pytest.mark.parametrize(
    ("character", "move"),
    [("rook", "dash_attack"), ("rook", "sspecial"), ("zephyr", "sspecial"), ("bramble", "fsmash")],
)
def test_an_attacker_follows_its_move_until_it_is_free(character: str, move: str) -> None:
    match, attacker, other = fresh(character)
    place(match, other, 10.0, 2.0)
    start_move(match, attacker, move)
    play_on(match, attacker, 3)
    track = track_of(match, attacker, 70)
    seen = play_on(match, attacker, 70)
    assert track.locked == first_free(seen)
    assert_follows(track, seen, track.locked)
    assert track.spread[track.locked - 1] == 0.0 < track.spread[track.locked + 5]


def test_a_free_fighter_on_the_ground_stays_inside_a_growing_disc() -> None:
    match, runner, other = fresh()
    place(match, other, 10.0, 2.0)
    still = track_of(match, runner, 30)
    assert still.locked == 0 and still.points[-1] == runner.pos
    assert still.spread == tuple(sorted(still.spread)) and still.spread[0] > 0.0
    for _ in range(20):
        match.tick([InputFrame(move=SE), NEUTRAL_INPUT])
    assert runner.state is StateId.RUN
    track = track_of(match, runner, 30)
    assert_follows(track, play_on(match, runner, 30), 30), "letting go: it skids to a stop"
    match, runner, other = fresh()
    place(match, other, 10.0, 2.0)
    for _ in range(20):
        match.tick([InputFrame(move=SE), NEUTRAL_INPUT])
    track = track_of(match, runner, 30)
    seen = []
    for _ in range(30):
        match.tick([InputFrame(move=SE), NEUTRAL_INPUT])
        seen.append((runner.pos, view_fighter(runner)))
    assert_follows(track, seen, 30, slack=0.1), "running on: still inside the disc"


def test_a_fighter_in_landing_lag_is_locked_for_what_is_left_of_it() -> None:
    match, jumper, other = fresh()
    place(match, other, 10.0, 2.0)
    match.tick([InputFrame(held=int(Button.JUMP)), NEUTRAL_INPUT])
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if jumper.state is StateId.LAND:
            break
    assert jumper.state is StateId.LAND
    track = track_of(match, jumper, 20)
    seen = play_on(match, jumper, 20)
    assert abs(track.locked - (first_free(seen) - 1)) <= 1
    assert track.spread[0] == 0.0


# --- fixed menus --------------------------------------------------------------------------


def lying_down() -> tuple[Match, Fighter, Vec2]:
    match, fighter, other = fresh()
    place(match, other, 10.0, 2.0)
    place(match, fighter, 3.0, 6.0)
    change_state(match, fighter, StateId.KNOCKDOWN)
    play_on(match, fighter, combat.KNOCKDOWN_LOCK_FRAMES + 5)
    assert fighter.state is StateId.KNOCKDOWN
    inward = (match.stage.respawn - fighter.pos.xy).normalized()
    return match, fighter, inward


@pytest.mark.parametrize(
    ("name", "state"),
    [
        ("stand", StateId.GETUP),
        ("attack", StateId.ATTACK),
        ("roll in", StateId.GETUP_ROLL),
        ("roll out", StateId.GETUP_ROLL),
    ],
)
def test_each_getup_option_ends_where_and_when_the_sim_says(name: str, state: StateId) -> None:
    match, fighter, inward = lying_down()
    option = options_of(match, fighter)[name]
    pressed: dict[str, Callable[[], InputFrame]] = {
        "stand": lambda: InputFrame(vertical=VERTICAL_UP),
        "attack": lambda: InputFrame(held=int(Button.ATTACK)),
        "roll in": lambda: InputFrame(move=inward),
        "roll out": lambda: InputFrame(move=inward * -1.0),
    }
    seen = play_on(match, fighter, 70, pressed[name]())
    assert seen[3][1].state is state
    assert option.free == first_free(seen)
    assert (seen[option.free - 1][0] - option.track.at(option.free)[0]).length() <= EXACT
    assert option.track.locked == option.free
    assert seen[option.intangible - 2][1].intangible or option.intangible == 0


def hanging() -> tuple[Match, Fighter]:
    match, fighter, other = fresh()
    place(match, other, 10.0, 2.0)
    place(match, fighter, -0.6, 6.0, z=-1.0, facing=Dir8.SE)
    for _ in range(60):
        match.tick([InputFrame(move=Vec2(1.0, 0.0)), NEUTRAL_INPUT])
        if fighter.state is StateId.LEDGE_HANG:
            break
    assert fighter.state is StateId.LEDGE_HANG
    play_on(match, fighter, combat.LEDGE_ACTION_DELAY + 4)
    return match, fighter


@pytest.mark.parametrize(
    ("name", "press", "state"),
    [
        ("getup", InputFrame(vertical=VERTICAL_UP), StateId.LEDGE_GETUP),
        ("roll", InputFrame(held=int(Button.SHIELD)), StateId.LEDGE_ROLL),
        ("attack", InputFrame(held=int(Button.ATTACK)), StateId.LEDGE_ATTACK),
    ],
)
def test_each_ledge_option_ends_where_and_when_the_sim_says(
    name: str, press: InputFrame, state: StateId
) -> None:
    match, fighter = hanging()
    option = options_of(match, fighter)[name]
    seen = play_on(match, fighter, 80, press)
    assert seen[3][1].state is state
    assert option.free == first_free(seen)
    assert (seen[option.free - 1][0] - option.track.at(option.free)[0]).length() <= EXACT


def test_the_ledge_jump_and_the_drop_leave_at_once() -> None:
    match, fighter = hanging()
    found = options_of(match, fighter)
    assert set(found) == {"getup", "roll", "attack", "jump", "drop"}
    jump = found["jump"]
    seen = play_on(match, fighter, 30, InputFrame(held=int(Button.JUMP)))
    assert seen[2][1].state is StateId.JUMP
    for index in range(1, 30):
        point, spread = jump.track.at(index + 1)
        assert (seen[index][0] - point).length() <= spread + 0.1, f"frame {index + 1}"
    drop = found["drop"]
    assert drop.track.points[20].z < fighter.pos.z - 1.0 and drop.intangible == 0


def test_a_tumbling_fighter_over_ground_faces_the_tech_menu() -> None:
    match, victim = launched("usmash", 60.0)
    assert options_of(match, victim) == {}, "still frozen: no menu yet"
    play_on(match, victim, victim.hitlag + 10)
    assert victim.state is StateId.TUMBLE
    found = options_of(match, victim)
    assert set(found) == {"tech", "tech in", "tech out", "miss"}
    landing = found["tech"].track.points[0]
    assert landing.z == pytest.approx(0.0)
    reach_in = (found["tech in"].track.points[-1] - landing).length()
    reach_out = (found["tech out"].track.points[-1] - landing).length()
    assert reach_in == pytest.approx(combat.TECH_ROLL_DISTANCE) == pytest.approx(reach_out)
    away = found["tech out"].track.points[-1] - found["tech in"].track.points[-1]
    assert away.length() == pytest.approx(2 * combat.TECH_ROLL_DISTANCE)
    assert found["miss"].intangible == 0 < found["tech"].intangible
    seen = play_on(match, victim, 120)
    down = next(position for position, view in seen if view.state is StateId.KNOCKDOWN)
    assert (down - landing).length() <= 0.1, "it comes down where the menu was laid out"


def test_someone_who_can_act_freely_has_no_menu() -> None:
    match, fighter, _other = fresh()
    assert options_of(match, fighter) == {}
    track = track_of(match, fighter, 10)
    assert track.at(0) == track.at(1) and track.at(99) == track.at(10), "clamped at both ends"
