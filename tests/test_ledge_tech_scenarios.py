"""Scenario tests for ledges, teching, wall bounces and the getup options.

Plan note "06 - Shield Dodge Grab and Ledge" ("Ledges", "Teching and knockdown"), and the M4
exit criterion: a player can recover to and from ledges on every edge of Sky Ruins.
"""

import pytest

from helpers import hold, make_match, make_stage, neutral, place, run, run_until
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as c
from isofightr.sim.events import HitEvent, LedgeGrabEvent, TechEvent, WallBounceEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, Dir8, InputFrame
from isofightr.sim.match import Match
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.states import change_state
from isofightr.sim.states.interrupts import start_move
from isofightr.sim.states.ledge import (
    find_ledge,
    hang_position,
    ledge_intangible_frames,
    roll_inset,
)

ROOK = load_character("rook")
Y = 6.0
WEST = Vec2(-1.0, 0.0)
"""Outward normal of the Training Grid's x = 0 edge, used by most tests here."""


def hanging(damage: float = 0.0) -> tuple[Match, Fighter]:
    """Return a match with P1 hanging from the west edge of the Training Grid."""
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, -0.4, Y, z=-0.5, damage=damage)
    run(match, neutral(1))
    assert fighter.state is StateId.LEDGE_HANG
    return match, fighter


def wait_for_options(match: Match) -> None:
    run(match, neutral(c.LEDGE_ACTION_DELAY))


def events_of(match: Match, kind: type) -> list:  # type: ignore[type-arg]
    return [event for event in match.events if isinstance(event, kind)]


# --- catching a ledge ---------------------------------------------------------------------


def test_a_falling_fighter_catches_a_nearby_ledge() -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, -0.4, Y, z=1.0, facing=Dir8.NW)
    fighter.air_jumps_left = 0
    fighter.air_dodge_used = True
    ticks = run_until(match, fighter, StateId.LEDGE_HANG, limit=60)
    assert ticks > 5, "not before the feet are below the ledge"
    [event] = events_of(match, LedgeGrabEvent)
    assert (event.player, event.trumped) == (0, None)
    ledge = match.stage.ledges[fighter.ledge]
    assert ledge.normal == WEST and fighter.ledge_point == Vec2(0.0, Y)
    assert fighter.pos == hang_position(ledge, fighter.ledge_point)
    assert fighter.pos == Vec3(-c.LEDGE_HANG_OUT, Y, -c.LEDGE_HANG_BELOW)
    assert fighter.facing is Dir8.SE, "faces the stage"
    assert fighter.vel == ZERO3 and not fighter.grounded
    assert fighter.air_jumps_left == 1 and not fighter.air_dodge_used
    assert fighter.intangible
    run(match, neutral(100))
    assert fighter.pos == Vec3(-c.LEDGE_HANG_OUT, Y, -c.LEDGE_HANG_BELOW), "it just hangs"


def test_ledge_intangibility_shrinks_with_air_time_and_damage() -> None:
    _, fighter = hanging()
    assert fighter.intangible_frames == 64 - 1  # one tick has passed since the grab
    fighter.ledge_grabs, fighter.air_frames, fighter.damage = 0, 200, 100.0
    assert ledge_intangible_frames(fighter) == 64 - 20 - 10
    fighter.air_frames = 5000
    assert ledge_intangible_frames(fighter) == c.LEDGE_INTANGIBLE_MIN
    fighter.ledge_grabs = 1
    assert ledge_intangible_frames(fighter) == 0


@pytest.mark.parametrize(
    "case", ["rising", "away", "holding_down", "hitstun", "too_far", "too_low"]
)
def test_when_a_ledge_is_not_caught(case: str) -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, -0.4, Y, z=-0.5)
    frame = neutral(1)
    if case == "rising":
        fighter.vel = Vec3(0.0, 0.0, 0.2)
        change_state(match, fighter, StateId.JUMP)
    elif case == "away":
        fighter.vel = Vec3(-0.06, 0.0, 0.0)
    elif case == "holding_down":
        frame = hold(frames=1, vertical=VERTICAL_DOWN)
    elif case == "hitstun":
        change_state(match, fighter, StateId.TUMBLE)
        fighter.hitstun = 30
    elif case == "too_far":
        place(match, fighter, -0.4 - c.LEDGE_REACH, Y, z=-0.5)
    else:
        place(match, fighter, -0.4, Y, z=-2.5)
    run(match, frame)
    assert fighter.state is not StateId.LEDGE_HANG


def test_walking_off_an_edge_does_not_grab_it_but_jumping_back_does() -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, 0.5, Y, facing=Dir8.NW)
    run(match, hold(Dir8.NW, Button.WALK, frames=20))
    assert fighter.state is StateId.FALL and fighter.pos.x < -0.3, "moving away: no grab"
    run(match, hold(Dir8.SE, Button.JUMP, frames=1))
    assert fighter.state is StateId.DOUBLE_JUMP
    for _ in range(80):
        if fighter.state is StateId.LEDGE_HANG or fighter.grounded:
            break
        run(match, hold(Dir8.SE, frames=1))
    # Depending on the height it catches the ledge or lands on the stage: both recover.
    assert fighter.state is StateId.LEDGE_HANG or fighter.grounded


def test_a_dropped_ledge_cannot_be_regrabbed_at_once_and_regrabs_are_not_intangible() -> None:
    match, fighter = hanging()
    wait_for_options(match)
    run(match, hold(frames=1, vertical=VERTICAL_DOWN))
    assert fighter.state is StateId.FALL and not fighter.intangible
    assert fighter.ledge_cooldown == c.LEDGE_REGRAB_COOLDOWN
    # Jump back up next to the ledge and fall onto it again.
    run(match, neutral(3) + hold(buttons=Button.JUMP, frames=1))
    assert fighter.state is StateId.DOUBLE_JUMP
    run_until(match, fighter, StateId.LEDGE_HANG, limit=120)
    assert fighter.ledge_grabs == 2 and not fighter.intangible


def test_hanging_too_long_lets_go() -> None:
    match, fighter = hanging()
    run(match, neutral(c.LEDGE_MAX_HANG - 1))
    assert fighter.state is StateId.LEDGE_HANG
    run(match, neutral(1))
    assert fighter.state is StateId.FALL


def test_a_hanging_fighter_can_be_hit_off_once_its_intangibility_ends() -> None:
    match, fighter = hanging()
    attacker = match.fighters[1]
    place(match, attacker, 0.7, Y, facing=Dir8.NW)
    start_move(match, attacker, "dtilt")
    run(match, neutral(30))
    assert fighter.damage == 0 and fighter.state is StateId.LEDGE_HANG, "intangible"
    fighter.intangible_frames = 0
    start_move(match, attacker, "dtilt")
    run(match, neutral(30))
    assert fighter.damage > 0 and fighter.state is not StateId.LEDGE_HANG
    assert fighter.ledge_grabs == 0, "being hit earns a fresh intangible grab"


# --- ledge options ------------------------------------------------------------------------


def test_inputs_held_while_catching_the_ledge_do_not_pick_an_option() -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, -0.6, Y, z=-0.5)
    run(match, hold(Dir8.SE, frames=60))
    assert fighter.state is StateId.LEDGE_HANG


def test_neutral_getup_climbs_onto_the_stage() -> None:
    for frame in (hold(Dir8.SE, frames=1), hold(frames=1, vertical=VERTICAL_UP)):
        match, fighter = hanging()
        wait_for_options(match)
        run(match, frame)
        assert fighter.state is StateId.LEDGE_GETUP
        run(match, neutral(c.LEDGE_GETUP_FRAMES - 1))
        assert fighter.state is StateId.LEDGE_GETUP and fighter.intangible_frames <= 1
        assert -c.LEDGE_HANG_BELOW < fighter.pos.z <= 0.0, "on its way up"
        run(match, neutral(1))
        assert fighter.state is StateId.IDLE and fighter.grounded
        assert fighter.pos == Vec3(c.LEDGE_GETUP_INSET, Y, 0.0)
        run(match, hold(Dir8.SE, frames=10))
        assert fighter.pos.x > c.LEDGE_GETUP_INSET, "and can walk away"


def test_ledge_drop() -> None:
    match, fighter = hanging()
    wait_for_options(match)
    run(match, hold(Dir8.NW, frames=1))
    assert fighter.state is StateId.FALL
    run(match, neutral(20))
    assert fighter.pos.z < -c.LEDGE_HANG_BELOW - 1.0


def test_ledge_jump_keeps_the_air_jump() -> None:
    match, fighter = hanging()
    wait_for_options(match)
    run(match, hold(buttons=Button.JUMP, frames=1))
    assert fighter.state is StateId.JUMP and fighter.air_jumps_left == 1
    assert fighter.intangible
    run(match, hold(Dir8.SE, frames=45))
    run_until(match, fighter, StateId.IDLE, limit=100)
    assert fighter.pos.x > 0.0 and fighter.pos.z == 0.0


def test_ledge_roll_goes_further_in_and_stops_where_the_ground_ends() -> None:
    match, fighter = hanging()
    wait_for_options(match)
    run(match, hold(buttons=Button.SHIELD, frames=1))
    assert fighter.state is StateId.LEDGE_ROLL
    run(match, neutral(c.LEDGE_ROLL_FRAMES))
    assert fighter.state is StateId.IDLE and fighter.grounded
    assert (fighter.pos.x, fighter.pos.y, fighter.pos.z) == pytest.approx(
        (c.LEDGE_ROLL_DISTANCE, Y, 0.0)
    )

    narrow = make_stage(["0", "0", "0"])
    [west] = [ledge for ledge in narrow.ledges if ledge.normal == WEST]
    inset = roll_inset(narrow, west, Vec2(0.0, 1.5))
    assert c.LEDGE_GETUP_INSET <= inset < 1.0


def test_ledge_attack_climbs_and_hits() -> None:
    match, fighter = hanging()
    target = match.fighters[1]
    place(match, target, 1.5, Y, facing=Dir8.NW)
    wait_for_options(match)
    run(match, hold(buttons=Button.ATTACK, frames=1))
    assert fighter.state is StateId.LEDGE_ATTACK
    hits = []
    for _ in range(40):
        run(match, neutral(1))
        hits.extend(events_of(match, HitEvent))
    assert [hit.move_id for hit in hits] == ["ledge_attack"]
    assert target.damage == pytest.approx(9 * c.FRESH_BONUS)
    assert fighter.grounded


# --- trump --------------------------------------------------------------------------------


def test_grabbing_an_occupied_ledge_trumps_the_occupant() -> None:
    match, first = hanging()
    second = match.fighters[1]
    place(match, second, -0.4, Y + 0.3, z=-0.5)
    run(match, neutral(1))
    [event] = events_of(match, LedgeGrabEvent)
    assert (event.player, event.trumped) == (1, 0)
    assert second.state is StateId.LEDGE_HANG and first.state is StateId.LEDGE_TRUMPED
    assert not first.intangible
    jump = hold(buttons=Button.JUMP, frames=1)
    run(match, [*jump, *neutral(1)] * (c.LEDGE_TRUMP_FRAMES // 2 - 1))
    assert first.state is StateId.LEDGE_TRUMPED and first.pos.x < -c.LEDGE_HANG_OUT
    run(match, neutral(2) + jump)
    assert first.state is StateId.DOUBLE_JUMP


def test_two_fighters_can_share_a_ledge_line_when_far_enough_apart() -> None:
    match, first = hanging()
    second = match.fighters[1]
    place(match, second, -0.4, Y + c.LEDGE_OCCUPIED_DISTANCE + 0.2, z=-0.5)
    run(match, neutral(1))
    assert first.state is second.state is StateId.LEDGE_HANG


# --- every edge of Sky Ruins ----------------------------------------------------------------

SKY_RUINS = load_stage("sky_ruins")


@pytest.mark.parametrize("index", range(len(SKY_RUINS.ledges)))
def test_every_sky_ruins_ledge_can_be_caught_and_climbed(index: int) -> None:
    """M4 exit criterion: recover to and from ledges on every edge of Sky Ruins."""
    match = make_match(SKY_RUINS, stocks=None)
    fighter = match.fighters[0]
    ledge = SKY_RUINS.ledges[index]
    middle = (ledge.start + ledge.end) / 2
    outside = middle + ledge.normal * 0.45
    place(match, fighter, outside.x, outside.y, z=ledge.z + 0.5)
    assert find_ledge(SKY_RUINS, fighter) is None, "still above the ledge"
    run_until(match, fighter, StateId.LEDGE_HANG, limit=60)
    assert fighter.ledge == index
    assert SKY_RUINS.surface_top(fighter.pos.x, fighter.pos.y) is None, "hangs over the void"
    wait_for_options(match)
    inward = ledge.normal * -1.0
    toward = next(d for d in Dir8 if d.world.dot(inward) > 0.99)
    run(match, hold(toward, frames=1) + neutral(c.LEDGE_GETUP_FRAMES))
    assert fighter.state is StateId.IDLE and fighter.grounded
    assert SKY_RUINS.surface_top(fighter.pos.x, fighter.pos.y) == ledge.z == fighter.pos.z
    run(match, neutral(30))
    assert fighter.state is StateId.IDLE, "stable on the stage"


@pytest.mark.parametrize("index", range(len(SKY_RUINS.ledges)))
def test_every_sky_ruins_ledge_can_be_reached_with_the_air_jump(index: int) -> None:
    """Knocked off the stage and below it: the air jump brings a fighter back to the ledge."""
    match = make_match(SKY_RUINS, stocks=None)
    fighter = match.fighters[0]
    ledge = SKY_RUINS.ledges[index]
    middle = (ledge.start + ledge.end) / 2
    outside = middle + ledge.normal * 1.2
    place(match, fighter, outside.x, outside.y, z=ledge.z - 3.8)  # the jump peaks below the top
    inward = ledge.normal * -1.0
    toward = next(d for d in Dir8 if d.world.dot(inward) > 0.99)
    run(match, hold(toward, Button.JUMP, frames=1))
    assert fighter.state is StateId.DOUBLE_JUMP
    for _ in range(120):
        if fighter.state is StateId.LEDGE_HANG:
            break
        run(match, hold(toward, frames=1))
    assert fighter.state is StateId.LEDGE_HANG
    caught = SKY_RUINS.ledges[fighter.ledge]
    # At a corner the neighbouring line may be the nearer one; either is a recovery.
    assert fighter.ledge == index or (caught.start - middle).length() <= 1.5


# --- tech ---------------------------------------------------------------------------------


def tumbling(height: float = 1.0, stage: object = "training_grid") -> tuple[Match, Fighter]:
    """Return a match with P1 tumbling in hitstun, falling from ``height``."""
    match = make_match(stage, stocks=None)  # type: ignore[arg-type]
    fighter = match.fighters[0]
    place(match, fighter, 6.0, Y, z=height)
    change_state(match, fighter, StateId.TUMBLE)
    fighter.hitstun = 200
    return match, fighter


def ticks_to_land(height: float = 1.0) -> int:
    match, fighter = tumbling(height)
    return run_until(match, fighter, StateId.KNOCKDOWN, limit=300)


SHIELD = hold(buttons=Button.SHIELD, frames=1)


@pytest.mark.parametrize(
    ("early", "teched"), [(1, True), (c.TECH_WINDOW, True), (c.TECH_WINDOW + 1, False)]
)
def test_tech_window(early: int, teched: bool) -> None:
    landing = ticks_to_land()
    match, fighter = tumbling()
    events = []
    for frame in neutral(landing - early) + SHIELD + neutral(early - 1):
        run(match, [frame])
        events.extend(events_of(match, TechEvent))
    assert fighter.grounded
    assert (fighter.state is StateId.TECH) is teched
    assert (fighter.state is StateId.KNOCKDOWN) is not teched
    assert len(events) == int(teched)
    if teched:
        assert fighter.intangible and fighter.hitstun == 0
        run(match, neutral(c.TECH_FRAMES))
        assert fighter.state is StateId.IDLE


def test_mashing_shield_does_not_tech() -> None:
    landing = ticks_to_land(3.0)
    match, fighter = tumbling(3.0)
    # A press 30 frames before landing starts the lockout; the well-timed second one is lost.
    run(match, neutral(landing - 30) + SHIELD + neutral(24) + SHIELD + neutral(4))
    assert fighter.state is StateId.KNOCKDOWN


@pytest.mark.parametrize("direction", [Dir8.SE, Dir8.N, Dir8.W])
def test_tech_roll(direction: Dir8) -> None:
    landing = ticks_to_land()
    match, fighter = tumbling()
    run(
        match,
        neutral(landing - 3) + hold(direction, Button.SHIELD, frames=1) + hold(direction, frames=2),
    )
    assert fighter.state is StateId.TECH_ROLL
    start = fighter.pos
    run(match, neutral(c.TECH_ROLL_FRAMES))
    assert fighter.state is StateId.IDLE
    moved = fighter.pos - start
    expected = direction.world * c.TECH_ROLL_DISTANCE
    assert (moved.x, moved.y) == pytest.approx((expected.x, expected.y))


def test_a_shield_press_after_hitstun_is_an_air_dodge_not_a_tech() -> None:
    match, fighter = tumbling(6.0)
    fighter.hitstun = 2
    run(match, neutral(3) + SHIELD)
    assert fighter.state is StateId.AIR_DODGE


# --- walls --------------------------------------------------------------------------------

WALL_ROWS = ["0000004", "0000004", "0000004"]
"""A floor with a wall four units high along its +x side."""


def flung_at_wall() -> tuple[Match, Fighter]:
    match, fighter = tumbling(1.5, make_stage(WALL_ROWS))
    place(match, fighter, 4.0, 1.5, z=1.5)
    change_state(match, fighter, StateId.TUMBLE)
    fighter.hitstun = 200
    fighter.kb_vel = Vec3(0.3, 0.0, 0.05)
    return match, fighter


def test_a_tumbling_fighter_bounces_off_a_wall() -> None:
    match, fighter = flung_at_wall()
    bounces = []
    for _ in range(12):
        run(match, neutral(1))
        bounces.extend(events_of(match, WallBounceEvent))
        if bounces:
            break
    assert len(bounces) == 1
    assert fighter.state is StateId.TUMBLE
    assert fighter.pos.x == pytest.approx(6.0 - ROOK.body.radius, abs=1e-4)
    assert -0.3 * c.WALL_BOUNCE_KEEP <= fighter.kb_vel.x < -0.2, "sent back, a little slower"
    assert fighter.damage == c.WALL_BOUNCE_DAMAGE
    run(match, neutral(5))
    assert fighter.pos.x < 6.0 - ROOK.body.radius - 0.5


def test_a_wall_can_be_teched() -> None:
    match, fighter = flung_at_wall()
    techs = []
    for frame in neutral(3) + SHIELD + neutral(8):
        run(match, [frame])
        techs.extend(events_of(match, TechEvent))
        if techs:
            break
    assert len(techs) == 1 and techs[0].wall
    assert fighter.state is StateId.WALL_TECH and fighter.intangible
    assert fighter.kb_vel == ZERO3 and fighter.damage == 0
    held = fighter.pos
    run(match, neutral(c.WALL_TECH_FRAMES - 1))
    assert fighter.pos == held, "sticks to the wall"
    run(match, neutral(2))
    assert fighter.state is StateId.FALL


def test_a_slow_touch_or_a_wall_outside_hitstun_does_not_bounce() -> None:
    match, fighter = flung_at_wall()
    fighter.kb_vel = Vec3(c.WALL_BOUNCE_MIN_SPEED / 2, 0.0, 0.0)
    place_x = 6.0 - ROOK.body.radius - 0.01
    fighter.pos = Vec3(place_x, 1.5, 1.5)
    run(match, neutral(3))
    assert fighter.damage == 0 and fighter.kb_vel.x >= 0


# --- knockdown options --------------------------------------------------------------------


def knocked_down() -> tuple[Match, Fighter]:
    match, fighter = tumbling()
    run_until(match, fighter, StateId.KNOCKDOWN, limit=200)
    run(match, neutral(c.KNOCKDOWN_LOCK_FRAMES))
    return match, fighter


def test_getup_is_intangible_at_first() -> None:
    match, fighter = knocked_down()
    run(match, hold(buttons=Button.JUMP, frames=1))
    assert fighter.state is StateId.GETUP and fighter.intangible_frames == c.GETUP_INTANGIBLE
    run(match, neutral(c.GETUP_FRAMES))
    assert fighter.state is StateId.IDLE and not fighter.intangible


@pytest.mark.parametrize("direction", [Dir8.NW, Dir8.S])
def test_getup_roll(direction: Dir8) -> None:
    match, fighter = knocked_down()
    start = fighter.pos
    run(match, hold(direction, frames=1))
    assert fighter.state is StateId.GETUP_ROLL and fighter.intangible
    run(match, neutral(c.GETUP_ROLL_FRAMES))
    assert fighter.state is StateId.IDLE
    moved = fighter.pos - start
    expected = direction.world * c.GETUP_ROLL_DISTANCE
    assert (moved.x, moved.y) == pytest.approx((expected.x, expected.y))


def test_getup_attack_hits_on_both_sides() -> None:
    match, fighter = knocked_down()
    other = match.fighters[1]
    damages = []
    for offset in (0.9, -0.9):
        place(match, other, fighter.pos.x + offset, Y)
        change_state(match, fighter, StateId.KNOCKDOWN)
        run(match, neutral(c.KNOCKDOWN_LOCK_FRAMES) + hold(buttons=Button.ATTACK, frames=1))
        assert fighter.state is StateId.ATTACK and fighter.move_id == "getup_attack"
        assert fighter.intangible
        run(match, neutral(60))
        damages.append(other.damage)
        fighter.stale_queue.clear()
    assert damages == pytest.approx([7 * c.FRESH_BONUS] * 2), "front, then behind"


def test_lying_fighters_get_up_by_themselves() -> None:
    match, fighter = tumbling()
    run_until(match, fighter, StateId.KNOCKDOWN, limit=200)
    run(match, neutral(c.KNOCKDOWN_MAX_FRAMES))
    assert fighter.state is StateId.GETUP


def test_input_frame_default_is_neutral() -> None:
    assert InputFrame().held == 0
