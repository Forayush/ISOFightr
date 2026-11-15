"""Tests for what the CPU can see and know since M20 group 1 (plan note "15 - CPU AI",
decision D-071): the wider view, beliefs (tracking is fast, reacting is slow), and the
additions to the recorded move knowledge. None of it may change how the CPU plays yet.
"""

from pathlib import Path
from typing import Any

import pytest

from helpers import place
from isofightr import config
from isofightr.ai import knowledge as know
from isofightr.ai.belief import CLOSE_ATTENTION, Beliefs
from isofightr.ai.classic.knowledge import knowledge_for as classic_knowledge_for
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.levels import cpu_level
from isofightr.ai.view import WorldView, observe
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as combat
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.rng import Rng
from isofightr.sim.states.interrupts import start_move

PINNED = Path(__file__).parent / "fixtures" / "cpu_classic.json"
CHARACTERS = list_character_ids()


def grid_match(*names: str, rules: MatchRules | None = None) -> Match:
    stage = load_stage("training_grid")
    characters = [load_character(name) for name in names]
    match = Match.create(stage, characters, seed=2, rules=rules or MatchRules(stocks=None))
    for index, fighter in enumerate(match.fighters):
        place(match, fighter, 3.0 + 3.0 * index, 6.0)
    return match


def idle(match: Match) -> list[InputFrame]:
    return [NEUTRAL_INPUT] * len(match.fighters)


# --- nothing changes how the CPU plays, yet -----------------------------------------------


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_the_actions_the_m10_cpu_reads_are_recorded_as_before(character_id: str) -> None:
    character = load_character(character_id)
    new, old = knowledge_for(character), classic_knowledge_for(character)
    assert [action.name for action in new.actions] == [action.name for action in old.actions]
    for mine, theirs in zip(new.actions, old.actions, strict=True):
        assert mine.path == theirs.path and mine.commit == theirs.commit
        assert mine.hit_frames == theirs.hit_frames or (
            [frame.frame for frame in mine.hit_frames]
            == [frame.frame for frame in theirs.hit_frames]
        )
        assert (mine.damage, mine.turns, mine.helpless) == (
            theirs.damage,
            theirs.turns,
            theirs.helpless,
        )
    assert set(new.ground_by_move) == set(old.ground_by_move)
    assert new.up_special_rise == old.up_special_rise


# --- knowledge ----------------------------------------------------------------------------


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_every_action_knows_its_hitboxes_and_how_far_it_reaches(character_id: str) -> None:
    character = load_character(character_id)
    knowledge = knowledge_for(character)
    for action in (*knowledge.actions, *knowledge.extras):
        if action.grab or not action.hit_frames:
            continue
        assert action.outcomes, action.name
        assert action.outcomes[0].frame == action.first_hit, action.name
        assert [o.frame for o in action.outcomes] == sorted(o.frame for o in action.outcomes)
        own = [s for f in action.hit_frames for s in f.spheres if not s.projectile]
        if own:
            assert action.envelope is not None
            assert action.envelope.radius >= max(action.envelope.reach) - 1e-9
            assert action.envelope.z_low < action.envelope.z_high
    smash = knowledge.action("fsmash")
    assert smash.envelope is not None
    forward, behind = smash.envelope.reach[0], smash.envelope.reach[4]
    assert forward > 1.5 > behind
    assert smash.envelope.along(Vec2(1.0, 0.0)) == forward
    assert smash.envelope.along(Vec2(-1.0, 0.1)) == behind
    assert smash.envelope.first_frame[0] == smash.first_hit
    assert smash.remaining(smash.first_hit) == smash.commit - smash.first_hit


def test_roles_come_from_the_move_data() -> None:
    def roles(character_id: str, action: str) -> frozenset[str]:
        return knowledge_for(load_character(character_id)).action(action).roles

    assert know.ROLE_COUNTER in roles("rook", "dspecial")
    assert know.ROLE_REFLECT in roles("zephyr", "dspecial")
    assert {know.ROLE_ARMOR, know.ROLE_CHARGE} <= roles("bramble", "fsmash")
    assert know.ROLE_TRAP in roles("mote", "dspecial")
    assert know.ROLE_PROJECTILE in roles("mote", "nspecial")
    assert know.ROLE_SHOCKWAVE in roles("bramble", "nspecial")
    assert know.ROLE_RECOVERY in roles("rook", "air_uspecial")
    assert roles("rook", "jab") == frozenset()
    assert know.roles_of(None) == frozenset()


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_jab_chains_and_charged_smashes_are_recorded(character_id: str) -> None:
    character = load_character(character_id)
    knowledge = knowledge_for(character)
    chain = character.moveset.jab
    for count in range(2, len(chain) + 1):
        action = knowledge.extra(f"jab_x{count}")
        boxes = [outcome.box for outcome in action.outcomes]
        for move_id in chain[:count]:
            move = character.moves[move_id]
            own = [box for window in move.windows for box in window.hitboxes]
            assert any(box in own for box in boxes), f"{action.name} never reached {move_id}"
    for name in ("fsmash", "usmash", "dsmash"):
        plain, charged = knowledge.action(name), knowledge.extra(f"{name}_charged")
        assert charged.charge > 1.0 == plain.charge
        assert charged.first_hit > plain.first_hit + 30
        assert know.ROLE_CHARGE in charged.roles
    assert knowledge.extra("air_uspecial_up").path
    with pytest.raises(KeyError):
        knowledge.extra("jab_x9")


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_movement_options_are_recorded_from_the_real_sim(character_id: str) -> None:
    character = load_character(character_id)
    knowledge = knowledge_for(character)
    used = knowledge.utilities
    assert set(used) == {name for name, _, _ in know._utility_recipes()}
    assert used["run"].offset_at(know.RUN_FRAMES).x > used["walk"].offset_at(know.RUN_FRAMES).x > 1
    assert "roll" in used["roll_fwd"].states and "roll" in used["roll_back"].states
    assert used["roll_fwd"].path[-1].x == pytest.approx(combat.ROLL_DISTANCE)
    assert used["roll_back"].path[-1].x == pytest.approx(-combat.ROLL_DISTANCE)
    assert "spot_dodge" in used["spot_dodge"].states
    for name in ("roll_fwd", "spot_dodge", "air_dodge", "air_dodge_fwd"):
        safe = used[name].intangible
        assert safe is not None and safe[1] > safe[0]
    assert used["run"].intangible is None
    full = max(point.z for point in used["full_hop"].path)
    short = max(point.z for point in used["short_hop"].path)
    assert full == pytest.approx(knowledge.full_hop_rise, abs=0.01) and short < full
    assert used["full_hop_fwd"].path[-1].x > 1.0 > used["full_hop_back"].path[-1].x
    assert max(p.z for p in used["air_jump"].path) == pytest.approx(
        knowledge.air_jump_rise, abs=0.01
    )
    assert used["fast_fall"].landed < used["drift_fwd"].landed
    assert used["turn"].states[1] == "turn" and used["turn"].free <= 6
    assert used["short_hop"].free < used["short_hop"].landed, "free in the air before landing"


def test_two_loads_of_one_character_share_one_recording() -> None:
    first = knowledge_for(load_character("rook"))
    assert knowledge_for(load_character("rook")) is first


# --- the view -----------------------------------------------------------------------------


def test_the_view_shows_shield_stocks_score_clock_and_knockback() -> None:
    rules = MatchRules(stocks=3, time_frames=3600)
    match = grid_match("rook", "rook", rules=rules)
    world = observe(match)
    assert world.time_left == 3600 and not world.sudden_death
    assert world.hazards == () and world.platforms == ()
    assert [view.stocks for view in world.fighters] == [3, 3]
    assert world.fighters[0].shield_hp == combat.SHIELD_MAX_HP
    for _ in range(30):
        match.tick([InputFrame(held=int(Button.SHIELD)), NEUTRAL_INPUT])
    assert observe(match).fighters[0].shield_hp < combat.SHIELD_MAX_HP
    one, two = match.fighters
    place(match, two, 3.9, 6.0, facing=Dir8.NW)
    two.damage = 80.0
    one.facing = Dir8.SE
    place(match, two, 3.0 + Dir8.SE.world.x * 0.9, 6.0 + Dir8.SE.world.y * 0.9)
    for _ in range(10):
        match.tick(idle(match))
    start_move(match, one, "fsmash")
    seen = False
    for _ in range(60):
        match.tick(idle(match))
        view = observe(match).fighters[1]
        if view.hitstun > 0 and view.hitlag == 0:
            assert view.kb_vel.length() > 0.05
            assert (view.vel - view.kb_vel).length() < view.vel.length()
            seen = True
            break
    assert seen
    two.pos = Vec3(60.0, 6.0, 0.0)
    match.tick(idle(match))
    world = observe(match)
    assert world.fighters[1].stocks == 2 and world.fighters[1].score == -1
    assert world.fighters[0].score == 1 and world.time_left < 3600


def test_the_view_flags_armor_counters_and_reflectors() -> None:
    def flag(character: str, move: str, name: str) -> list[int]:
        match = grid_match(character, "rook")
        start_move(match, match.fighters[0], move)
        frames = []
        for _ in range(40):
            view = observe(match).fighters[0]
            if getattr(view, name):
                frames.append(view.state_frame)
            match.tick(idle(match))
        return frames

    armor = load_character("bramble").moves["fsmash"].armor[0].frames
    assert flag("bramble", "fsmash", "armored") == list(range(armor.first, armor.last + 1))
    counter = load_character("rook").moves["dspecial"].counter
    assert counter is not None
    assert flag("rook", "dspecial", "countering") == list(
        range(counter.frames.first, counter.frames.last + 1)
    )
    assert flag("zephyr", "dspecial", "reflecting")
    assert not flag("rook", "jab1", "armored")


def test_the_view_describes_projectiles_and_traps() -> None:
    def fired(move: str) -> Any:
        match = grid_match("mote", "rook")
        start_move(match, match.fighters[0], move)
        for _ in range(60):
            match.tick(idle(match))
            world = observe(match)
            if world.projectiles:
                return world.projectiles[0]
        raise AssertionError(f"{move} fired nothing")

    orb = fired("nspecial")
    assert orb.owner == 0 and orb.move_id == "nspecial" and orb.damage > 0.0
    assert not orb.trap and orb.vel.length() > 0.0
    assert fired("dspecial").trap


def test_hazards_and_moving_platforms_are_seen_only_with_mechanics_on() -> None:
    stage = load_stage("ember_forge")
    characters = [load_character("rook"), load_character("rook")]
    off = Match.create(stage, characters, rules=MatchRules(stocks=None))
    assert observe(off).hazards == ()
    match = Match.create(stage, characters, rules=MatchRules(stocks=None, stage_hazards=True))
    before = observe(match).hazards
    assert len(before) == len(stage.hazards) == 2 and all(view.hits for view in before)
    assert {view.kind for view in before} == {"geyser"}
    countdown = before[0].frames_to_active
    assert before[0].phase == "rest" and countdown == stage.hazards[0].first_active()
    for _ in range(countdown - 1):
        match.tick(idle(match))
    view = observe(match).hazards[0]
    assert (view.phase, view.frames_to_active) == ("warn", 1)
    match.tick(idle(match))
    view = observe(match).hazards[0]
    assert (view.phase, view.frames_to_active) == ("active", 0)
    assert view.frames_left == stage.hazards[0].active
    assert stage.hazards[0].is_active(match.frame)

    wind = load_stage("dune_bazaar")
    blown = Match.create(wind, characters, rules=MatchRules(stocks=None, stage_hazards=True))
    gust = observe(blown).hazards[0]
    assert gust.kind == "wind" and not gust.hits and gust.push.length() > 0.0

    isles = load_stage("twin_isles")
    still = Match.create(isles, characters, rules=MatchRules(stocks=None))
    assert observe(still).platforms == ()
    moving = Match.create(isles, characters, rules=MatchRules(stocks=None, stage_hazards=True))
    steps = []
    for _ in range(120):
        moving.tick(idle(moving))
        steps.append(observe(moving).platforms[0].step.length())
    assert max(steps) > 0.0


# --- beliefs ------------------------------------------------------------------------------


def watch(
    match: Match,
    beliefs: Beliefs,
    ticks: int,
    inputs: dict[int, InputFrame],
    focus: int | None = None,
    history: list[WorldView] | None = None,
) -> list[WorldView]:
    """Tick the match, feeding each snapshot to ``beliefs``; return the history."""
    history = [] if history is None else history
    for _ in range(ticks):
        frames = idle(match)
        for player, frame in inputs.items():
            frames[player] = frame
        match.tick(frames)
        history.append(observe(match))
        beliefs.update(history, focus)
    return history


def test_levels_track_sooner_than_they_react() -> None:
    assert [cpu_level(level).tracking_frames for level in (1, 3, 5, 7, 9)] == [10, 8, 6, 4, 2]
    for level in range(1, 10):
        assert cpu_level(level).tracking_frames < cpu_level(level).reaction_frames


def test_a_new_move_is_noticed_a_reaction_time_late_and_then_caught_up_with() -> None:
    match = grid_match("rook", "rook")
    beliefs = Beliefs(0, tracking_frames=3, reaction_frames=12, rng=Rng.seeded(1), spread=0)
    history = watch(match, beliefs, 20, {})
    assert beliefs.of(1).state is StateId.IDLE and beliefs.noticed(1)
    start_move(match, match.fighters[1], "fsmash")
    started = match.frame + 1
    for tick in range(1, 30):
        watch(match, beliefs, 1, {}, history=history)
        believed, real = beliefs.of(1), history[-1].fighters[1]
        if match.frame < started + 12:
            assert believed.state is StateId.IDLE, f"tick {tick}: too soon"
            assert not beliefs.noticed(1)
        else:
            assert believed.state is StateId.ATTACK and believed.move_id == "fsmash"
            assert believed.state_frame == real.state_frame, "run on to where the move is now"
            assert believed.move_faf == real.move_faf and beliefs.noticed(1)
    assert beliefs.of(0) == history[-1].fighters[0], "its own fighter is known as it is"


def test_position_is_tracked_sooner_than_the_state() -> None:
    match = grid_match("rook", "rook")
    beliefs = Beliefs(0, tracking_frames=3, reaction_frames=12, rng=Rng.seeded(1), spread=0)
    history = watch(match, beliefs, 10, {})
    run = InputFrame(move=Vec2(0.0, 1.0))
    watch(match, beliefs, 8, {1: run}, history=history)
    believed = beliefs.of(1)
    assert believed.state is StateId.IDLE, "the dash has not been noticed yet"
    assert believed.pos == history[-4].fighters[1].pos != history[0].fighters[1].pos
    assert believed.vel == history[-4].fighters[1].vel
    watch(match, beliefs, 10, {1: run}, history=history)
    assert beliefs.of(1).state in (StateId.DASH, StateId.RUN)
    assert beliefs.of(1).pos == history[-4].fighters[1].pos


def test_a_reaction_is_never_quicker_than_the_levels_and_varies_a_little() -> None:
    delays = set()
    for seed in range(12):
        match = grid_match("rook", "rook")
        beliefs = Beliefs(0, 2, 10, Rng.seeded(seed))
        history = watch(match, beliefs, 5, {})
        start_move(match, match.fighters[1], "jab1")
        started = match.frame + 1
        for _ in range(30):
            watch(match, beliefs, 1, {}, history=history)
            if beliefs.of(1).state is StateId.ATTACK:
                delays.add(match.frame - started)
                break
    assert min(delays) >= 10 and max(delays) <= 10 + config.CPU_REACTION_SPREAD
    assert len(delays) > 1


def test_an_opponent_out_of_focus_and_far_away_is_read_later() -> None:
    def delay(focus: int | None, distance: float) -> int:
        match = grid_match("rook", "rook", "rook")
        place(match, match.fighters[2], 3.0 + distance, 6.0)
        beliefs = Beliefs(0, 2, 10, Rng.seeded(3), spread=0)
        history = watch(match, beliefs, 5, {}, focus)
        start_move(match, match.fighters[2], "fsmash")
        started = match.frame + 1
        for _ in range(40):
            watch(match, beliefs, 1, {}, focus, history)
            if beliefs.of(2).state is StateId.ATTACK:
                return match.frame - started
        raise AssertionError("never noticed")

    far, near = CLOSE_ATTENTION + 3.0, CLOSE_ATTENTION - 1.0
    assert delay(None, far) == 10
    assert delay(2, far) == 10
    assert delay(1, far) == 10 + config.CPU_ATTENTION_FRAMES
    assert delay(1, near) == 10, "close enough to demand attention anyway"


def test_hitstun_seen_once_runs_down_by_itself() -> None:
    match = grid_match("rook", "rook")
    one, two = match.fighters
    one.facing = Dir8.SE
    place(match, two, 3.0 + Dir8.SE.world.x * 0.9, 6.0 + Dir8.SE.world.y * 0.9)
    two.damage = 60.0
    beliefs = Beliefs(0, 2, 6, Rng.seeded(1), spread=0)
    history = watch(match, beliefs, 3, {})
    start_move(match, one, "fsmash")
    for _ in range(80):
        watch(match, beliefs, 1, {}, history=history)
        real, believed = history[-1].fighters[1], beliefs.of(1)
        if believed.state is StateId.TUMBLE and real.state is StateId.TUMBLE:
            assert abs(believed.hitstun - real.hitstun) <= 1
            assert believed.launch is None
            break
    else:
        raise AssertionError("the launch was never noticed")
    assert len(beliefs.views()) == 2
