"""Tests for levels by skill (plan note "15 - CPU AI", "Levels", decision D-071, M20 group 7):
what each level knows, the misjudged distance that replaced the dice, a respawned CPU waiting
out its invincibility, and the F2 line.
"""

from dataclasses import replace

from helpers import place
from isofightr import config
from isofightr.ai import intercept
from isofightr.ai.controller import CpuController
from isofightr.ai.levels import cpu_level
from isofightr.ai.view import observe
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3

ROOK = load_character("rook")
GRID = load_stage("training_grid")


def duel(gap: float) -> Match:
    match = Match.create(GRID, [ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], 4.0, 6.0, facing=Dir8.SE)
    place(match, match.fighters[1], 4.0 + gap, 6.0, facing=Dir8.NW)
    return match


def searched(level: int) -> set[str]:
    match = duel(4.0)
    cpu = CpuController(0, level, 1, GRID)
    cpu.think(match)
    names: set[str] = set()
    original = intercept.search

    def watching(reading, actions, allowed):  # type: ignore[no-untyped-def]
        listed = list(actions)
        names.update(action.name for action in listed)
        return original(reading, listed, allowed)

    intercept.search = watching  # type: ignore[assignment]
    try:
        world = observe(match)
        me, target = world.fighters
        me = replace(me, vel=Vec3(0.0, 0.0, 0.0))
        cpu._choose(cpu._read(world, me, target, None))
    finally:
        intercept.search = original  # type: ignore[assignment]
    return names


def test_skills_come_with_the_levels_of_the_table() -> None:
    low, mid, top = cpu_level(1), cpu_level(5), cpu_level(9)
    assert not low.can(config.CPU_SKILL_RUN) and mid.can(config.CPU_SKILL_RUN)
    assert not low.can(config.CPU_SKILL_COMBOS) and mid.can(config.CPU_SKILL_COMBOS)
    assert mid.can(config.CPU_SKILL_DODGE) and not cpu_level(4).can(config.CPU_SKILL_DODGE)
    assert not mid.can(config.CPU_SKILL_BEST_OUT_OF_SHIELD) and top.can(
        config.CPU_SKILL_BEST_OUT_OF_SHIELD
    )
    assert top.can(config.CPU_SKILL_GUARD_AVOID) and not cpu_level(8).can(
        config.CPU_SKILL_GUARD_AVOID
    )


def test_level_1_walks_up_to_its_moves_and_level_9_also_runs_and_charges() -> None:
    low, top = searched(1), searched(9)
    assert any(name.startswith("walk") for name in low)
    assert not any(name.startswith("run") for name in low)
    assert any(name.startswith("run") for name in top)
    assert len(top) > len(low), "jab chains and charged smashes from level 5"


def test_a_weak_cpu_misjudges_where_its_target_is_and_level_9_does_not() -> None:
    assert cpu_level(9).misjudge == 0.0 < cpu_level(5).misjudge < cpu_level(1).misjudge
    match = duel(3.0)
    world = observe(match)
    me, target = world.fighters
    for level, moved in ((9, False), (1, True)):
        cpu = CpuController(0, level, 1, GRID)
        cpu.think(match)
        reading = cpu._read(world, me, target, None)
        offset = (reading.track.points[0].xy - target.pos.xy).length()
        assert (offset > 0.01) is moved, level


def test_without_the_combo_skill_frames_ahead_are_worth_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    match = duel(0.6)
    world = observe(match)
    me, target = world.fighters
    cpu = CpuController(0, 9, 1, GRID)
    cpu.think(match)
    reading = cpu._read(world, me, target, None)
    jab = cpu.knowledge[0].action("jab")
    monkeypatch.setattr(intercept.forecast, "advantage_on_hit", lambda *_: 10)
    aim = Dir8.SE.world
    full = intercept.weigh(reading, jab, aim, jab.first_hit, 1.0)
    one_hit = intercept.weigh(replace(reading, combos=False), jab, aim, jab.first_hit, 1.0)
    assert full.value > one_hit.value


def test_a_respawned_cpu_waits_out_its_invincibility_at_a_distance() -> None:
    match = duel(1.0)
    me = match.fighters[0]
    me.invincible_frames = 90
    cpu = CpuController(0, 9, 1, GRID)
    start = (match.fighters[1].pos - me.pos).length()
    plans = set()
    for _ in range(40):
        match.tick([cpu.think(match), NEUTRAL_INPUT])
        plans.add(cpu.plan.detail)
    assert "wait out invincibility" in plans
    assert (match.fighters[1].pos - me.pos).length() > start + 1.0


def test_the_f2_line_says_what_the_cpu_is_doing() -> None:
    match = duel(3.0)
    cpu = CpuController(0, 7, 1, GRID)
    for _ in range(20):
        match.tick([cpu.think(match), NEUTRAL_INPUT])
    line = cpu.describe()
    assert line.strip().startswith("cpu L7 ") and cpu.plan.kind in line
