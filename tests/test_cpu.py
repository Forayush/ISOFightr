"""Tests for the CPU opponents (plan note "15 - CPU AI").

The CPU only ever turns a read-only view of the match into ``InputFrame``s, so these tests
run real matches with CPUs in them and check what happens: it reaches and hits its target on
every stage, recovers from off the stage with every character, techs, DIs, shields what it
sees coming, mashes out of grabs, never changes the match by itself, and is deterministic.
"""

from dataclasses import fields

import pytest

from helpers import place, run
from isofightr import config
from isofightr.ai.controller import CpuController
from isofightr.ai.knowledge import Start, knowledge_for
from isofightr.ai.levels import cpu_level
from isofightr.ai.terrain import region_of, regions, route
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.headless import run_cpu_match, run_headless
from isofightr.sim.character_def import MoveSet
from isofightr.sim.events import HitEvent, KoEvent
from isofightr.sim.fighter import Launch, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.replay import Recorder, play_back
from isofightr.sim.states.base import change_state

CHARACTERS = ("rook", "bramble", "zephyr", "mote")
STAGES = ("sky_ruins", "final_plateau", "training_grid", "twin_isles", "lily_pads")


def cpu_match(
    stage: str, characters: tuple[str, ...], levels: tuple[int, ...], seed: int = 1
) -> tuple[Match, list[CpuController | None]]:
    built = load_stage(stage)
    match = Match.create(
        built, [load_character(c) for c in characters], seed=seed, rules=MatchRules(stocks=None)
    )
    cpus = [
        CpuController(index, level, seed, built) if level else None
        for index, level in enumerate(levels)
    ]
    return match, cpus


def play(match: Match, cpus: list[CpuController | None], ticks: int) -> list[object]:
    """Run ``ticks`` ticks with CPUs and idle players; return every event."""
    events: list[object] = []
    for _ in range(ticks):
        match.tick([cpu.think(match) if cpu else NEUTRAL_INPUT for cpu in cpus])
        events += match.events
    return events


# --- levels and knowledge ---------------------------------------------------------------------


def test_levels_follow_the_plan_table_and_interpolate_between_anchors() -> None:
    assert cpu_level(1).reaction_frames == 40 and cpu_level(9).reaction_frames == 7
    assert cpu_level(5).defend_chance == pytest.approx(0.40)
    assert cpu_level(2).reaction_frames == 34, "halfway between levels 1 and 3"
    assert cpu_level(9).tech_chance == pytest.approx(0.90)
    reactions = [cpu_level(level).reaction_frames for level in range(1, 10)]
    assert reactions == sorted(reactions, reverse=True), "higher levels react sooner"
    for bad in (0, 10):
        with pytest.raises(ValueError, match="CPU level"):
            cpu_level(bad)


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_move_knowledge_is_recorded_from_the_real_moves(character_id: str) -> None:
    character = load_character(character_id)
    knowledge = knowledge_for(character)
    assert knowledge_for(character) is knowledge, "cached"
    recorded = {action.move_id for action in knowledge.actions}
    moveset = character.moveset
    for field in fields(MoveSet):
        if field.name in ("jab", "getup_attack", "ledge_attack", "taunt"):
            continue
        assert getattr(moveset, field.name) in recorded or field.name == "dspecial", field.name
    jab = knowledge.action("jab")
    first_window = character.moves[moveset.jab[0]].windows[0].frames.first
    assert jab.first_hit == first_window, "the jab's hitbox comes out on its data's frame"
    sh_nair = knowledge.action("sh_nair")
    assert sh_nair.move_start == character.movement.jumpsquat + 1, "after the jumpsquat"
    assert sh_nair.start is Start.GROUND and knowledge.action("air_nair").start is Start.AIR
    assert knowledge.action("ftilt").turns and knowledge.action("fsmash").turns
    assert not knowledge.action("jab").turns
    assert knowledge.action("grab").grab and knowledge.action("grab").first_hit > 0
    assert knowledge.up_special is not None and knowledge.up_special.helpless
    assert knowledge.up_special_rise > 1.0, "every up special gains height"
    assert knowledge.jump_distance > 3.0


def test_only_mote_has_a_projectile_long_enough_to_zone() -> None:
    zoners = [
        c
        for c in CHARACTERS
        if knowledge_for(load_character(c)).projectile_reach >= config.CPU_ZONER_REACH
    ]
    assert zoners == ["mote"]


# --- terrain -------------------------------------------------------------------------------


def test_routes_cross_lily_pads_through_the_middle() -> None:
    stage = load_stage("lily_pads")
    here = region_of(stage, Vec3(4.5, 13.5, 1.0))
    there = region_of(stage, Vec3(13.5, 4.5, 1.0))
    assert here is not None and there is not None and here != there
    knowledge = knowledge_for(load_character("rook"))
    reach = knowledge.jump_distance * config.CPU_JUMP_REACH_SHARE
    rise = (knowledge.full_hop_rise + knowledge.air_jump_rise) * config.CPU_JUMP_RISE_SHARE
    chain = route(stage, here, there, reach, rise)
    assert len(chain) >= 2, "too far for one jump"
    assert chain[-1].target == there
    assert len(regions(stage)) >= 5


# --- behaviour in matches ------------------------------------------------------------------


def test_thinking_never_changes_the_match() -> None:
    match, cpus = cpu_match("sky_ruins", ("rook", "rook"), (9, 9))
    for _ in range(300):
        before = match.state_hash()
        frames = [cpu.think(match) for cpu in cpus if cpu is not None]
        assert match.state_hash() == before
        match.tick(frames)


def test_cpus_are_deterministic_for_a_seed() -> None:
    hashes = []
    for _ in range(2):
        match, cpus = cpu_match("twin_isles", CHARACTERS, (9, 5, 3, 7), seed=11)
        play(match, cpus, 1200)
        hashes.append(match.state_hash())
    assert hashes[0] == hashes[1]
    match, cpus = cpu_match("twin_isles", CHARACTERS, (9, 5, 3, 7), seed=12)
    play(match, cpus, 1200)
    assert match.state_hash() != hashes[0], "another seed plays differently"


@pytest.mark.parametrize(
    ("stage", "character"),
    list(zip(STAGES, ("rook", "bramble", "zephyr", "mote", "rook"), strict=True)),
)
def test_a_level_9_cpu_reaches_and_hits_a_standing_opponent(stage: str, character: str) -> None:
    match, cpus = cpu_match(stage, (character, "rook"), (9, 0))
    events = play(match, cpus, 30 * 60)
    dealt = sum(e.damage for e in events if isinstance(e, HitEvent) and e.attacker == 0)
    assert dealt > 50.0
    own_falls = [e for e in events if isinstance(e, KoEvent) and e.player == 0]
    assert not own_falls, "it never falls off on its own"


@pytest.mark.parametrize("level", [1, 9])
@pytest.mark.parametrize("character_id", CHARACTERS)
@pytest.mark.parametrize("side", ["west", "east"])
def test_every_cpu_recovers_from_off_the_stage(character_id: str, level: int, side: str) -> None:
    match, cpus = cpu_match("training_grid", (character_id, "rook"), (level, 0))
    fighter = match.fighters[0]
    place(match, match.fighters[1], 6.0, 6.0)
    x, facing = (-3.0, Dir8.SE) if side == "west" else (15.0, Dir8.NW)
    place(match, fighter, x, 6.0, z=-1.0, facing=facing)
    for _ in range(300):
        play(match, cpus, 1)
        if fighter.grounded and fighter.state is not StateId.KO:
            break
    assert fighter.stocks is None or fighter.in_play
    assert fighter.grounded or fighter.state is StateId.LEDGE_HANG, f"fell: {fighter.pos}"


def test_a_level_9_cpu_techs_most_landings_and_level_1_never_does() -> None:
    def techs(level: int) -> int:
        count = 0
        for seed in range(8):
            match, cpus = cpu_match("final_plateau", ("rook", "rook"), (level, 0), seed=seed)
            fighter = match.fighters[0]
            place(match, fighter, 7.0, 5.0, z=2.5)
            change_state(match, fighter, StateId.TUMBLE)
            fighter.hitstun = 60
            for _ in range(80):
                play(match, cpus, 1)
                if fighter.grounded:
                    break
            count += fighter.state in (StateId.TECH, StateId.TECH_ROLL)
        return count

    assert techs(9) >= 5
    assert techs(1) == 0


def test_a_launched_cpu_holds_survival_di_toward_the_middle() -> None:
    match, cpus = cpu_match("final_plateau", ("rook", "rook"), (9, 0))
    fighter = match.fighters[0]
    place(match, fighter, 12.0, 8.0)  # the stage's middle is at (7, 5)
    fighter.hitlag = 5
    fighter.launch = Launch(150.0, Vec2(1.0, 0.0), 30.0, True)
    cpu = cpus[0]
    assert cpu is not None
    frame = cpu.think(match)
    assert frame.move.y < -0.9, "across the launch (+x), on the side of the stage's middle"


def test_a_cpu_shields_a_smash_it_sees_coming_at_high_levels() -> None:
    def shields(level: int) -> int:
        count = 0
        for seed in range(10):
            match, cpus = cpu_match("final_plateau", ("rook", "rook"), (level, 0), seed=seed)
            cpu, attacker = match.fighters
            place(match, cpu, 7.0, 5.0, facing=Dir8.NW)
            place(match, attacker, 5.6, 5.0, facing=Dir8.SE)
            smash = InputFrame(held=int(Button.STRONG))
            controller = cpus[0]
            assert controller is not None
            # Only the defence layer is under test: the CPU neither attacks nor moves.
            controller._next_decision = 10**9
            controller._move_goal = cpu.pos
            for tick in range(40):
                frames = [controller.think(match), NEUTRAL_INPUT]
                if tick == 0:
                    frames[1] = smash
                match.tick(frames)
                if cpu.state is StateId.SHIELD:
                    count += 1
                    break
        return count

    assert shields(9) >= 5
    assert shields(1) <= 3


def test_a_grabbed_cpu_mashes_out_sooner_than_an_idle_player() -> None:
    def held_for(level: int) -> int:
        match, cpus = cpu_match("final_plateau", ("rook", "rook"), (0, level))
        grabber, victim = match.fighters
        place(match, grabber, 7.0, 5.0, facing=Dir8.SE)
        place(match, victim, 7.8, 5.0, facing=Dir8.NW)
        run(match, [InputFrame(held=int(Button.GRAB))])
        for _ in range(20):
            match.tick([NEUTRAL_INPUT, cpus[1].think(match) if cpus[1] else NEUTRAL_INPUT])
            if victim.state is StateId.GRABBED:
                break
        assert victim.state is StateId.GRABBED
        for tick in range(600):
            match.tick([NEUTRAL_INPUT, cpus[1].think(match) if cpus[1] else NEUTRAL_INPUT])
            if victim.state is not StateId.GRABBED:
                return tick
        return 600

    assert held_for(9) < held_for(0)


def test_higher_levels_beat_lower_ones() -> None:
    report = run_cpu_match(
        load_stage("final_plateau"),
        [load_character("rook")] * 2,
        (2, 9),
        seed=5,
        rules=MatchRules(stocks=1),
        max_ticks=60 * 60 * 3,
    )
    assert report.ended and report.knockouts == 1
    assert report.winners == (1,), "the level 9 CPU wins"


def test_headless_cpus_record_and_replay_exactly() -> None:
    stage = load_stage("sky_ruins")
    characters = [load_character(c) for c in ("zephyr", "mote")]
    recorder = Recorder(stage.id, ("zephyr", "mote"), 4, MatchRules(stocks=None))
    run_headless(stage, characters, 4, 900, recorder, cpus=(9, 6))
    assert recorder.final is not None
    replay = recorder.final
    match = Match.create(stage, characters, seed=4, rules=MatchRules(stocks=None))
    assert play_back(match, replay)


def test_a_cpu_does_nothing_during_the_countdown() -> None:
    stage = load_stage("sky_ruins")
    match = Match.create(
        stage, [load_character("rook")] * 2, rules=MatchRules(stocks=3, countdown_frames=60)
    )
    cpu = CpuController(0, 9, 0, stage)
    for _ in range(59):
        assert cpu.think(match) == NEUTRAL_INPUT
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
