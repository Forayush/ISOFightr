"""Tests for the CPU's disadvantage state (plan note "15 - CPU AI", decision D-071, M20 group
4): DI by the forecast, SDI out of multi-hits, the tech choice, getup and ledge options by
where the opponent can punish, defence by value (grabs are threats a shield does not stop),
out-of-shield punishes, and recovering away from a guarded ledge.
"""

from dataclasses import replace

from helpers import place
from isofightr import config
from isofightr.ai import disadvantage, forecast, predict
from isofightr.ai.controller import CpuController
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.terrain import closest_point, recovery_ledge
from isofightr.ai.view import observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.fighter import Launch, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3

ROOK = load_character("rook")
KNOWN = knowledge_for(ROOK)
GRID = load_stage("training_grid")


def pair(x: float, y: float, gap: float = 0.6, damage: float = 0.0) -> Match:
    """A Rook at (x, y) facing south-east, another Rook ``gap`` in front of it."""
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], x, y, facing=Dir8.SE, damage=damage)
    ahead = Dir8.SE.world * gap
    place(match, match.fighters[1], x + ahead.x, y + ahead.y, facing=Dir8.NW)
    return match


# --- DI and SDI -----------------------------------------------------------------------------


def test_di_survives_whenever_some_choice_survives() -> None:
    """Near the east edge at high knockback: some holds KO, some do not; the CPU's never."""
    start = Vec3(11.0, 6.0, 0.0)
    for knockback in (120.0, 150.0, 180.0, 210.0):
        launch = Launch(knockback, Vec2(1.0, 0.0), 40.0, True)
        flights = forecast.di_flights(GRID, launch, start, True, ROOK)
        stick, vertical = disadvantage.di_choice(GRID, launch, start, True, ROOK, None)
        chosen = next(f for s, v, f in flights if s == stick and v == vertical)
        if not all(f.ko for _, _, f in flights):
            assert not chosen.ko, knockback


def test_di_leans_away_from_the_attacker_when_everything_lands_on_the_stage() -> None:
    start = Vec3(6.0, 6.0, 0.0)
    launch = Launch(40.0, Vec2(1.0, 0.0), 30.0, False)
    north = disadvantage.di_choice(GRID, launch, start, True, ROOK, Vec3(6.0, 4.0, 0.0))
    south = disadvantage.di_choice(GRID, launch, start, True, ROOK, Vec3(6.0, 8.0, 0.0))
    assert north[0].y > 0.0 and south[0].y < 0.0


def _hitlag_frames(level: int, knockback: float) -> list:
    match = pair(6.0, 6.0)
    cpu = CpuController(0, level, 1, GRID)
    victim, attacker = match.fighters
    victim.launch = Launch(knockback, Vec2(1.0, 0.0), 30.0, False)
    attacker.hitlag = 9
    frames = []
    for hitlag in range(9, 0, -1):
        victim.hitlag = hitlag
        frames.append((hitlag, cpu.think(match)))
    return frames


def test_a_level_9_cpu_flicks_sdi_away_from_a_multi_hit_then_holds_its_di() -> None:
    frames = _hitlag_frames(9, 20.0)
    flicks = [frame for hitlag, frame in frames if hitlag > 1 and frame.move != Vec2()]
    assert len(flicks) >= 3
    away = Vec2(6.0, 6.0) - (Vec2(6.0, 6.0) + Dir8.SE.world * 0.6)
    assert all(frame.move.dot(away) > 0.0 for frame in flicks), "out of the attacker's reach"
    gaps = [frame for hitlag, frame in frames if hitlag > 1 and frame.move == Vec2()]
    assert gaps, "a flick needs the stick to come back between presses"
    held = [frame for hitlag, frame in frames if hitlag <= 1]
    assert all(frame.move != Vec2() for frame in held), "the DI is held at the end"


def test_low_levels_do_not_sdi() -> None:
    frames = _hitlag_frames(3, 20.0)
    assert len({frame.move for hitlag, frame in frames if hitlag > 2}) <= 1


# --- tech, getup and ledge -----------------------------------------------------------------


def test_tech_away_from_an_opponent_waiting_where_the_tumble_lands() -> None:
    match = pair(6.0, 6.0)
    _me, other = observe(match).fighters
    landing = Vec3(6.0, 6.0, 0.0)
    assert disadvantage.tech_choice(landing, other, 1.0) == disadvantage.TECH_AWAY
    far = replace(other, pos=Vec3(12.0, 1.0, 0.0))
    assert disadvantage.tech_choice(landing, far, 1.0) == disadvantage.TECH_IN_PLACE
    assert disadvantage.tech_choice(landing, None, 1.0) == disadvantage.TECH_IN_PLACE


def test_option_risk_is_sure_inside_reach_and_nothing_far_away() -> None:
    match = pair(6.0, 6.0)
    _me, other = observe(match).fighters
    end = other.pos
    assert disadvantage.option_risk(end, 30, 0, other, KNOWN, 0.1) == 1.0
    far = Vec3(other.pos.x + 9.0, other.pos.y, 0.0)
    assert disadvantage.option_risk(far, 20, 10, other, KNOWN, 0.1) == 0.0
    middle = Vec3(other.pos.x + KNOWN.strike_reach + 1.0, other.pos.y, 0.0)
    risk = disadvantage.option_risk(middle, 30, 0, other, KNOWN, 0.1)
    assert 0.0 < risk < 1.0


def test_a_getup_attack_is_best_with_the_opponent_on_top_and_worst_with_nobody_there() -> None:
    match = pair(6.0, 6.0)
    me, other = observe(match).fighters
    downed = replace(me, state=StateId.KNOCKDOWN)
    menu = predict.getup_options(GRID, downed, ROOK)
    near = dict(disadvantage.option_values(menu, other, KNOWN, ROOK.movement.run_speed))
    assert max(near, key=near.__getitem__) == "attack"
    far = dict(
        disadvantage.option_values(
            menu, replace(other, pos=Vec3(12.0, 1.0, 0.0)), KNOWN, ROOK.movement.run_speed
        )
    )
    assert far["attack"] < far["stand"]


def test_ledge_options_never_include_letting_go_and_cost_more_with_a_guard_waiting() -> None:
    match = pair(6.0, 6.0)
    hanger = match.fighters[0]
    place(match, hanger, -0.35, 6.0, z=-1.8)
    me, other = observe(match).fighters
    menu = predict.ledge_options(GRID, me, ROOK)
    speed = ROOK.movement.run_speed
    on_top = dict(
        disadvantage.option_values(menu, replace(other, pos=Vec3(0.8, 6.0, 0.0)), KNOWN, speed)
    )
    away = dict(
        disadvantage.option_values(menu, replace(other, pos=Vec3(12.0, 1.0, 0.0)), KNOWN, speed)
    )
    assert "drop" not in on_top and set(on_top) == set(away)
    assert all(on_top[name] < away[name] for name in on_top if name != "attack")
    assert on_top["attack"] > away["attack"], "a ledge attack is for someone standing there"


def test_pick_follows_the_values_at_low_temperature_and_mixes_at_high() -> None:
    names = ["a", "b", "c"]
    values = [10.0, 0.0, -5.0]
    assert {disadvantage.pick(names, values, 0.5, r / 20) for r in range(20)} == {"a"}
    assert len({disadvantage.pick(names, [1.0, 0.5, 0.0], 8.0, r / 20) for r in range(20)}) == 3


# --- defence ---------------------------------------------------------------------------------


def test_a_grab_is_never_shielded_and_a_worn_shield_gives_way_to_a_dodge() -> None:
    against_grab = disadvantage.defence_options(KNOWN, 10, True, 50.0, 0)
    assert against_grab and all(option.name != "shield" for option in against_grab)
    names = {option.name for option in against_grab}
    assert names & {"spot dodge", "jump"}
    spot = KNOWN.utilities["spot_dodge"]
    assert spot.intangible is not None
    covered = spot.intangible[0] + 1
    fresh = disadvantage.defence_options(KNOWN, covered, False, 50.0, 0)
    worn = disadvantage.defence_options(KNOWN, covered, False, config.CPU_LOW_SHIELD - 1, 0)
    assert fresh[0].name == "shield"
    assert worn[0].name != "shield"


def test_a_grab_on_its_way_is_a_threat_the_cpu_dodges_or_jumps_rather_than_shields() -> None:
    match = pair(6.0, 6.0, gap=0.9)
    cpu = CpuController(0, 9, 1, GRID)
    cpu.think(match)
    match.tick([NEUTRAL_INPUT, InputFrame(held=int(Button.GRAB))])
    world = observe(match)
    me, other = world.fighters
    assert other.state is StateId.GRAB
    threat = cpu._threat(world, me, 0, 30)
    assert threat is not None and threat.grab and threat.source == other.pos
    answers = set()
    for seed in range(8):
        cpu = CpuController(0, 9, seed, GRID)
        cpu.think(match)
        cpu._defended.clear()  # its own look may already have judged this grab
        if cpu._defend(world, me, threat) is not None:
            answers.add(cpu.plan.detail)
    assert answers and answers <= {"spot dodge", "jump away", "roll away"}


def test_a_shielding_cpu_punishes_a_blocked_smash_out_of_shield() -> None:
    """A forward smash into the shield: once the shield stun is over and the smash is still
    in its end lag, the CPU grabs, up smashes or up specials straight out of the shield."""
    from isofightr.sim.states.interrupts import start_move

    match = pair(6.0, 6.0, gap=0.9)
    cpu = CpuController(0, 9, 1, GRID)
    me, other = match.fighters
    plans = set()
    for tick in range(90):
        frame = cpu.think(match)
        if me.state is StateId.SHIELD:
            plans.add(cpu.plan.detail)
        if tick == 6:
            start_move(match, other, "fsmash")
        if tick < 25 or me.state is not StateId.SHIELD:
            frame = InputFrame(held=int(Button.SHIELD))  # hold it up through the smash
            cpu.queue.clear()  # and forget whatever it meant to do from neutral
        match.tick([frame, NEUTRAL_INPUT])
        if other.state in (StateId.GRABBED, StateId.FLINCH, StateId.TUMBLE):
            break
    assert any(plan.endswith("out of shield") for plan in plans), plans
    assert other.state in (StateId.GRABBED, StateId.FLINCH, StateId.TUMBLE), other.state


# --- recovery --------------------------------------------------------------------------------


def test_recovery_heads_away_from_a_guard_on_the_ledge() -> None:
    off = Vec3(-2.0, 6.0, -1.0)
    plain = recovery_ledge(GRID, off, 10.0, None)
    assert plain is not None
    guarded = recovery_ledge(GRID, off, 10.0, None, [plain.point])
    assert guarded is not None
    assert (guarded.point - plain.point).length() >= config.CPU_GUARDED_LEDGE - 0.5
    assert closest_point(guarded.ledge, guarded.point) == guarded.point
