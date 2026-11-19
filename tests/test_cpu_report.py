"""Tests for the CPU benchmark and report (plan note "15 - CPU AI", decision D-071).

Three things are held here: the M10 CPU frozen in ``ai/classic`` plays exactly as it did (it
is what the game's CPU is measured against), the scripted bots do their one thing, and the
report counts what it says it counts.
"""

import ast
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from helpers import place
from isofightr.ai import bots, report
from isofightr.ai.bots import BOTS, ONE_BUTTON, bot_def, make_bot
from isofightr.ai.classic import ClassicCpu
from isofightr.ai.classic.knowledge import knowledge_for
from isofightr.ai.report import (
    COST_METRICS,
    SUITES,
    TARGETS,
    MatchReport,
    MatchSpec,
    PlayerReport,
    Tally,
    check,
    make_brain,
    play,
    report_lines,
    suites,
    summarise,
    trace,
)
from isofightr.ai.view import observe
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.events import GrabEvent, HitEvent, ShieldHitEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect

ROOT = Path(__file__).parent.parent
PINNED = Path(__file__).parent / "fixtures" / "cpu_classic.json"
CLASSIC_DIR = ROOT / "src" / "isofightr" / "ai" / "classic"


# --- the frozen M10 CPU -------------------------------------------------------------------


def classic_hash(case: dict[str, Any], share_view: bool = False) -> str:
    """Play a match of frozen CPUs and return its state hash."""
    stage = load_stage(case["stage"])
    rules = MatchRules(stocks=3, stage_hazards=True)
    characters = [load_character(name) for name in case["characters"]]
    match = Match.create(stage, characters, seed=case["seed"], rules=rules)
    cpus = [
        ClassicCpu(index, level, case["seed"], stage) for index, level in enumerate(case["levels"])
    ]
    for _ in range(case["ticks"]):
        world = observe(match) if share_view else None
        match.tick([cpu.think(match, world) for cpu in cpus])
    return match.state_hash()


@pytest.mark.parametrize("index", range(4))
def test_the_frozen_cpu_plays_as_it_did(index: int, update_goldens: bool) -> None:
    """The benchmark must not drift. If the sim itself changes (never in M20), re-record with
    ``uv run pytest --update-goldens`` together with the goldens, and say so."""
    cases = json.loads(PINNED.read_text(encoding="utf-8"))
    case = cases[index]
    actual = classic_hash(case)
    if update_goldens:
        case["hash"] = actual
        PINNED.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8", newline="\n")
    assert actual == case["hash"]


def test_the_frozen_cpu_ignores_a_snapshot_that_is_not_its_own() -> None:
    case = json.loads(PINNED.read_text(encoding="utf-8"))[0]
    short = dict(case, ticks=600)
    assert classic_hash(short, share_view=True) == classic_hash(short)


def test_the_frozen_cpu_depends_on_nothing_that_will_change() -> None:
    """It may import the sim and itself: not the game's CPU, and not ``config``."""
    for path in sorted(CLASSIC_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
                if node.module == "isofightr":
                    names = [f"isofightr.{alias.name}" for alias in node.names]
            for name in names:
                if not name.startswith("isofightr"):
                    continue
                allowed = name.startswith(("isofightr.sim", "isofightr.ai.classic"))
                assert allowed, f"{path.name} imports {name}"


# --- the scripted bots --------------------------------------------------------------------


def bot_match(name: str, distance: float = 4.0) -> tuple[Match, bots.ScriptedBot]:
    """A bot (player 1) and an idle Rook ``distance`` units away, on Training Grid."""
    definition = bot_def(name)
    stage = load_stage("training_grid")
    characters = [load_character(definition.character), load_character("rook")]
    match = Match.create(stage, characters, seed=3, rules=MatchRules(stocks=None))
    place(match, match.fighters[0], 4.0, 6.0)
    place(match, match.fighters[1], 4.0 + distance, 6.0, facing=Dir8.NW)
    return match, make_bot(name, 0, 3, stage)


def run_bot(match: Match, bot: bots.ScriptedBot, ticks: int) -> list[object]:
    events: list[object] = []
    for _ in range(ticks):
        match.tick([bot.think(match), NEUTRAL_INPUT])
        events += match.events
    return events


def test_every_bot_is_real_data() -> None:
    assert len({bot.name for bot in BOTS}) == len(BOTS)
    assert set(ONE_BUTTON) <= {bot.name for bot in BOTS}
    for bot in BOTS:
        assert bot.character in list_character_ids()
        if bot.action:
            knowledge_for(load_character(bot.character)).action(bot.action)
    with pytest.raises(KeyError):
        bot_def("button_masher")


@pytest.mark.parametrize("name", ["dtilt", "jab", "fsmash", "dash_attack", "sh_fair"])
def test_a_one_move_bot_walks_up_and_lands_its_move(name: str) -> None:
    match, bot = bot_match(name)
    events = run_bot(match, bot, 600)
    moves = {event.move_id for event in events if isinstance(event, HitEvent)}
    wanted = {"jab": "jab1", "sh_fair": "fair"}.get(name, name)
    assert moves == {wanted}
    assert match.fighters[0].in_play and match.stats[0].falls == 0


def test_the_grab_bot_grabs_and_throws() -> None:
    match, bot = bot_match("grab")
    events = run_bot(match, bot, 400)
    assert any(isinstance(event, GrabEvent) and event.grabber == 0 for event in events)
    assert match.fighters[1].damage > 0.0


def test_the_shield_bot_shields_only_when_someone_is_close() -> None:
    match, bot = bot_match("shield", distance=6.0)
    run_bot(match, bot, 30)
    assert match.fighters[0].state is StateId.IDLE
    place(match, match.fighters[1], 5.5, 6.0, facing=Dir8.NW)
    run_bot(match, bot, 30)
    assert match.fighters[0].state is StateId.SHIELD


def test_a_zoning_bot_stays_where_it_is() -> None:
    match, bot = bot_match("orb", distance=7.0)
    start = match.fighters[0].pos
    events = run_bot(match, bot, 300)
    assert (match.fighters[0].pos - start).length() < 0.5
    assert any(isinstance(event, HitEvent) and event.attacker == 0 for event in events)


def test_a_bot_off_the_stage_gets_back() -> None:
    match, bot = bot_match("dtilt")
    fighter = match.fighters[0]
    place(match, fighter, -3.0, 6.0, z=-1.0, facing=Dir8.SE)
    for _ in range(300):
        run_bot(match, bot, 1)
        if fighter.grounded:
            break
    assert fighter.grounded and match.stats[0].falls == 0


def test_bots_only_read_the_match_and_are_deterministic() -> None:
    hashes = []
    for _ in range(2):
        match, bot = bot_match("fsmash")
        for _ in range(300):
            before = match.state_hash()
            frame = bot.think(match)
            assert match.state_hash() == before
            match.tick([frame, NEUTRAL_INPUT])
        hashes.append(match.state_hash())
    assert hashes[0] == hashes[1]


# --- the suites ---------------------------------------------------------------------------


def test_the_suites_are_fixed_and_playable() -> None:
    everything = suites()
    assert everything == suites()
    counts = {suite: sum(1 for spec in everything if spec.suite == suite) for suite in SUITES}
    assert counts == {
        "ladder": 120,
        "matrix": 96,
        "versus": 96,
        "bots": 192,
        "low": 72,
        "ffa": 22,
        "mix": 44,
        "teams": 11,
    }
    stage = load_stage("training_grid")
    for spec in everything:
        assert len(spec.characters) == len(spec.players)
        assert set(spec.characters) <= set(list_character_ids())
        load_stage(spec.stage)
        for index, player in enumerate(spec.players):
            make_brain(player, index, spec.seed, stage)
    with pytest.raises(ValueError, match="unknown player"):
        make_brain("human:1", 0, 1, stage)


def test_the_quick_sample_is_a_thin_slice_of_every_suite() -> None:
    quick = suites(quick=True)
    assert {spec.suite for spec in quick} == set(SUITES)
    assert set(quick) <= set(suites())
    assert 30 <= len(quick) <= 60
    assert {spec.suite for spec in suites(only=("bots", "low"))} == {"bots", "low"}


def test_versus_puts_the_subject_on_both_sides() -> None:
    versus = [spec for spec in suites() if spec.suite == "versus"]
    sides = {next(i for i in range(2) if spec.is_subject(i)) for spec in versus}
    assert sides == {0, 1}
    assert all(sorted(spec.players) == ["classic:9", "cpu:9"] for spec in versus)


# --- playing and counting -----------------------------------------------------------------

SHORT = MatchSpec(
    "matrix", "rook v zephyr", "sky_ruins", ("rook", "zephyr"), ("cpu:9", "cpu:9"), 12, minutes=1.0
)


@pytest.fixture(scope="module")
def short() -> MatchReport:
    return play(SHORT)


def test_a_match_report_adds_up(short: MatchReport) -> None:
    assert short.ticks == 3600 or short.ended
    one, two = short.players
    for player in short.players:
        assert player.subject and player.ticks > 0
        assert player.uses == sum(player.moves.values()) > 10
        assert player.uses_hit + player.uses_blocked + player.uses_stuffed <= player.uses
        assert player.follow_ups <= player.launches <= player.hits
        assert player.whiff_punishes <= player.whiff_chances
        assert player.block_punishes <= player.blocks
    assert one.damage_given == pytest.approx(two.damage_taken)
    assert one.hits == sum(two.taken.values())
    assert one.falls == two.kos + one.self_destructs


def test_playing_is_deterministic_and_the_subject_can_be_the_frozen_cpu(
    short: MatchReport,
) -> None:
    again = play(SHORT)
    assert again.state_hash == short.state_hash
    assert again.players == short.players
    # Until M20 group 2 changes the game's CPU, it and the frozen copy are the same player.
    assert play(SHORT, subject=report.CLASSIC).ticks > 0


def recorder_with(characters: tuple[str, ...] = ("rook", "rook")) -> tuple[Match, Any]:
    stage = load_stage("training_grid")
    match = Match.create(
        stage, [load_character(c) for c in characters], seed=1, rules=MatchRules(stocks=None)
    )
    place(match, match.fighters[0], 5.0, 6.0)
    place(match, match.fighters[1], 6.4, 6.0, facing=Dir8.NW)
    spec = MatchSpec("matrix", "test", "training_grid", characters, ("cpu:9", "cpu:9"), 1)
    return match, report._Recorder(match, spec)


def drive(match: Match, recorder: Any, inputs: list[tuple[InputFrame, InputFrame]]) -> None:
    for frames in inputs:
        recorder.before(match)
        match.tick(list(frames))
        recorder.after(match)


def test_a_move_that_connects_is_a_hit_and_one_into_a_shield_is_blocked() -> None:
    match, recorder = recorder_with()
    smash = InputFrame(move=Dir8.SE.world, held=int(Button.STRONG))
    drive(match, recorder, [(smash, NEUTRAL_INPUT)] + [(NEUTRAL_INPUT, NEUTRAL_INPUT)] * 70)
    done = recorder.report(match, 10**6).players
    assert (done[0].uses, done[0].uses_hit, done[0].moves) == (1, 1, {"fsmash": 1})
    assert done[0].launches == 1 and done[1].taken == {"free": 1}

    match, recorder = recorder_with()
    shield = InputFrame(held=int(Button.SHIELD))
    drive(
        match,
        recorder,
        [(NEUTRAL_INPUT, shield)] * 5 + [(smash, shield)] + [(NEUTRAL_INPUT, shield)] * 70,
    )
    done = recorder.report(match, 10**6).players
    assert (done[0].uses_hit, done[0].uses_blocked) == (0, 1)
    assert done[1].blocks == 1 and done[1].block_punishes == 0


def test_a_move_that_misses_next_to_someone_is_a_whiff_they_could_punish() -> None:
    match, recorder = recorder_with()
    place(match, match.fighters[1], 7.6, 6.0, facing=Dir8.NW)  # out of the smash's reach
    smash = InputFrame(move=Dir8.SE.world, held=int(Button.STRONG))
    drive(match, recorder, [(smash, NEUTRAL_INPUT)] + [(NEUTRAL_INPUT, NEUTRAL_INPUT)] * 80)
    done = recorder.report(match, 10**6).players
    assert done[0].uses == 1 and done[0].uses_hit == done[0].uses_stuffed == 0
    assert (done[1].whiff_chances, done[1].whiff_punishes) == (1, 0)


def test_a_move_beaten_before_it_comes_out_is_stuffed_not_whiffed() -> None:
    match, recorder = recorder_with()
    smash = InputFrame(move=Dir8.SE.world, held=int(Button.STRONG))
    jab = InputFrame(held=int(Button.ATTACK))
    drive(match, recorder, [(smash, jab)] + [(NEUTRAL_INPUT, NEUTRAL_INPUT)] * 60)
    done = recorder.report(match, 10**6).players
    assert done[0].uses_stuffed == 1 and done[0].taken == {"own_move": 1}
    assert done[1].uses_hit == 1 and done[1].whiff_chances == 0


def hit(attacker: int, target: int, move: str, knockback: float = 60.0) -> HitEvent:
    return HitEvent(attacker, target, move, 8.0, knockback, Vec3(0, 0, 0), Effect.NORMAL, 5)


def test_follow_ups_punishes_and_offstage_kos_are_counted_from_events() -> None:
    match, recorder = recorder_with()
    recorder.before(match)
    # Two hits of one throw-like use: one launch, no follow-up; then another use in time.
    recorder._hit(match, hit(0, 1, "pummel", knockback=0.0), 10)
    recorder._hit(match, hit(0, 1, "throw_f"), 20)
    recorder._hit(match, hit(0, 1, "throw_u"), 50)
    recorder._hit(match, hit(0, 1, "throw_d"), 200)  # too late to follow the second launch
    one, two = recorder.players
    assert (one.hits, one.launches, one.follow_ups) == (4, 3, 1)
    # Player 2 blocked something of player 1's, then hit back in time.
    recorder.current[0] = report._Use(99, {"fsmash"}, "fsmash", 300)
    recorder._shield_hit(ShieldHitEvent(0, 1, 5.0, Vec3(0, 0, 0), 4, False), 310)
    recorder._shield_hit(ShieldHitEvent(0, 1, 5.0, Vec3(0, 0, 0), 4, False), 312)
    recorder.current[0] = None
    recorder._hit(match, hit(1, 0, "throw_f"), 330)
    assert (two.blocks, two.block_punishes) == (1, 1)


def test_a_teammate_hit_is_counted() -> None:
    stage = load_stage("training_grid")
    rules = MatchRules(stocks=None, teams=(0, 0), friendly_fire=True)
    match = Match.create(stage, [load_character("rook")] * 2, seed=1, rules=rules)
    spec = MatchSpec("teams", "t", "training_grid", ("rook", "rook"), ("cpu:9", "cpu:9"), 1)
    recorder = report._Recorder(match, spec)
    recorder.before(match)
    recorder._hit(match, hit(0, 1, "throw_f"), 5)
    assert recorder.players[0].team_hits == 1


# --- metrics and targets ------------------------------------------------------------------


def player(spec: str, character: str = "rook", **values: Any) -> PlayerReport:
    made = PlayerReport(spec, character, spec.startswith("cpu:"))
    for name, value in values.items():
        setattr(made, name, value)
    return made


def match_report(
    suite: str,
    tag: str,
    players: list[PlayerReport],
    winners: tuple[int, ...],
    stage: str = "sky_ruins",
) -> MatchReport:
    spec = MatchSpec(
        suite, tag, stage, tuple(p.character for p in players), tuple(p.spec for p in players), 1
    )
    for index, made in enumerate(players):
        made.won = index in winners
    return MatchReport(spec, 3600, True, False, winners, players, "")


def synthetic() -> list[MatchReport]:
    """One hand-made match per suite, with numbers chosen so each metric is easy to check."""
    busy = {
        "ticks": 3600,
        "uses": 20,
        "uses_hit": 8,
        "uses_blocked": 2,
        "uses_stuffed": 4,
        "moves": {"fsmash": 10, "jab1": 4, "jab2": 1, "grab": 1, "nair": 4},
        "hits": 10,
        "launches": 5,
        "follow_ups": 1,
        "whiff_chances": 4,
        "whiff_punishes": 1,
        "blocks": 4,
        "block_punishes": 2,
        "taken": {"own_move": 3, "free": 1},
        "entries": {"roll": 2, "crouch": 1},
        "kos": 2,
        "falls": 2,
        "ko_moves": {"fsmash": 1, "bair": 1},
        "offstage_hits": 2,
        "offstage_kos": 1,
        "damage_taken": 300.0,
        "damage_given": 300.0,
    }
    four = [
        player("cpu:9", c, ticks=3600, hits=10, team_hits=2, falls=5) for c in report.CHARACTERS
    ]
    four[0].self_destructs = 1
    four[1].hazard_hits = 6
    four[2].near_invincible = 120
    return [
        match_report(
            "matrix",
            "rook v mote",
            [player("cpu:9", **busy), player("cpu:9", "mote", **busy)],
            (0,),
        ),
        match_report("versus", "rook v rook", [player("classic:9"), player("cpu:9")], (1,)),
        match_report("ladder", "7v9", [player("cpu:9"), player("cpu:7")], (0,)),
        match_report("ladder", "8v9", [player("cpu:9"), player("cpu:8")], (1,)),
        match_report(
            "bots",
            "dtilt",
            [
                player("cpu:9", ticks=3600, damage_given=50.0),
                player("bot:dtilt", uses=10, uses_hit=6, damage_given=100.0),
            ],
            (1,),
        ),
        match_report("low", "1 v jab", [player("cpu:1"), player("bot:jab")], (1,)),
        match_report("low", "5 v jab", [player("cpu:5"), player("bot:jab")], (0,)),
        match_report("ffa", "storm_galleon", four, (1,), stage="storm_galleon"),
        match_report(
            "teams",
            "sky_ruins",
            [player("cpu:9", c, hits=10, team_hits=1) for c in report.CHARACTERS],
            (0, 1),
        ),
    ]


def test_metrics_are_what_their_names_say() -> None:
    metrics = summarise(synthetic())
    expected = {
        "whiff_rate": 6 / 20,
        "stuffed_rate": 4 / 20,
        "top_move_share": 0.5,
        "light_share": 6 / 20,
        "jab_chain_rate": 0.25,
        "rolls_per_min": 2.0,
        "spot_dodges_per_min": 0.0,
        "crouches_per_min": 1.0,
        "follow_up_rate": 0.2,
        "whiff_punish_rate": 0.25,
        "block_punish_rate": 0.5,
        "own_move_hit_share": 0.75,
        "damage_per_stock": 150.0,
        "other_ko_share": 0.5,
        "offstage_hit_share": 0.2,
        "offstage_ko_share": 0.5,
        "timeout_share": 0.0,
        "character_win_low": 0.0,
        "character_win_high": 1.0,
        "versus_win_rate": 1.0,
        "ladder_two_apart": 1.0,
        "ladder_one_apart": 0.0,
        "bot_land_rate": 0.6,
        "bot_damage_ratio": 2.0,
        "bot_matches_lost": 1.0,
        "level1_bot_win_rate": 1.0,
        "level5_bot_win_rate": 0.0,
        "self_destruct_share": 1 / 20,
        "self_destruct_worst_stage": 1 / 20,
        "near_invincible_seconds": 0.5,
        "lightning_per_min": 6.0,
        "team_hit_share": 0.1,
        "unfinished": 0.0,
    }
    assert metrics == pytest.approx(expected)


def test_a_metric_is_left_out_when_its_suite_was_not_played() -> None:
    metrics = summarise([r for r in synthetic() if r.spec.suite == "versus"])
    assert set(metrics) == {"unfinished", "versus_win_rate"}


def test_every_target_names_a_metric_and_states_a_baseline() -> None:
    names = set(summarise(synthetic())) | set(COST_METRICS)
    assert len({target.metric for target in TARGETS}) == len(TARGETS) >= 20
    for target in TARGETS:
        assert target.metric in names, target.metric
        assert target.what
        # No target is already met by the CPU it was written to improve on, except the ones
        # that only have to stay as good as they are.
        assert target.met(target.baseline) == (target.metric in report.HOLD), target.metric
    results = check({"whiff_rate": 0.0, "versus_win_rate": 0.0})
    assert [(target.metric, met) for target, _, met in results] == [
        ("versus_win_rate", False),
        ("whiff_rate", True),
    ]


def test_the_printed_report_covers_every_suite_and_the_targets() -> None:
    reports = synthetic()
    text = "\n".join(report_lines(reports, summarise(reports)))
    for heading in (
        "LADDER",
        "MATRIX",
        "VERSUS",
        "BOTS",
        "LOW LEVELS",
        "FREE-FOR-ALL",
        "TEAMS",
        "TARGETS",
    ):
        assert heading in text
    assert "dtilt" in text and "MISS" in text and "targets met" in text


def test_tally_adds_players_up() -> None:
    total = Tally()
    total.add(player("cpu:9", ticks=1800, uses=3, moves={"jab1": 3}, longest_combo=4, won=True))
    total.add(player("cpu:9", ticks=1800, uses=2, moves={"jab1": 1, "nair": 1}, longest_combo=2))
    assert (total.matches, total.wins, total.minutes) == (2, 1, 1.0)
    assert total.total.uses == 5 and total.total.moves == {"jab1": 4, "nair": 1}
    assert total.total.longest_combo == 4


def test_trace_lists_a_players_decisions() -> None:
    lines = trace(SHORT, 0, 600)
    assert len(lines) > 5
    assert any("attack" in line or "move" in line for line in lines)
    assert any("hits with" in line or "is hit by" in line for line in lines)


def test_the_tool_plays_a_sample_and_reports_its_exit_status() -> None:
    path = ROOT / "tools" / "cpu_report.py"
    loaded = importlib.util.spec_from_file_location("cpu_report_tool", path)
    assert loaded is not None and loaded.loader is not None
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    arguments = ["--quick", "--suite", "versus", "--limit", "1", "--jobs", "1", "--no-cost"]
    assert module.main(arguments) in (0, 1)
    spec = module.trace_spec(
        module.argparse.Namespace(players="rook=cpu:9, mote=bot:orb", stage="lily_pads", seed=2)
    )
    assert spec.characters == ("rook", "mote") and spec.players == ("cpu:9", "bot:orb")


# --- the matchup table ------------------------------------------------------------------------


def test_the_matchup_table_counts_both_sides_and_leaves_mirrors_out() -> None:
    def duel(first: str, second: str, winner: int | None) -> report.MatchReport:
        players = [player("cpu:9", first), player("cpu:9", second)]
        winners = () if winner is None else (winner,)
        return match_report("matrix", f"{first} v {second}", players, winners)

    reports = [
        duel("rook", "mote", 0),  # Rook beats Mote...
        duel("mote", "rook", 1),  # ...from the other side too
        duel("mote", "rook", 0),
        duel("rook", "mote", None),  # nobody won: played, no win
        duel("rook", "rook", 0),  # a mirror
        match_report("versus", "rook", [player("cpu:9"), player("classic:9")], (0,)),
    ]
    table = report.matchups(reports)
    assert table[("rook", "mote")] == (2, 4) and table[("mote", "rook")] == (1, 4)
    assert ("rook", "rook") not in table, "mirrors are always one win each"
    lines = report.matchup_lines(reports, ("rook", "mote"))
    assert lines[2].split() == ["rook", "-", "2/4"]
    assert lines[3].split() == ["mote", "1/4", "-"]
    text = "\n".join(report_lines(reports, summarise(reports)))
    assert "matchups: the row's wins against the column" in text
