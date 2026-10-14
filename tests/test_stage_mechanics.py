"""Stage mechanics (decision D-063, M14 group 4): the hazards rule, moving platforms,
hazards (geyser, lightning, wind) and surface modifiers (ice, conveyors, springs).

Every stage here is built in the test: no stage in ``assets/`` exists only for tests.
"""

from collections.abc import Mapping
from dataclasses import replace

import pytest

from helpers import hold, neutral, place, run
from isofightr.ai.random_inputs import random_inputs
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import parse_stage
from isofightr.data.validation import DataError
from isofightr.sim.constants import HAZARD_SAFE_FRAMES, MAX_PLATFORM_SPEED
from isofightr.sim.events import BounceEvent, HazardHitEvent
from isofightr.sim.fighter import NO_PARTNER, GroundKind, StateId
from isofightr.sim.input_frame import Button, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.replay import Recorder, from_data, play_back, to_data
from isofightr.sim.stage import Stage, path_extent

ROOK = load_character("rook")
ON = MatchRules(stocks=None, stage_hazards=True)
OFF = MatchRules(stocks=None)
GRID = "\n".join(["0000000000"] * 10)
SPAWNS = {
    "p1": [1.5, 1.5],
    "p2": [8.5, 1.5],
    "p3": [1.5, 8.5],
    "p4": [8.5, 8.5],
    "respawn": [1.5, 1.5],
}
BRIDGE = {
    "rect": [4, 4, 6, 6],
    "z": 2.5,
    "motion": {"kind": "ping_pong", "to": [3.0, 0.0, 0.0], "period": 240},
}
LIFT = {"rect": [4, 4, 6, 6], "z": 2.5, "motion": {"kind": "bob", "amplitude": 1.5, "period": 120}}
GEYSER = {
    "kind": "geyser",
    "at": [5.0, 5.0],
    "radius": 0.8,
    "rest": 200,
    "warn": 60,
    "active": 30,
    "damage": 12.0,
}
WIND = {
    "kind": "wind",
    "at": [5.0, 5.0],
    "radius": 2.0,
    "rest": 200,
    "warn": 60,
    "active": 90,
    "push": [0.03, 0.0, 0.0],
}


def build(grid: str = GRID, legend: Mapping[str, object] | None = None, **extra: object) -> Stage:
    data: dict[str, object] = {
        "id": "test",
        "display_name": "Test",
        "tileset": "grid",
        "grid": grid,
        "legend": {"0": {"height": 0}, **(legend or {})},
        "spawns": SPAWNS,
        **extra,
    }
    return parse_stage(data, source="test")


def start(stage: Stage, rules: MatchRules = ON, fighters: int = 2) -> Match:
    return Match.create(stage, [ROOK] * fighters, seed=3, rules=rules)


def wait(match: Match, frames: int) -> None:
    for _ in range(frames):
        match.tick(neutral() * len(match.fighters))


def with_cells(row: int, column: int, symbol: str) -> str:
    rows = GRID.splitlines()
    rows[row] = rows[row][:column] + symbol + rows[row][column + 1 :]
    return "\n".join(rows)


# --- the rule ------------------------------------------------------------------------------


def test_the_rule_is_off_in_the_sim_and_stages_know_if_they_have_mechanics() -> None:
    assert not MatchRules().stage_hazards
    assert not build().has_mechanics
    assert build(soft_platforms=[BRIDGE]).has_mechanics and build(soft_platforms=[BRIDGE]).moves
    assert build(hazards=[GEYSER]).has_mechanics and not build(hazards=[GEYSER]).moves
    icy = build(with_cells(5, 5, "i"), {"i": {"height": 0, "traction": 0.25}})
    assert icy.has_mechanics and icy.cell(5, 5).traction == 0.25  # type: ignore[union-attr]
    assert build(soft_platforms=[{"rect": [4, 4, 6, 6], "z": 2.5}]).at(77) is not None


FULL = {
    "soft_platforms": [BRIDGE, LIFT | {"rect": [1, 6, 3, 8]}],
    "hazards": [GEYSER, WIND | {"at": [7.0, 7.0]}],
}
FULL_LEGEND = {
    "i": {"height": 0, "traction": 0.25},
    "c": {"height": 0, "drive": [0.02, 0.0]},
    "s": {"height": 0, "bounce": 0.4},
}
FULL_GRID = with_cells(3, 3, "i").replace(
    "0000000000\n0000000000\n0000000000", "0000000000\n00000cc000\n0000000s00", 1
)


def test_with_hazards_off_a_mechanic_stage_plays_exactly_like_plain_ground() -> None:
    mechanic = build(FULL_GRID, FULL_LEGEND, **FULL)
    plain = build(
        GRID, soft_platforms=[{"rect": [4, 4, 6, 6], "z": 2.5}, {"rect": [1, 6, 3, 8], "z": 2.5}]
    )
    assert mechanic.has_mechanics and not plain.has_mechanics
    inputs = random_inputs(11, 1500)
    one, other = start(mechanic, OFF), start(plain, OFF)
    lively = start(mechanic, ON)
    differed = False
    for frames in inputs:
        one.tick(frames)
        other.tick(frames)
        lively.tick(frames)
        assert one.state_hash() == other.state_hash(), f"frame {one.frame}"
        assert one.stage is mechanic, "nothing moved"
        differed = differed or lively.state_hash() != one.state_hash()
    assert differed, "and with the rule on, the same inputs play out differently"


def test_a_match_on_a_mechanic_stage_is_deterministic_and_its_replay_verifies() -> None:
    stage = build(FULL_GRID, FULL_LEGEND, **FULL)
    inputs = random_inputs(5, 1800)
    hashes = []
    for _ in range(2):
        match = start(stage)
        recorder = Recorder("test", ("rook", "rook"), 3, ON)
        for frames in inputs:
            recorder.record(frames)
            match.tick(frames)
        hashes.append(match.state_hash())
    assert hashes[0] == hashes[1]
    replay = from_data(to_data(recorder.finish(match)))
    assert replay.rules.stage_hazards, "the rule is in the replay"
    assert play_back(start(stage, replay.rules), replay)
    assert not play_back(start(stage, replace(replay.rules, stage_hazards=False)), replay)
    old = to_data(recorder.finish(match))
    del old["rules"]["stage_hazards"]
    assert not from_data(old).rules.stage_hazards, "a replay from before the rule plays without it"


# --- moving platforms ----------------------------------------------------------------------


def test_a_platforms_place_is_a_function_of_the_frame() -> None:
    stage = build(soft_platforms=[BRIDGE])
    platform = stage.soft_platforms[0]
    assert platform.at(0).x0 == 4 and platform.at(240).x0 == pytest.approx(4)
    assert platform.at(120).x0 == pytest.approx(7.0), "at the far end half way through"
    assert platform.at(60).x0 == pytest.approx(5.5), "and half way there a quarter through"
    assert 4 < platform.at(20).x0 < 4.3, "it eases away from a stop"
    assert platform.at(1000).x0 == platform.at(1000 % 240).x0
    for frame in range(0, 480, 7):
        moved = platform.at(frame)
        assert moved.step.length() <= MAX_PLATFORM_SPEED
        assert moved.x0 - platform.at(frame - 1).x0 == pytest.approx(moved.step.x)
        assert (moved.y0, moved.z) == (4, 2.5) and moved.x1 - moved.x0 == pytest.approx(2)
    assert stage.at(60).soft_platforms[0].x0 == pytest.approx(5.5) and stage.at(60) is not stage
    still = build(soft_platforms=[{"rect": [4, 4, 6, 6], "z": 2.5}])
    assert still.at(60) is still
    extent = path_extent(platform)
    assert (extent.x_min, extent.x_max, extent.z_min, extent.z_max) == (4, 9, 2.5, 2.5)
    assert stage.camera_bounds.x_max == still.camera_bounds.x_max, "inside the island anyway"


def test_other_trips_a_phase_a_loop_and_a_bob() -> None:
    late = build(soft_platforms=[BRIDGE | {"motion": BRIDGE["motion"] | {"phase": 120}}])  # type: ignore[operator]
    assert late.soft_platforms[0].at(0).x0 == pytest.approx(7.0)
    loop = {"kind": "loop", "points": [[2.0, 0.0, 0.0], [2.0, 2.0, 0.0]], "period": 300}
    round_trip = build(
        soft_platforms=[{"rect": [3, 3, 5, 5], "z": 2.5, "motion": loop}]
    ).soft_platforms[0]
    assert (round_trip.at(100).x0, round_trip.at(100).y0) == pytest.approx((5.0, 3.0))
    assert (round_trip.at(200).x0, round_trip.at(200).y0) == pytest.approx((5.0, 5.0))
    assert (round_trip.at(250).x0, round_trip.at(250).y0) == pytest.approx((4.0, 4.0)), "home"
    lift = build(soft_platforms=[LIFT]).soft_platforms[0]
    assert lift.at(60).z == pytest.approx(4.0) and lift.at(0).z == lift.at(120).z == 2.5


def test_a_fighter_standing_on_a_platform_is_carried_by_it() -> None:
    stage = build(soft_platforms=[BRIDGE])
    match = start(stage)
    rider = match.fighters[0]
    place(match, rider, 5.0, 5.0)
    assert rider.ground is GroundKind.PLATFORM and rider.platform == 0
    for _ in range(240):
        match.tick(neutral() * 2)
        deck = match.stage.soft_platforms[0]
        assert rider.ground is GroundKind.PLATFORM and rider.state is StateId.IDLE
        assert rider.pos.x - deck.x0 == pytest.approx(1.0) and rider.pos.z == deck.z
        if match.frame == 120:
            assert rider.pos.x == pytest.approx(8.0)
    assert rider.pos == Vec3(5.0, 5.0, 2.5), "back where it started after a whole trip"
    assert match.rest_stage is stage and match.stage.soft_platforms[0].x0 == pytest.approx(4)

    resting = start(stage, OFF)
    place(resting, resting.fighters[0], 5.0, 5.0)
    wait(resting, 120)
    assert resting.fighters[0].pos == Vec3(5.0, 5.0, 2.5) and resting.stage is stage


def test_a_lift_carries_up_and_down_and_a_frozen_fighter_too() -> None:
    match = start(build(soft_platforms=[LIFT]))
    rider = match.fighters[0]
    place(match, rider, 5.0, 5.0)
    wait(match, 30)
    rider.hitlag = 20  # frozen by a hit: it skips its own physics, but still rides the deck
    wait(match, 30)
    assert rider.pos.z == pytest.approx(4.0) and rider.ground is GroundKind.PLATFORM
    wait(match, 60)
    assert rider.pos.z == pytest.approx(2.5)


def test_landing_is_swept_against_a_deck_that_moves() -> None:
    match = start(build(soft_platforms=[LIFT]))
    faller = match.fighters[0]
    place(match, faller, 5.0, 5.0, z=6.5)
    landed_at = None
    for _ in range(200):
        match.tick(neutral() * 2)
        if faller.grounded:
            landed_at = match.frame
            break
    assert landed_at is not None and faller.ground is GroundKind.PLATFORM
    assert faller.pos.z == pytest.approx(match.stage.soft_platforms[0].z)

    # Jumping up through it from underneath: a soft platform never blocks from below.
    match = start(build(soft_platforms=[LIFT]))
    jumper = match.fighters[0]
    place(match, jumper, 5.0, 5.0, z=0.0)
    run(match, hold(buttons=Button.JUMP, frames=40))
    assert jumper.pos.z > 0.5 or jumper.ground is GroundKind.PLATFORM


def test_walking_off_a_moving_platform_and_dropping_through_it() -> None:
    match = start(build(soft_platforms=[BRIDGE]))
    walker = match.fighters[0]
    place(match, walker, 5.0, 5.0)
    run(match, hold(Dir8.NW, frames=25))
    wait(match, 60)
    assert walker.ground is GroundKind.CELL and walker.pos.z == 0.0, "walked off and fell"

    match = start(build(soft_platforms=[BRIDGE]))
    dropper = match.fighters[0]
    place(match, dropper, 5.0, 5.0)
    wait(match, 30)
    run(match, hold(frames=4, vertical=-1) + hold(Dir8.S, frames=30, vertical=-1))
    wait(match, 30)
    assert dropper.pos.z == 0.0 and dropper.ground is GroundKind.CELL, "dropped through"


@pytest.mark.parametrize(
    ("platform", "message"),
    [
        (BRIDGE | {"motion": {"kind": "wobble", "to": [1, 0, 0], "period": 240}}, "motion kind"),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "to": [0, 0, 0], "period": 240}},
            "goes nowhere",
        ),
        (BRIDGE | {"motion": {"kind": "ping_pong", "to": [3, 0, 0], "period": 30}}, "at least"),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "to": [3, 0, 0], "period": 61}},
            "units a frame",
        ),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "to": [0, 0, -2.4], "period": 600}},
            "comes within",
        ),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "to": [30, 0, 0], "period": 3000}},
            "blast zone",
        ),
        (BRIDGE | {"motion": {"kind": "ping_pong", "period": 240}}, "exactly one of"),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "amplitude": 1, "period": 240}},
            "only for a bob",
        ),
        (BRIDGE | {"motion": {"kind": "loop", "points": "far", "period": 240}}, "list of"),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "to": [1, 0, 0], "period": 240, "speed": 2}},
            "unknown key",
        ),
        (
            BRIDGE | {"motion": {"kind": "ping_pong", "to": [1, 0, 0], "period": 240, "phase": -1}},
            "phase",
        ),
    ],
)
def test_bad_motion_is_refused(platform: dict[str, object], message: str) -> None:
    with pytest.raises(DataError, match=message):
        build(soft_platforms=[platform])


# --- hazards -------------------------------------------------------------------------------


def test_a_hazards_cycle_is_rest_then_warning_then_active() -> None:
    hazard = build(hazards=[GEYSER]).hazards[0]
    assert hazard.cycle == 290 and hazard.first_active() == 260
    assert hazard.moment(0) == ("rest", 0, 0) and hazard.moment(199) == ("rest", 199, 0)
    assert hazard.moment(200) == ("warn", 0, 0) and hazard.moment(259) == ("warn", 59, 0)
    assert hazard.moment(260) == ("active", 0, 0) and hazard.moment(289) == ("active", 29, 0)
    assert hazard.moment(290) == ("rest", 0, 1) and hazard.moment(290 + 260)[2] == 1
    assert [hazard.is_active(frame) for frame in (259, 260, 289, 290)] == [False, True, True, False]
    late = build(hazards=[GEYSER | {"phase": 10}]).hazards[0]
    assert late.first_active() == 250 and late.moment(250)[0] == "active"
    assert hazard.touches(Vec3(5.5, 5.0, 0.0), 0.3, 2.5) and not hazard.touches(
        Vec3(7.0, 5.0, 0.0), 0.3, 2.5
    )
    assert not hazard.touches(Vec3(5.0, 5.0, 6.0), 0.3, 2.5), "above the column"


def test_a_geyser_hits_once_each_time_it_goes_off() -> None:
    match = start(build(hazards=[GEYSER]))
    victim, bystander = match.fighters
    place(match, victim, 5.2, 5.0)
    wait(match, 259)
    assert victim.damage == 0.0 and not match.events
    match.tick(neutral() * 2)
    hits = [event for event in match.events if isinstance(event, HazardHitEvent)]
    assert len(hits) == 1 and hits[0].target == 0 and hits[0].kind == "geyser"
    assert (hits[0].damage, hits[0].blocked) == (12.0, False) and hits[0].knockback > 0
    assert victim.damage == 12.0 and victim.hitlag > 0 and bystander.hitlag == 0
    assert victim.hazard_hits == {0: 0} and victim.last_hit_by == NO_PARTNER
    assert match.stats[0].damage_taken == 12.0 and match.stats[1].damage_given == 0.0
    wait(match, 14)
    assert not victim.grounded and victim.pos.z > 0.0, "thrown up"
    wait(match, 15)
    assert victim.damage == 12.0, "one eruption, one hit, however long it lasts"
    wait(match, 150)  # let it land and get up before standing it back in the geyser
    place(match, victim, 5.2, 5.0, damage=12.0)
    wait(match, 141)
    assert match.frame == 580 and victim.damage == 24.0 and victim.hazard_hits == {0: 1}, (
        "the next one hits again"
    )
    assert bystander.damage == 0.0

    quiet = start(build(hazards=[GEYSER]), OFF)
    place(quiet, quiet.fighters[0], 5.2, 5.0)
    wait(quiet, 600)
    assert quiet.fighters[0].damage == 0.0, "nothing with the rule off"


def test_a_hazard_takes_nobodys_ko_credit() -> None:
    lethal = GEYSER | {"damage": 30.0, "bkb": 400.0}
    match = start(build(hazards=[lethal]), replace(ON, stocks=3))
    victim = match.fighters[0]
    place(match, victim, 5.2, 5.0)
    for _ in range(900):
        match.tick(neutral() * 2)
        if victim.stocks == 2:
            break
    assert victim.stocks == 2 and match.stats[0].self_destructs == 1 and match.stats[1].kos == 0

    match = start(build(hazards=[lethal]), replace(ON, stocks=3))
    victim = match.fighters[0]
    place(match, victim, 5.2, 5.0)
    wait(match, 250)
    victim.last_hit_by, victim.last_hit_timer = 1, 400  # player 2 hit them just before
    for _ in range(900):
        match.tick(neutral() * 2)
        if victim.stocks == 2:
            break
    assert match.stats[1].kos == 1 and match.stats[0].self_destructs == 0, "the rival keeps it"


def test_a_shield_blocks_a_hazard_and_dodges_and_invincibility_beat_it() -> None:
    match = start(build(hazards=[GEYSER]))
    guard = match.fighters[0]
    place(match, guard, 5.2, 5.0)
    wait(match, 240)
    full = guard.shield_hp
    run(match, hold(buttons=Button.SHIELD, frames=20))
    blocked = [event for event in match.events if isinstance(event, HazardHitEvent)]
    assert len(blocked) == 1 and blocked[0].blocked and blocked[0].damage > 0
    assert guard.damage == 0.0 and guard.shield_hp < full - 5.0
    assert guard.state is StateId.SHIELD_STUN and guard.launch is None
    assert match.stats[0].damage_taken == 0.0

    match = start(build(hazards=[GEYSER]))
    ghost = match.fighters[0]
    place(match, ghost, 5.2, 5.0)
    wait(match, 259)
    ghost.intangible_frames = 40
    wait(match, 31)
    assert ghost.damage == 0.0 and ghost.hazard_hits == {}, "it passed through"

    match = start(build(hazards=[GEYSER]))
    hero = match.fighters[0]
    place(match, hero, 5.2, 5.0)
    wait(match, 259)
    hero.invincible_frames = 40
    match.tick(neutral() * 2)
    hit = next(event for event in match.events if isinstance(event, HazardHitEvent))
    assert hit.damage == 0.0 and hero.damage == 0.0 and hero.launch is None


def test_lightning_launches_away_from_where_it_strikes() -> None:
    bolt = {
        "kind": "lightning",
        "at": [5.0, 5.0],
        "radius": 1.0,
        "rest": 200,
        "warn": 50,
        "active": 6,
        "damage": 15.0,
    }
    match = start(build(hazards=[bolt]))
    left, right = match.fighters
    place(match, left, 4.4, 5.0, damage=60.0)
    place(match, right, 5.6, 5.0, damage=60.0)
    wait(match, 320)
    assert left.damage == right.damage == 75.0
    assert left.pos.x < 4.0 and right.pos.x > 6.0, "each thrown outward"
    assert build(hazards=[bolt]).hazards[0].height == 9.0, "a tall column: it reaches platforms"


def test_wind_pushes_while_it_blows_on_the_ground_and_in_the_air() -> None:
    match = start(build(hazards=[WIND]))
    walker, outsider = match.fighters
    place(match, walker, 4.0, 5.0)
    place(match, outsider, 8.5, 8.5)
    wait(match, 259)
    assert walker.pos.x == 4.0, "a warning moves nobody"
    wait(match, 30)
    assert walker.pos.x == pytest.approx(4.0 + 30 * 0.03) and walker.state is StateId.IDLE
    assert outsider.pos.x == 8.5
    wait(match, 200)
    resting = walker.pos.x
    wait(match, 30)
    assert walker.pos.x == resting, "it stopped: out of the wind, or the wind is resting"

    match = start(build(hazards=[WIND]))
    floater = match.fighters[0]
    place(match, floater, 4.0, 5.0, z=3.0)
    match.frame = 259
    wait(match, 10)
    assert floater.pos.x == pytest.approx(4.0 + 10 * 0.03) and not floater.grounded


@pytest.mark.parametrize(
    ("hazard", "message"),
    [
        (GEYSER | {"kind": "meteor"}, "kind must be one of"),
        (GEYSER | {"radius": 0}, "radius and height"),
        (GEYSER | {"warn": 0}, "warn and active"),
        (GEYSER | {"damage": 0}, "needs damage"),
        (GEYSER | {"push": [1, 0, 0]}, "only for a wind"),
        (WIND | {"damage": 3}, "not for a wind"),
        ({key: value for key, value in WIND.items() if key != "push"}, "needs a push"),
        (GEYSER | {"at": [1.5, 1.5], "rest": 100}, "active over a spawn"),
        (WIND | {"at": [8.5, 8.5], "rest": 0, "warn": 60}, "active over a spawn"),
        (GEYSER | {"colour": "red"}, "unknown key"),
    ],
)
def test_bad_hazards_are_refused(hazard: dict[str, object], message: str) -> None:
    with pytest.raises(DataError, match=message):
        build(hazards=[hazard])


def test_a_hazard_may_sit_on_a_spawn_if_it_waits_four_seconds() -> None:
    patient = GEYSER | {"at": [1.5, 1.5], "rest": HAZARD_SAFE_FRAMES - 60}
    assert build(hazards=[patient]).hazards[0].first_active() == HAZARD_SAFE_FRAMES
    with pytest.raises(DataError, match="active over a spawn"):
        build(hazards=[patient | {"phase": 1}])


# --- surfaces ------------------------------------------------------------------------------


def slide(legend: Mapping[str, object] | None, rules: MatchRules = ON) -> float:
    grid = "\n".join(["0000000000"] * 4 + ["iiiiiiiiii"] * 2 + ["0000000000"] * 4)
    match = start(build(grid, {"i": {"height": 0, **(legend or {})}}), rules)
    runner = match.fighters[0]
    place(match, runner, 1.5, 4.5)
    run(match, hold(Dir8.SE, frames=1))
    east = match.fighters[0].pos.x > 1.5
    run(match, hold(Dir8.SE if east else Dir8.NE, frames=30))
    before = runner.pos
    wait(match, 90)
    return (runner.pos - before).length()


def test_ice_makes_a_stop_slide_further() -> None:
    plain, icy = slide(None), slide({"traction": 0.25})
    assert icy > 2.0 * plain > 0.0
    assert slide({"traction": 0.25}, OFF) == pytest.approx(plain), "plain with the rule off"


def test_a_conveyor_carries_whoever_stands_on_it() -> None:
    grid = with_cells(5, 5, "c")
    stage = build(grid, {"c": {"height": 0, "drive": [0.02, 0.0]}})
    match = start(stage)
    rider = match.fighters[0]
    place(match, rider, 5.2, 5.5)
    wait(match, 10)
    assert rider.pos.x == pytest.approx(5.4) and rider.state is StateId.IDLE and rider.vel == ZERO3
    wait(match, 60)
    assert 6.0 <= rider.pos.x < 6.05, "it stops carrying at the end of the belt"
    still = start(stage, OFF)
    place(still, still.fighters[0], 5.2, 5.5)
    wait(still, 60)
    assert still.fighters[0].pos.x == 5.2


def test_a_spring_throws_a_fighter_up_but_not_one_in_hitstun() -> None:
    stage = build(with_cells(5, 5, "s"), {"s": {"height": 0, "bounce": 0.4}})
    match = start(stage)
    hopper = match.fighters[0]
    place(match, hopper, 5.5, 5.5, z=1.0)
    bounced = []
    peak = 0.0
    for _ in range(120):
        match.tick(neutral() * 2)
        bounced += [event for event in match.events if isinstance(event, BounceEvent)]
        peak = max(peak, hopper.pos.z)
    assert len(bounced) >= 2 and bounced[0].player == 0 and bounced[0].speed == 0.4
    assert peak > 2.5, "higher than its own jump would take it from a standstill"
    assert hopper.air_jumps_left == ROOK.movement.air_jumps or not hopper.grounded

    stunned = start(stage)
    victim = stunned.fighters[0]
    place(stunned, victim, 5.5, 5.5)
    victim.hitstun = 40
    victim.state = StateId.FLINCH
    wait(stunned, 20)
    assert victim.pos.z == 0.0, "a spring never rescues anyone from a combo"

    off = start(stage, OFF)
    place(off, off.fighters[0], 5.5, 5.5)
    wait(off, 30)
    assert off.fighters[0].pos.z == 0.0


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"height": 0, "traction": 0}, "traction must be"),
        ({"height": 0, "bounce": 2.0}, "bounce must be"),
        ({"height": 0, "drive": [0.1]}, "drive"),
        ({"height": 0, "slippery": True}, "unknown key"),
    ],
)
def test_bad_surfaces_are_refused(entry: dict[str, object], message: str) -> None:
    with pytest.raises(DataError, match=message):
        build(with_cells(5, 5, "x"), {"x": entry})


def test_no_spawn_stands_on_a_conveyor_or_a_spring() -> None:
    for entry in ({"height": 0, "bounce": 0.4}, {"height": 0, "drive": [0.02, 0.0]}):
        with pytest.raises(DataError, match="a spawn stands on"):
            build(with_cells(1, 1, "x"), {"x": entry})
    assert build(with_cells(1, 1, "x"), {"x": {"height": 0, "traction": 0.25}}).has_mechanics


# --- the state hash ------------------------------------------------------------------------


def test_the_state_hash_covers_the_hazard_record_and_plain_stages_hash_as_before() -> None:
    match = start(build(hazards=[GEYSER]))
    place(match, match.fighters[0], 5.2, 5.0)
    wait(match, 261)
    before = match.state_hash()
    match.fighters[0].hazard_hits[0] = 7
    assert match.state_hash() != before
    plain = start(build(), OFF)
    assert plain._canonical_mechanics() == ()
    assert start(build(soft_platforms=[BRIDGE]))._canonical_mechanics() == ()
