"""Tests for several opponents, teammates and stages (plan note "15 - CPU AI", decision D-071,
M20 group 6): target choice, friendly fire, hazards as timed threats, opponents that cannot
be hit, and routes on stages whose islands are far apart.
"""

from dataclasses import replace

from helpers import place
from isofightr.ai import crowd
from isofightr.ai.controller import CpuController
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.view import HazardView, observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.events import HazardHitEvent, HitEvent
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3

ROOK = load_character("rook")
GRID = load_stage("training_grid")


def four() -> tuple[Match, list]:
    match = Match.create(GRID, [ROOK] * 4, seed=1, rules=MatchRules(stocks=3))
    for index, (x, y) in enumerate(((3.0, 6.0), (5.0, 6.0), (9.0, 6.0), (6.0, 9.0))):
        place(match, match.fighters[index], x, y)
    return match, list(observe(match).fighters)


# --- target choice ------------------------------------------------------------------------------


def test_an_opponent_that_cannot_be_hit_is_not_the_target_while_another_is_near() -> None:
    _match, views = four()
    me, near, far, other = views
    opponents = [near, far, other]
    assert crowd.target_cost(me, near, opponents, None, False) < crowd.target_cost(
        me, far, opponents, None, False
    )
    shielded = replace(near, invincible=True)
    opponents = [shielded, far, other]
    assert crowd.target_cost(me, shielded, opponents, None, False) > crowd.target_cost(
        me, far, opponents, None, False
    )


def test_the_current_target_is_kept_and_a_high_percent_one_is_preferred() -> None:
    _match, views = four()
    me, a, b, _ = views
    b_close = replace(b, pos=Vec3(a.pos.x + 0.5, a.pos.y + 2.0, a.pos.z))
    opponents = [a, b_close]
    plain = crowd.target_cost(me, b_close, opponents, None, False)
    held = crowd.target_cost(me, b_close, opponents, b_close.index, False)
    hurt = crowd.target_cost(me, replace(b_close, damage=140.0), opponents, None, False)
    assert held < plain and hurt < plain


def test_at_ko_percent_it_keeps_out_of_a_brawl_and_in_a_timed_match_goes_for_the_leader() -> None:
    _match, views = four()
    me, a, b, c = views
    brawling = replace(b, pos=Vec3(a.pos.x + 1.0, a.pos.y, a.pos.z))
    opponents = [a, brawling]
    calm = crowd.target_cost(me, a, opponents, None, False)
    hurt_me = replace(me, damage=130.0)
    assert crowd.target_cost(hurt_me, a, opponents, None, False) > calm
    leader = replace(c, score=3)
    field = [a, b, leader]
    assert crowd.target_cost(me, leader, field, None, True) < crowd.target_cost(
        me, leader, field, None, False
    )


# --- friendly fire ------------------------------------------------------------------------------


def test_a_move_swung_through_a_teammate_is_risky_and_one_away_from_it_is_not() -> None:
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], 6.0, 6.0, facing=Dir8.SE)
    ahead = Dir8.SE.world * 0.8
    place(match, match.fighters[1], 6.0 + ahead.x, 6.0 + ahead.y)
    me, ally = observe(match).fighters
    ftilt = knowledge_for(ROOK).action("ftilt")
    assert crowd.ally_risk(me, ftilt, Dir8.SE.world, [ally]) > 0.5
    assert crowd.ally_risk(me, ftilt, Dir8.NW.world, [ally]) == 0.0
    assert crowd.ally_risk(me, ftilt, Dir8.SE.world, []) == 0.0


# --- hazards ------------------------------------------------------------------------------------


def zone(phase: str, to_active: int, left: int = 0) -> HazardView:
    return HazardView(
        0, "lightning", Vec3(5.0, 5.0, 0.0), 1.2, 9.0, phase, to_active, left, True, Vec3()
    )


def test_only_hazards_that_hit_and_are_coming_soon_are_danger_zones() -> None:
    soon, later, now = zone("warn", 30), zone("rest", 400), zone("active", 0, 10)
    wind = replace(soon, hits=False)
    assert crowd.danger_zones([soon, later, now, wind]) == [soon, now]


def test_a_place_in_a_zone_is_moved_out_of_it_and_a_path_through_it_is_seen() -> None:
    soon = zone("warn", 20)
    out = crowd.clear_of(Vec3(5.5, 5.0, 0.0), [soon])
    assert out is not None and (out.xy - Vec2(5.0, 5.0)).length() > 1.2
    assert crowd.clear_of(Vec3(9.0, 9.0, 0.0), [soon]) is None
    start = Vec3(3.0, 5.0, 0.0)
    path = [(f, Vec3(0.1 * f, 0.0, 0.0)) for f in range(0, 40, 4)]
    assert crowd.hit_during(start, path, [soon])
    assert not crowd.hit_during(start, path[:3], [soon]), "out before the bolt"


def test_a_cpu_at_a_lightning_rod_walks_out_before_the_bolt() -> None:
    stage = load_stage("storm_galleon")
    rules = MatchRules(stocks=None, stage_hazards=True)
    match = Match.create(stage, [ROOK, ROOK], seed=1, rules=rules)
    rod = 1  # the middle rod, at (8.5, 4.5)
    while observe(match).hazards[rod].phase != "warn":
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
    place(match, match.fighters[0], 8.5, 4.5)
    place(match, match.fighters[1], 2.0, 2.0)
    cpu = CpuController(0, 9, 1, stage)
    struck = False
    for _ in range(140):
        match.tick([cpu.think(match), NEUTRAL_INPUT])
        struck = struck or any(
            isinstance(e, HazardHitEvent) and e.target == 0 for e in match.events
        )
    assert not struck


# --- stages -------------------------------------------------------------------------------------


def test_two_brambles_on_lily_pads_get_to_each_other() -> None:
    """They used to wait on their own pads for whole matches: no route fit the share of
    Bramble's jump a CPU trusts, so the route is now stretched before it gives up."""
    stage = load_stage("lily_pads")
    bramble = load_character("bramble")
    match = Match.create(stage, [bramble, bramble], seed=1, rules=MatchRules(stocks=None))
    cpus = [CpuController(i, 9, 1, stage) for i in range(2)]
    hits = 0
    for _ in range(40 * 60):
        world = observe(match)
        match.tick([cpu.think(match, world) for cpu in cpus])
        hits += sum(1 for e in match.events if isinstance(e, HitEvent))
    assert hits >= 5
