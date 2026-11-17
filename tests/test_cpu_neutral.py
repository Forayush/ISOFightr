"""Tests for the CPU's new decisions in neutral (plan note "15 - CPU AI", decision D-071,
M20 group 2): the intercept search, the expected-value formula, the choice, the situations,
and scenarios for each neutral tactic, played against the real sim.
"""

from dataclasses import replace

from helpers import place
from isofightr import config
from isofightr.ai import intercept
from isofightr.ai.bots import make_bot
from isofightr.ai.controller import CpuController
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.predict import Track, track
from isofightr.ai.situation import Situation, classify
from isofightr.ai.view import FighterView, observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.events import GrabEvent, HitEvent
from isofightr.sim.fighter import Launch, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.states.interrupts import start_move

ROOK = load_character("rook")
KNOWN = knowledge_for(ROOK)
SE = Dir8.SE.world


def duel(distance: float, stage: str = "final_plateau", seed: int = 1) -> Match:
    """Two Rooks facing each other ``distance`` units apart."""
    match = Match.create(load_stage(stage), [ROOK, ROOK], seed=seed, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], 6.0, 5.0, facing=Dir8.SE)
    place(match, match.fighters[1], 6.0 + SE.x * distance, 5.0 + SE.y * distance, facing=Dir8.NW)
    return match


def views(match: Match) -> tuple[FighterView, FighterView]:
    world = observe(match)
    return world.fighters[0], world.fighters[1]


def still(view: FighterView, frames: int = 70, locked: int = 70, spread: float = 0.0) -> Track:
    """A target that stays where it is: locked for ``locked`` frames, then ``spread`` a frame."""
    doubt = tuple(max(f - locked, 0) * spread for f in range(1, frames + 1))
    return Track((view.pos,) * frames, doubt, locked)


def reading_for(match: Match, target_track: Track | None = None) -> intercept.Reading:
    me, target = views(match)
    if target_track is None:
        target_track = track(match.stage, target, ROOK, KNOWN)
    return intercept.Reading(match.stage, me, target, target_track, ROOK, KNOWN)


# --- the intercept search -----------------------------------------------------------------


def test_a_locked_target_in_reach_is_hit_for_certain_on_the_moves_first_active_frame() -> None:
    match = duel(1.0)
    me, target = views(match)
    jab = KNOWN.action("jab")
    frame, chance = intercept.connect(me, target, jab, me.facing.world, still(target))
    assert (frame, chance) == (jab.first_hit, 1.0)


def test_a_target_out_of_reach_is_never_hit_and_one_at_the_tip_only_maybe() -> None:
    match = duel(6.0)
    me, target = views(match)
    jab = KNOWN.action("jab")
    assert intercept.connect(me, target, jab, me.facing.world, still(target)) == (0, 0.0)
    match = duel(1.45)
    me, target = views(match)
    loose = still(target, locked=0, spread=0.3)
    frame, chance = intercept.connect(me, target, jab, me.facing.world, loose)
    assert frame == jab.first_hit and 0.0 < chance < 1.0, "a free target may step away"


def test_a_target_that_is_intangible_on_the_active_frames_is_not_counted_on() -> None:
    match = duel(1.0)
    me, target = views(match)
    jab = KNOWN.action("jab")
    safe = replace(target, intangible_left=jab.last_hit)
    assert intercept.connect(me, safe, jab, me.facing.world, still(safe)) == (0, 0.0)


def test_a_run_up_reaches_a_target_a_standing_move_cannot() -> None:
    match = duel(3.5)
    me, target = views(match)
    run_up = next(a for a in KNOWN.approaches if a.name == "run12_dash_attack")
    assert intercept.connect(me, target, KNOWN.action("fsmash"), SE, still(target)) == (0, 0.0)
    frame, chance = intercept.connect(me, target, run_up, SE, still(target))
    assert chance == 1.0 and frame > run_up.lead


def test_the_search_skips_what_the_caller_forbids_and_what_starts_in_the_air() -> None:
    match = duel(1.0)
    reading = reading_for(match, still(views(match)[1]))
    everything = intercept.search(reading, KNOWN.actions, lambda action, aim: True)
    names = {candidate.action.name for candidate in everything}
    assert "jab" in names and not any(name.startswith("air_") for name in names)
    nothing = intercept.search(reading, KNOWN.actions, lambda action, aim: False)
    assert nothing == []


# --- what a candidate is worth --------------------------------------------------------------


def test_a_sure_hit_is_worth_its_damage_and_a_shielded_one_is_not() -> None:
    match = duel(1.0)
    reading = reading_for(match, still(views(match)[1]))
    jab = KNOWN.action("jab")
    sure = intercept.weigh(reading, jab, SE, jab.first_hit, 1.0)
    assert sure.hit == 1.0 and sure.value > jab.damage
    shielding = replace(reading.target, state=StateId.SHIELD)
    blocked = intercept.weigh(replace(reading, target=shielding), jab, SE, jab.first_hit, 1.0)
    assert blocked.hit == 0.0 and blocked.value < sure.value
    grab = KNOWN.action("grab")
    grabbed = intercept.weigh(replace(reading, target=shielding), grab, SE, grab.first_hit, 1.0)
    assert grabbed.hit == 1.0 and grabbed.value > blocked.value, "grab the shield"


def test_a_hit_that_kos_is_worth_a_stock() -> None:
    match = duel(1.0)
    reading = reading_for(match, still(views(match)[1]))
    smash = KNOWN.action("fsmash")
    fresh = intercept.weigh(reading, smash, SE, smash.first_hit, 1.0)
    high = replace(reading, target=replace(reading.target, damage=220.0))
    finishing = intercept.weigh(high, smash, SE, smash.first_hit, 1.0)
    assert finishing.kills and not fresh.kills
    assert finishing.value > fresh.value + config.CPU_KO_VALUE * 0.8


def test_a_slow_move_inside_a_free_opponents_reach_risks_being_beaten() -> None:
    match = duel(1.0)
    _me, target = views(match)
    free = track(match.stage, target, ROOK, KNOWN)
    smash = KNOWN.action("fsmash")
    open_up = intercept.weigh(reading_for(match, still(target)), smash, SE, smash.first_hit, 1.0)
    contested = intercept.weigh(reading_for(match, free), smash, SE, smash.first_hit, 1.0)
    assert contested.value < open_up.value - 5.0


def test_a_move_carried_into_a_swing_that_is_coming_is_worthless() -> None:
    match = duel(2.2)
    start_move(match, match.fighters[1], "fsmash")
    match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
    _me, target = views(match)
    theirs = KNOWN.ground_by_move["fsmash"]
    reading = replace(
        reading_for(match),
        their_action=theirs,
        their_frame=theirs.move_start + target.state_frame - 1,
    )
    run_in = next(a for a in KNOWN.approaches if a.name == "run6_dash_attack")
    assert intercept.danger(reading, run_in, SE, 30) > 0
    assert intercept.danger(reading, KNOWN.action("jab"), SE, 2) == 0


def test_choose_takes_the_best_when_cool_and_nothing_below_the_bar() -> None:
    action = KNOWN.action("jab")

    def candidate(value: float) -> intercept.Candidate:
        return intercept.Candidate(action, SE, 3, 1.0, value)

    found = [candidate(2.0), candidate(9.0), candidate(5.0)]
    for roll in (0.0, 0.5, 0.999):
        chosen = intercept.choose(found, 0.01, roll)
        assert chosen is not None and chosen.value == 9.0
    warm = {intercept.choose(found, 100.0, roll / 10).value for roll in range(10)}  # type: ignore[union-attr]
    assert len(warm) > 1, "a high temperature also picks worse things"
    assert intercept.choose([candidate(config.CPU_ACT_VALUE - 0.1)], 1.0, 0.5) is None
    assert intercept.choose([], 1.0, 0.5) is None


# --- situations ---------------------------------------------------------------------------


def test_the_situation_is_named_from_both_sides() -> None:
    match = duel(1.0)
    me, target = views(match)
    assert classify(me, target, still(target, locked=0)).situation is Situation.NEUTRAL
    assert classify(me, target, still(target, locked=10)).why == "an opening"
    hit = replace(target, hitlag=5, launch=Launch(90.0, SE, 40.0, True))
    assert classify(me, hit, None).situation is Situation.ADVANTAGE
    stunned = replace(me, hitstun=12)
    assert classify(stunned, target, None).situation is Situation.DISADVANTAGE
    assert classify(me, target, None, target_off_stage=True).why == "off the stage"
    assert classify(me, None, None).situation is Situation.NEUTRAL


# --- scenarios ------------------------------------------------------------------------------


def play(match: Match, cpu: CpuController, ticks: int, other=None) -> list[object]:
    events: list[object] = []
    for _ in range(ticks):
        world = observe(match)
        second = other.think(match, world) if other is not None else NEUTRAL_INPUT
        match.tick([cpu.think(match, world), second])
        events += match.events
    return events


def test_a_whiffed_smash_is_punished() -> None:
    """The opponent swings a forward smash that falls short: a level 9 CPU hits it before
    it can act again, most of the time."""
    punished = 0
    for seed in range(10):
        match = duel(3.0, seed=seed)
        cpu = CpuController(0, 9, seed, match.stage)
        play(match, cpu, 30)  # let it settle; it may close in a little
        swinger = match.fighters[1]
        start_move(match, swinger, "fsmash")
        faf = ROOK.moves["fsmash"].faf
        events = play(match, cpu, faf + 5)
        if any(
            isinstance(e, HitEvent | GrabEvent)
            and getattr(e, "attacker", getattr(e, "grabber", -1)) == 0
            for e in events
        ):
            punished += 1
    assert punished >= 6


def test_a_shield_holder_is_grabbed() -> None:
    """The M10 CPU could not get past a held shield, and an early M20 build stood beside
    one forever: the shield bot on Final Plateau, seed 31."""
    for character in ("zephyr", "rook"):
        stage = load_stage("final_plateau")
        match = Match.create(
            stage, [load_character(character), ROOK], seed=31, rules=MatchRules(stocks=None)
        )
        cpu = CpuController(0, 9, 31, stage)
        bot = make_bot("shield", 1, 31, stage)
        events = play(match, cpu, 20 * 60, bot)
        grabs = [e for e in events if isinstance(e, GrabEvent) and e.grabber == 0]
        assert grabs, f"{character} never grabbed the shield"


def test_an_opponent_that_cannot_be_hit_is_given_room() -> None:
    match = duel(1.5)
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 2)
    match.fighters[1].invincible_frames = 120
    started_near = (match.fighters[0].pos - match.fighters[1].pos).length()
    seen_late = cpu.level.tracking_frames + 1
    for tick in range(100):
        before = cpu.plan
        play(match, cpu, 1)
        started = cpu.plan is not before and cpu.plan.kind == "attack"
        assert not (started and tick >= seen_late), "never swing at an invincible opponent"
    away = (match.fighters[0].pos - match.fighters[1].pos).length()
    assert away > started_near + 1.0


def test_it_keeps_its_distance_then_closes_in_when_nothing_happens() -> None:
    match = duel(1.0)
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 1)
    world = observe(match)
    me, target = views(match)
    reading = cpu._read(world, me, target, None)
    cpu._last_attack = cpu._last_landed = world.frame
    near = cpu._position(world, me, target, reading)
    # Out of its quick reach, as far as a brawler stands off (the cap is under Rook's lunge).
    least = config.CPU_HOVER_MAX + config.CPU_SWAY[0] - 0.01
    assert (near.xy - target.pos.xy).length() >= least
    cpu._last_landed = world.frame - 3 * config.CPU_PATIENCE_FRAMES  # no hit in a while
    cpu._sway_until = 0
    impatient = cpu._position(world, me, target, reading)
    assert (impatient.xy - target.pos.xy).length() < config.CPU_CLOSE_RANGE + 0.6


def test_a_run_up_is_called_off_when_the_target_is_not_where_it_was_expected() -> None:
    match = duel(4.0)
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 1)
    run_up = next(a for a in KNOWN.approaches if a.name == "run12_dash_attack")
    world = observe(match)
    me, target = views(match)
    reading = cpu._read(world, me, target, None)
    cpu._attack(world, target, intercept.Candidate(run_up, SE, 20, 1.0, 10.0), reading)
    assert cpu.queue and cpu._committed is not None
    place(match, match.fighters[1], 2.0, 9.0)  # gone elsewhere
    me = match.fighters[0]
    for _ in range(run_up.lead + 20):
        play(match, cpu, 1)
        assert not (me.state is StateId.ATTACK and me.move_id == "dash_attack"), "it swung"
    assert cpu._committed is None


def test_thinking_still_never_changes_the_match_and_is_deterministic() -> None:
    hashes = []
    for _ in range(2):
        match = duel(4.0, seed=7)
        cpus = [CpuController(index, 9, 7, match.stage) for index in range(2)]
        for _ in range(900):
            world = observe(match)
            before = match.state_hash()
            frames = [cpu.think(match, world) for cpu in cpus]
            assert match.state_hash() == before
            match.tick(frames)
        hashes.append(match.state_hash())
    assert hashes[0] == hashes[1]


# --- staying alive (found by the bots in M20 group 2) ---------------------------------------


def test_nothing_is_chosen_that_carries_the_cpu_out_of_the_blast_zone() -> None:
    """Zephyr, high up after a double jump, flew its straight-up up special out of the top."""
    zephyr = load_character("zephyr")
    match = Match.create(
        load_stage("final_plateau"), [zephyr, ROOK], seed=1, rules=MatchRules(stocks=None)
    )
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 1)
    me = observe(match).fighters[0]
    up = knowledge_for(zephyr).extra("air_uspecial_up")
    me = replace(me, vel=Vec3(0.0, 0.0, 0.0), grounded=False)
    low = replace(me, pos=Vec3(me.pos.x, me.pos.y, me.pos.z + 1.0))
    high = replace(me, pos=Vec3(me.pos.x, me.pos.y, match.stage.blast_zone.z_max - 6.0))
    assert cpu._safe(low, up, me.facing.world)
    assert not cpu._safe(high, up, me.facing.world)


def test_a_ground_move_whose_path_leaves_the_ground_is_not_safe() -> None:
    match = duel(1.0)
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 1)
    me = observe(match).fighters[0]
    walk_up = next(a for a in KNOWN.approaches if a.name == "walk16_dtilt")
    assert cpu._safe(me, walk_up, SE)
    run_up = next(a for a in KNOWN.approaches if a.name == "run20_dash_attack")
    stage = match.stage
    right = max(x + 0.5 for x in range(40) if stage.surface_top(x + 0.5, me.pos.y) is not None)
    at_edge = replace(me, pos=Vec3(right - 0.6, me.pos.y, me.pos.z))
    assert not cpu._safe(at_edge, run_up, Vec2(1.0, 0.0)), "it would run off the edge"


def test_run_ups_are_only_used_from_a_standstill() -> None:
    match = duel(4.0)
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 1)
    names: set[str] = set()
    original = intercept.search

    def watching(reading, actions, allowed):  # type: ignore[no-untyped-def]
        listed = list(actions)
        names.update(action.name for action in listed)
        return original(reading, listed, allowed)

    intercept.search = watching  # type: ignore[assignment]
    try:
        world = observe(match)
        me, target = views(match)
        me = replace(me, vel=Vec3(0.0, 0.0, 0.0))  # standing (it may already be moving)
        cpu._choose(cpu._read(world, me, target, None))
        assert any(name.startswith("run") for name in names), "standing: run-ups are searched"
        names.clear()
        running = replace(me, vel=Vec3(0.12, 0.0, 0.0))
        cpu._choose(cpu._read(world, running, target, None))
        assert names and not any(name.startswith(("run", "walk")) for name in names)
    finally:
        intercept.search = original  # type: ignore[assignment]


def test_a_ground_move_still_queued_is_dropped_when_the_cpu_leaves_the_ground() -> None:
    match = duel(4.0)
    cpu = CpuController(0, 9, 1, match.stage)
    play(match, cpu, 1)
    world = observe(match)
    me, target = views(match)
    walk_up = next(a for a in KNOWN.approaches if a.name == "walk16_dtilt")
    cpu._attack(
        world,
        target,
        intercept.Candidate(walk_up, SE, 25, 1.0, 10.0),
        cpu._read(world, me, target, None),
    )
    assert cpu.queue and cpu._queued is not None
    fighter = match.fighters[0]
    place(match, fighter, fighter.pos.x, fighter.pos.y, z=fighter.pos.z + 2.0)
    play(match, cpu, 1)
    assert not cpu.queue, "the rest would have come out as a down air"
