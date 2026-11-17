"""Tests for the CPU's habits and styles (plan note "15 - CPU AI", decision D-071, M20 group
5): what it learns of each opponent, how fast it follows a change, which levels adapt, its
own variety, and each character's style from its data and ``[cpu]`` table.
"""

from dataclasses import replace

from helpers import place
from isofightr import config
from isofightr.ai import habits, intercept
from isofightr.ai.bots import make_bot
from isofightr.ai.controller import CpuController
from isofightr.ai.knowledge import knowledge_for
from isofightr.ai.levels import cpu_level
from isofightr.ai.style import Style, default_style, style_for
from isofightr.ai.view import observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.character_def import CpuStyleDef
from isofightr.sim.events import GrabEvent, HitEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2

ROOK = load_character("rook")
MOTE = load_character("mote")
GRID = load_stage("training_grid")


def learner(adapt: float = 1.0) -> habits.Habits:
    return habits.Habits(0, adapt, Vec2(6.0, 6.0))


# --- learning ---------------------------------------------------------------------------------


def test_a_habit_is_expected_once_seen_and_a_change_is_followed_within_a_few_repeats() -> None:
    seen = learner()
    assert seen.expected(1, habits.LEDGE) is None
    for _ in range(3):
        seen.record(1, habits.LEDGE, "roll")
    assert seen.expected(1, habits.LEDGE) is not None
    assert seen.expected(1, habits.LEDGE)[0] == "roll"
    for _ in range(3):
        seen.record(1, habits.LEDGE, "getup")
    expected = seen.expected(1, habits.LEDGE)
    assert expected is not None and expected[0] == "getup", "three repeats outweigh the old"
    assert seen.expected(2, habits.LEDGE) is None, "habits are per opponent"


def test_levels_below_5_do_not_adapt_and_5_trusts_less_than_9() -> None:
    assert cpu_level(4).adapt == 0.0 and cpu_level(1).adapt == 0.0
    assert 0.0 < cpu_level(5).adapt < cpu_level(9).adapt
    blind = learner(cpu_level(3).adapt)
    for _ in range(5):
        blind.record(1, habits.GETUP, "roll in")
    assert blind.expected(1, habits.GETUP) is None
    middle, top = learner(cpu_level(5).adapt), learner(cpu_level(9).adapt)
    for seen in (middle, top):
        seen.record(1, habits.GETUP, "roll in")
        seen.record(1, habits.GETUP, "roll in")
    assert middle.expected(1, habits.GETUP) is None or (
        middle.expected(1, habits.GETUP)[1] < top.expected(1, habits.GETUP)[1]
    )


def test_ledge_exits_are_read_from_the_states_the_cpu_sees() -> None:
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    me, them = observe(match).fighters
    seen = learner()
    hanging = replace(them, state=StateId.LEDGE_HANG)
    for _option, state in (("roll", StateId.LEDGE_ROLL), ("getup", StateId.LEDGE_GETUP)):
        seen.observe((me, hanging), 10)
        seen.observe((me, replace(them, state=state)), 11)
    assert set(seen.options(1, habits.LEDGE)) == {"roll", "getup"}


def test_the_guard_habit_moves_toward_what_was_seen() -> None:
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], 6.0, 6.0)
    place(match, match.fighters[1], 6.8, 6.0)
    me, them = observe(match).fighters
    seen = learner()
    prior = config.CPU_GUARD_GUESS
    frame = 0
    for _ in range(4):
        seen.observe((me, them), frame)
        attacking = replace(me, state=StateId.ATTACK, move_id="ftilt")
        seen.observe((attacking, replace(them, state=StateId.SHIELD)), frame + 1)
        for tick in range(config.CPU_HABIT_GUARD_FRAMES + 2):
            seen.observe((me, replace(them, state=StateId.SHIELD)), frame + 2 + tick)
        frame += 40
    assert seen.guard(1, prior) > prior + 0.3


def test_its_own_moves_are_counted_so_it_can_avoid_a_pattern() -> None:
    own = habits.OwnMoves()
    for _ in range(4):
        own.used("fsmash")
    own.used("jab1")
    assert own.share("fsmash") > own.share("jab1") > own.share("dtilt") == 0.0


# --- in play ------------------------------------------------------------------------------------


def test_an_opponent_that_always_rolls_in_from_the_ledge_is_hit_by_the_third_time() -> None:
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    cpu = CpuController(0, 9, 1, GRID)
    me, other = match.fighters
    punished = []
    for _trial in range(3):
        place(match, me, 4.0, 6.0, facing=Dir8.NW)
        place(match, other, -0.35, 6.0, z=-1.8, damage=30.0)
        hung, hit = 0, False
        for _ in range(200):
            theirs = NEUTRAL_INPUT
            if other.state is StateId.LEDGE_HANG:
                hung += 1
                if hung == 40:
                    theirs = InputFrame(held=int(Button.SHIELD))
            match.tick([cpu.think(match), theirs])
            if any(isinstance(e, HitEvent) and e.attacker == 0 for e in match.events):
                hit = True
                break
        punished.append(hit)
    assert cpu.habits.options(1, habits.LEDGE).get("roll", 0.0) == 1.0
    assert any(punished), punished


def test_the_cpu_waits_beyond_the_end_of_an_expected_ledge_roll() -> None:
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    place(match, match.fighters[1], -0.35, 6.0, z=-1.8)
    cpu = CpuController(0, 9, 1, GRID)
    cpu.think(match)
    for _ in range(3):
        cpu.habits.record(1, habits.LEDGE, "roll")
    view = replace(observe(match).fighters[1], state=StateId.LEDGE_HANG)
    spot = cpu._habit_spot(view)
    assert spot is not None and spot[1] == "roll"
    assert spot[0].x > 1.5, "inside the stage, past where the roll ends"


def test_a_shield_holder_is_grabbed_and_a_projectile_repeater_is_noticed() -> None:
    for bot, character, check in (("shield", ROOK, "grabs"), ("orb", MOTE, "rush")):
        match = Match.create(GRID, [ROOK, character], seed=1, rules=MatchRules(stocks=None))
        cpu = CpuController(0, 9, 1, GRID)
        brain = make_bot(bot, 1, 1, GRID)
        grabs = 0
        noticed = False
        for _ in range(40 * 60):
            world = observe(match)
            match.tick([cpu.think(match, world), brain.think(match, world)])
            grabs += sum(1 for e in match.events if isinstance(e, GrabEvent) and e.grabber == 0)
            noticed = noticed or cpu._zoner(1)
        if check == "grabs":
            assert grabs >= 3
        else:
            assert noticed, "the orb bot's habit was noticed"


# --- style ------------------------------------------------------------------------------------


def test_a_character_without_a_cpu_table_gets_a_style_from_its_data() -> None:
    bare = replace(MOTE, cpu=CpuStyleDef())
    style = default_style(bare, knowledge_for(bare))
    assert style.far and style.zoning > 1.0, "a long projectile makes a zoner"
    rook = default_style(replace(ROOK, cpu=CpuStyleDef()), knowledge_for(ROOK))
    assert not rook.far
    low, high = config.CPU_STYLE_DEFAULT_BOUNDS
    assert all(low <= value <= high for value in (rook.aggression, rook.risk))


def test_the_four_styles_differ_as_their_tables_say() -> None:
    styles = {
        c: style_for(load_character(c), knowledge_for(load_character(c)), 0)
        for c in ("rook", "bramble", "zephyr", "mote")
    }
    assert styles["mote"].zoning > 1.25 > styles["rook"].zoning
    assert styles["zephyr"].aggression > styles["rook"].aggression > styles["bramble"].aggression
    assert styles["bramble"].stays_on_stage and not styles["zephyr"].stays_on_stage
    assert styles["zephyr"].air_bias > 1.2 > styles["bramble"].air_bias + 0.3
    assert {"nspecial", "sspecial", "dspecial"} <= styles["mote"].favourites


def test_temperament_makes_two_cpus_of_one_character_differ_a_little() -> None:
    first = style_for(ROOK, knowledge_for(ROOK), 1)
    second = style_for(ROOK, knowledge_for(ROOK), 2)
    assert first != second
    for name in ("aggression", "patience", "risk"):
        assert abs(getattr(first, name) / getattr(second, name) - 1.0) <= 0.25


def test_mote_values_its_projectiles_more_and_its_neutral_air_less_than_a_plain_style() -> None:
    cpu = CpuController(0, 9, 1, GRID)
    match = Match.create(GRID, [MOTE, ROOK], seed=1, rules=MatchRules(stocks=None))
    cpu.think(match)
    known = knowledge_for(MOTE)
    orb = next(a for a in known.actions if a.move_id == "nspecial" and a.projectile)
    nair = next(a for a in known.actions if a.move_id == "nair")

    def flavour(action, style: Style) -> float:
        cpu.style = style
        cpu.own = habits.OwnMoves()
        return cpu._flavour(intercept.Candidate(action, Vec2(1.0, 0.0), 10, 1.0, 0.0))

    mote = style_for(MOTE, known, 1)
    assert flavour(orb, mote) > flavour(orb, Style()) + 4.0
    assert flavour(nair, mote) < flavour(nair, Style())


def test_a_move_it_keeps_using_loses_value() -> None:
    cpu = CpuController(0, 9, 1, GRID)
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    cpu.think(match)
    cpu.style = Style()
    fsmash = knowledge_for(ROOK).action("fsmash")
    candidate = intercept.Candidate(fsmash, Vec2(1.0, 0.0), 10, 1.0, 0.0)
    fresh = cpu._flavour(candidate)
    for _ in range(3):
        cpu.own.used("fsmash")
    assert cpu._flavour(candidate) < fresh - config.CPU_REPEAT_PENALTY * 0.5
