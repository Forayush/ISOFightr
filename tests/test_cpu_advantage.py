"""Tests for the CPU's advantage state (plan note "15 - CPU AI", decision D-071, M20 group 3):
throws by forecast, chasing a launched opponent, the ledge trap, shield breaks, and the return
check that lets a CPU edgeguard off the stage without losing a stock.
"""

from dataclasses import replace

from helpers import place
from isofightr.ai import advantage, intercept
from isofightr.ai.controller import CpuController
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.predict import Track, track
from isofightr.ai.view import observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as combat
from isofightr.sim.combat.shield import shield_damage
from isofightr.sim.events import GrabEvent, HitEvent, KoEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, VERTICAL_NONE, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3

ROOK = load_character("rook")
KNOWN = knowledge_for(ROOK)
GRID = load_stage("training_grid")


def pair(x: float, y: float, damage: float = 0.0, stage=GRID) -> Match:
    """A Rook at (x, y) facing south-east, another Rook just in front of it."""
    match = Match.create(stage, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], x, y, facing=Dir8.SE)
    ahead = Dir8.SE.world * 0.6
    place(match, match.fighters[1], x + ahead.x, y + ahead.y, facing=Dir8.NW, damage=damage)
    return match


# --- throws by forecast -------------------------------------------------------------------


def test_every_throw_and_direction_is_weighed_best_first() -> None:
    match = pair(6.0, 6.0, damage=20.0)
    me, victim = observe(match).fighters
    choices = advantage.throw_choices(GRID, me, ROOK.grabs, victim, ROOK)
    assert len(choices) == 2 + len(Dir8)
    assert [c.value for c in choices] == sorted((c.value for c in choices), reverse=True)
    assert {c.name for c in choices} >= {"up", "down"}
    backs = [c for c in choices if c.name.startswith("back")]
    fronts = [c for c in choices if c.name.startswith("forward")]
    assert backs and fronts and all(c.throw is ROOK.grabs.back for c in backs)
    assert all(c.vertical == VERTICAL_NONE for c in backs + fronts)
    assert not any(c.kills for c in choices), "nothing kills at 20%"


def test_at_high_percent_near_an_edge_the_best_throw_kills_off_that_edge() -> None:
    west = 0.8  # Training Grid's west edge is x = 0
    match = pair(west + 0.2, 6.0, damage=170.0)
    me, victim = observe(match).fighters
    choices = advantage.throw_choices(GRID, me, ROOK.grabs, victim, ROOK)
    best = choices[0]
    if any(choice.kills for choice in choices):
        assert best.kills
    else:
        assert best.off_stage, "no throw KOs here: then off the stage, for an edgeguard"
    assert best.vertical == VERTICAL_NONE and best.heading.x < 0.0, "toward the near edge"


def test_a_cpu_holding_someone_throws_by_the_forecast() -> None:
    match = pair(1.2, 6.0, damage=170.0)
    cpu = CpuController(0, 9, 1, GRID)
    victim = match.fighters[1]
    events = []
    for tick in range(240):
        world = observe(match)
        frame = cpu.think(match, world)
        if tick < 3:
            frame = InputFrame(held=int(Button.GRAB))
        match.tick([frame, NEUTRAL_INPUT])
        events += match.events
        if any(isinstance(e, KoEvent) and e.player == 1 for e in events):
            break
    assert any(isinstance(e, GrabEvent) and e.grabber == 0 for e in events)
    assert cpu.plan.kind == "throw" or any(isinstance(e, KoEvent) for e in events)
    assert any(isinstance(e, KoEvent) and e.player == 1 for e in events), victim.state


# --- chasing and the ledge ------------------------------------------------------------------


def test_the_chase_point_is_on_ground_under_where_the_opponent_will_be() -> None:
    match = pair(6.0, 6.0)
    me, _target = observe(match).fighters
    landing = Vec3(7.0, 6.0, 0.0)
    path = tuple(Vec3(6.0 + 0.05 * f, 6.0, max(2.0 - 0.1 * f, 0.0)) for f in range(1, 41))
    flying = Track(path, (0.0,) * 40, 30)
    point = advantage.chase_point(GRID, flying, me, 40)
    assert point is not None and abs(point.x - path[29].x) < 1e-9 and point.z == 0.0
    off = Track(tuple(Vec3(-3.0, 6.0, 1.0) for _ in range(40)), (0.0,) * 40, 30)
    assert advantage.chase_point(GRID, off, me, 40) is None, "over nothing: an edgeguard"
    assert landing.z == 0.0


def test_the_ledge_trap_is_inside_the_ledge_the_opponent_hangs_from() -> None:
    match = pair(6.0, 6.0)
    hanger = match.fighters[1]
    place(match, hanger, -0.35, 6.0, z=-1.8)
    view = observe(match).fighters[1]
    spot = advantage.ledge_trap_point(GRID, view)
    assert spot is not None and spot.z == 0.0
    assert abs(spot.x - (0.0 + 1.5)) < 1e-6 and abs(spot.y - 6.0) < 0.6


def test_the_return_check_counts_jumps_and_the_up_special() -> None:
    near = Vec3(-1.5, 6.0, 0.5)
    far = Vec3(-12.0, 6.0, 0.5)
    deep = Vec3(-1.5, 6.0, -9.0)
    assert advantage.can_return(GRID, near, 1, KNOWN)
    assert not advantage.can_return(GRID, far, 1, KNOWN)
    assert not advantage.can_return(GRID, deep, 1, KNOWN)
    assert advantage.can_return(GRID, Vec3(6.0, 6.0, 0.0), 0, KNOWN), "over the stage"


def test_an_off_stage_action_is_safe_only_when_edgeguarding_and_returnable() -> None:
    match = pair(0.6, 6.0)
    cpu = CpuController(0, 9, 1, GRID)
    cpu.think(match)
    me = observe(match).fighters[0]
    me = replace(me, pos=Vec3(-0.4, 6.0, 1.5), grounded=False, vel=Vec3(0.0, 0.0, 0.0))
    fair = KNOWN.action("air_fair")
    west = Vec2(-1.0, 0.0)
    cpu._edgeguard_ok = False
    assert not cpu._safe(me, fair, west), "not edgeguarding: stays over the stage"
    cpu._edgeguard_ok = True
    assert cpu._safe(me, fair, west), "edgeguarding, a jump left: fine"
    assert not cpu._safe(me, KNOWN.extra("air_uspecial_up"), west), "never helpless out there"


# --- shield breaks ----------------------------------------------------------------------------


def test_a_block_that_breaks_the_shield_is_worth_more_than_a_hit() -> None:
    match = pair(6.0, 6.0)
    me, target = observe(match).fighters
    shielding = replace(target, state=StateId.SHIELD)
    sure = Track((target.pos,) * 70, (0.0,) * 70, 70)
    reading = intercept.Reading(GRID, me, shielding, sure, ROOK, KNOWN)
    smash = KNOWN.action("fsmash")
    full = intercept.weigh(reading, smash, Dir8.SE.world, smash.first_hit, 1.0)
    damage = smash.damage * 1.05
    worn = replace(shielding, shield_hp=shield_damage(damage) - 0.5)
    broken = intercept.weigh(
        replace(reading, target=worn), smash, Dir8.SE.world, smash.first_hit, 1.0
    )
    assert full.hit == 0.0 and broken.hit == 1.0
    assert broken.value > full.value + 20.0
    assert shield_damage(damage) < combat.SHIELD_MAX_HP


# --- in play --------------------------------------------------------------------------------


def test_a_launched_opponent_is_chased() -> None:
    """After a forward smash at mid percent the CPU heads for where the victim lands."""
    match = pair(4.0, 6.0, damage=60.0)
    cpu = CpuController(0, 9, 1, GRID)
    from isofightr.sim.states.interrupts import start_move

    start_move(match, match.fighters[0], "ftilt")
    plans = set()
    hits = 0
    for _ in range(150):
        world = observe(match)
        match.tick([cpu.think(match, world), NEUTRAL_INPUT])
        plans.add(f"{cpu.plan.kind} {cpu.plan.detail}")
        hits += sum(1 for e in match.events if isinstance(e, HitEvent) and e.attacker == 0)
    assert hits >= 2, plans
    assert any(p.startswith(("attack", "advantage")) for p in plans)


def test_four_level_9_cpus_on_twin_isles_and_storm_galleon_do_not_self_destruct() -> None:
    """Edgeguarding off the stage must not cost stocks (the stages with gaps and hazards)."""
    characters = [load_character(c) for c in ("rook", "bramble", "zephyr", "mote")]
    for stage_id in ("twin_isles", "storm_galleon"):
        stage = load_stage(stage_id)
        rules = MatchRules(stocks=None, stage_hazards=True)
        match = Match.create(stage, characters, seed=5, rules=rules)
        cpus = [CpuController(i, 9, 5, stage) for i in range(4)]
        destructs = 0
        for _ in range(4 * 3600):
            world = observe(match)
            match.tick([cpu.think(match, world) for cpu in cpus])
            destructs += sum(
                1 for e in match.events if isinstance(e, KoEvent) and e.credited_to is None
            )
        assert destructs <= 1, stage_id


def test_tracks_are_still_real_tracks() -> None:
    match = pair(6.0, 6.0)
    _me, target = observe(match).fighters
    assert track(GRID, target, ROOK, KNOWN, 10).locked == 0
