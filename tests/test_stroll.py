"""The strollers: the scripted input of the fighters on the menus' island (decision D-072,
M21 group 2). Pure: no window, a real sim.
"""

from isofightr.ai.stroll import TAUNT_REST, WALK_TILT, Doing, Stroller
from isofightr.data.character_loader import load_character
from isofightr.scenes.menu_world_model import STROLL_BOUNDS, Bounds, load_isle
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, Button
from isofightr.sim.match import Match, MatchRules

ROSTER = ("rook", "bramble", "zephyr", "mote")
SLACK = 0.6
"""How far past the plaza's edge a fighter may slide to a stop (tiles)."""
NEVER = int(
    Button.JUMP | Button.ATTACK | Button.SPECIAL | Button.STRONG | Button.GRAB | Button.SHIELD
)
"""Buttons a stroller must never hold."""


def stroll(ticks: int, seed: int = 0) -> tuple[Match, list[Stroller], set[StateId], set[Doing]]:
    match = Match.create(
        load_isle(), [load_character(name) for name in ROSTER], rules=MatchRules(stocks=None)
    )
    strollers = [Stroller(seed * 16 + index, STROLL_BOUNDS) for index in range(len(ROSTER))]
    wide = Bounds(
        STROLL_BOUNDS.depth_min - SLACK,
        STROLL_BOUNDS.depth_max + SLACK,
        STROLL_BOUNDS.across_min - SLACK,
        STROLL_BOUNDS.across_max + SLACK,
    )
    states: set[StateId] = set()
    doings: set[Doing] = set()
    for _ in range(ticks):
        inputs = [
            stroller.think(fighter.pos.x, fighter.pos.y)
            for stroller, fighter in zip(strollers, match.fighters, strict=True)
        ]
        for frame in inputs:
            assert frame.held & NEVER == 0
            assert frame.move.length() <= WALK_TILT + 1e-9
        match.tick(inputs)
        for stroller, fighter in zip(strollers, match.fighters, strict=True):
            assert wide.holds(fighter.pos.x, fighter.pos.y), (fighter.character.id, fighter.pos)
            assert fighter.pos.z == 0.0, "nobody leaves the ground"
            assert fighter.damage == 0.0
            states.add(fighter.state)
            doings.add(stroller.doing)
            if fighter.state is StateId.ATTACK:
                assert fighter.move_id == fighter.character.moveset.taunt, "only ever a taunt"
    return match, strollers, states, doings


def test_strollers_stay_on_the_plaza_for_a_long_time() -> None:
    match, _, states, doings = stroll(20000)
    assert all(stats.falls == 0 for stats in match.stats), "nobody was lost"
    assert doings == set(Doing), "they stand, walk, turn, crouch and taunt"
    assert {StateId.IDLE, StateId.WALK, StateId.CROUCH, StateId.ATTACK} <= states
    assert not states & {StateId.JUMP, StateId.FALL, StateId.DASH, StateId.RUN}


def test_a_stroll_is_the_same_every_time_for_a_seed() -> None:
    first, _, _, _ = stroll(1500, seed=3)
    again, _, _, _ = stroll(1500, seed=3)
    other, _, _, _ = stroll(1500, seed=4)
    assert first.state_hash() == again.state_hash()
    assert first.state_hash() != other.state_hash()


def test_strollers_do_not_all_do_the_same_thing() -> None:
    match, _, _, _ = stroll(900)
    spots = {(round(fighter.pos.x, 1), round(fighter.pos.y, 1)) for fighter in match.fighters}
    assert len(spots) == len(ROSTER)
    assert len({fighter.facing for fighter in match.fighters}) > 1


def test_a_stroller_put_off_the_plaza_walks_back() -> None:
    stroller = Stroller(1, STROLL_BOUNDS)
    middle = STROLL_BOUNDS.point(0.5, 0.5)
    outside = STROLL_BOUNDS.point(0.5, 0.5)[0] - 9.0, middle[1] + 9.0
    assert not STROLL_BOUNDS.holds(*outside)
    frame = stroller.think(*outside)
    assert stroller.doing is Doing.WALK and stroller.goal == middle
    assert frame.held == int(Button.WALK)
    heading = (middle[0] - outside[0], middle[1] - outside[1])
    assert frame.move.x * heading[0] + frame.move.y * heading[1] > 0, "toward the middle"


def test_a_crouch_holds_down_and_a_taunt_is_a_short_press() -> None:
    stroller = Stroller(5, STROLL_BOUNDS)
    x, y = STROLL_BOUNDS.point(0.5, 0.5)
    seen_crouch = seen_taunt = 0
    taunt_run = longest = 0
    for _ in range(6000):
        frame = stroller.think(x, y)
        if stroller.doing is Doing.CROUCH:
            assert frame.vertical == VERTICAL_DOWN
            seen_crouch += 1
        if frame.held & int(Button.TAUNT):
            seen_taunt += 1
            taunt_run += 1
            longest = max(longest, taunt_run)
        else:
            taunt_run = 0
    assert seen_crouch and seen_taunt
    assert longest <= 3 and TAUNT_REST > 30, "a tap, then time for the animation"
