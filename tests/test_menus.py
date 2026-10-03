"""Tests for the windowless half of the M6 UI: menu model and input, match setup, dummy
behaviours, HUD layout, UI art, the results table and the Final Plateau stage.

Plan note "13 - Game Modes UI and Flow".
"""

import pytest

from helpers import hold, neutral, place
from isofightr.__main__ import build_parser, skips_menus
from isofightr.ai.dummy import DummyBehavior, dummy_frame
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render import placeholder_art as art
from isofightr.scenes.setup import (
    RANDOM_STAGE,
    MatchSetup,
    Mode,
    clock_text,
    countdown_text,
    result_awards,
    results_table,
    training_setup,
)
from isofightr.sim.constants import COUNTDOWN_FRAMES
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame, world_to_stick
from isofightr.sim.match import Match, MatchRules
from isofightr.ui.hud_layout import (
    BUBBLE_MARGIN,
    MAX_STOCK_ICONS,
    bubble_position,
    stock_count_text,
    stock_icons_shown,
)
from isofightr.ui.menu import (
    REPEAT_DELAY,
    REPEAT_EVERY,
    Menu,
    MenuAction,
    MenuInput,
    MenuItem,
    held_actions,
)

ROOK = load_character("rook")


def frame(direction: Dir8 | None = None, buttons: int = 0) -> InputFrame:
    return hold(direction, buttons, frames=1)[0]


# --- menu input ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "action"),
    [
        (Dir8.N, MenuAction.UP),
        (Dir8.S, MenuAction.DOWN),
        (Dir8.W, MenuAction.LEFT),
        (Dir8.E, MenuAction.RIGHT),
    ],
)
def test_the_stick_gives_screen_directions(direction: Dir8, action: MenuAction) -> None:
    assert held_actions(frame(direction)) == {action}


def test_buttons_confirm_and_go_back() -> None:
    assert held_actions(frame(buttons=Button.ATTACK)) == {MenuAction.CONFIRM}
    assert held_actions(frame(buttons=Button.JUMP)) == {MenuAction.CONFIRM}
    assert held_actions(frame(buttons=Button.SPECIAL)) == {MenuAction.BACK}
    assert held_actions(frame(buttons=Button.SHIELD)) == {MenuAction.BACK}
    assert held_actions(frame(buttons=Button.GRAB)) == {MenuAction.EXTRA}
    assert held_actions(NEUTRAL_INPUT) == set()
    assert held_actions(frame(Dir8.SE)) == {MenuAction.RIGHT, MenuAction.DOWN}


def test_a_press_fires_once_and_directions_repeat() -> None:
    menu_input = MenuInput()
    assert menu_input.update([NEUTRAL_INPUT]) == [frozenset()]
    confirm = frame(buttons=Button.ATTACK)
    fired = [menu_input.update([confirm])[0] for _ in range(60)]
    assert fired[0] == {MenuAction.CONFIRM} and not any(fired[1:]), "buttons do not repeat"

    menu_input.update([NEUTRAL_INPUT])
    down = frame(Dir8.S)
    ticks = [bool(menu_input.update([down])[0]) for _ in range(REPEAT_DELAY + 2 * REPEAT_EVERY + 1)]
    firing = [index for index, fired_now in enumerate(ticks) if fired_now]
    assert firing == [0, REPEAT_DELAY, REPEAT_DELAY + REPEAT_EVERY, REPEAT_DELAY + 2 * REPEAT_EVERY]


def test_what_is_held_when_a_menu_opens_is_ignored_until_released() -> None:
    menu_input = MenuInput()
    confirm = frame(buttons=Button.ATTACK)
    for _ in range(40):
        assert menu_input.update([confirm]) == [frozenset()]
    menu_input.update([NEUTRAL_INPUT])
    assert menu_input.update([confirm]) == [{MenuAction.CONFIRM}]
    menu_input.reset()
    assert menu_input.update([confirm]) == [frozenset()]


def test_each_player_has_its_own_actions() -> None:
    menu_input = MenuInput()
    menu_input.update([NEUTRAL_INPUT, NEUTRAL_INPUT])
    fired = menu_input.update([frame(Dir8.N), frame(buttons=Button.SPECIAL)])
    assert fired == [{MenuAction.UP}, {MenuAction.BACK}]


# --- menu model ---------------------------------------------------------------------------


def sample_menu() -> Menu:
    return Menu(
        [
            MenuItem("start", "Start"),
            MenuItem("mode", "Mode", ("Stock", "Time")),
            MenuItem("quit", "Quit"),
        ]
    )


def test_menu_navigation_wraps_and_confirm_returns_the_key() -> None:
    menu = sample_menu()
    assert menu.apply(MenuAction.CONFIRM) == "start"
    assert menu.apply(MenuAction.UP) is None and menu.selected.key == "quit"
    assert menu.apply(MenuAction.DOWN) is None and menu.selected.key == "start"
    menu.apply(MenuAction.DOWN)
    assert menu.selected.is_setting and menu.selected.value == "Stock"
    assert menu.apply(MenuAction.RIGHT) is None and menu.selected.value == "Time"
    assert menu.apply(MenuAction.RIGHT) is None and menu.selected.value == "Stock"
    assert menu.apply(MenuAction.LEFT) is None and menu.selected.value == "Time"
    assert menu.apply(MenuAction.CONFIRM) is None and menu.selected.value == "Stock"
    assert menu.lines() == ["  Start", "> Mode: < Stock >", "  Quit"]
    assert menu.item("quit").text == "Quit"
    menu.cursor = 0
    assert not menu.change(1), "an action item has nothing to change"


# --- match setup --------------------------------------------------------------------------


def test_setup_rules_for_each_mode() -> None:
    stock = MatchSetup(stocks=4)
    assert stock.rules() == MatchRules(stocks=4, countdown_frames=COUNTDOWN_FRAMES)
    timed = MatchSetup(mode=Mode.TIME, minutes=2)
    assert timed.rules() == MatchRules(
        stocks=None, time_frames=2 * 3600, countdown_frames=COUNTDOWN_FRAMES
    )
    training = training_setup()
    assert training.rules() == MatchRules(stocks=None) and training.stage == "training_grid"


def test_setup_counts_follow_the_mode_and_stay_in_range() -> None:
    setup = MatchSetup()
    assert (setup.stocks, setup.minutes, setup.count_label) == (3, 3, "3 stocks")
    assert setup.with_count(1).stocks == 4 and setup.with_count(1).minutes == 3
    assert setup.with_count(-5).stocks == 1 and setup.with_count(500).stocks == 99
    assert setup.with_count(-2).count_label == "1 stock"
    timed = MatchSetup(mode=Mode.TIME)
    assert timed.with_count(2).minutes == 5 and timed.with_count(2).stocks == 3
    assert timed.count_label == "3 minutes" and timed.with_count(-2).count_label == "1 minute"


def test_clock_and_countdown_text() -> None:
    assert [clock_text(f) for f in (10800, 10799, 3601, 3600, 61, 60, 1, 0, -5)] == [
        "3:00",
        "3:00",
        "1:01",
        "1:00",
        "0:02",
        "0:01",
        "0:01",
        "0:00",
        "0:00",
    ]
    assert [countdown_text(f) for f in (180, 121, 120, 61, 60, 1)] == ["3", "3", "2", "2", "1", "1"]


# --- dummy behaviours ---------------------------------------------------------------------


def test_dummy_behaviours() -> None:
    manual = frame(Dir8.N, Button.GRAB)
    assert dummy_frame(DummyBehavior.MANUAL, 7, manual) is manual
    assert dummy_frame(DummyBehavior.STAND, 7, manual) == NEUTRAL_INPUT
    assert dummy_frame(DummyBehavior.SHIELD, 7, manual).held == Button.SHIELD
    jumps = [
        bool(dummy_frame(DummyBehavior.JUMP, f, manual).held & Button.JUMP) for f in range(140)
    ]
    assert jumps[0] and not jumps[20] and jumps[70] and sum(jumps) == 16
    attacks = [dummy_frame(DummyBehavior.ATTACK, f, manual).held for f in range(90)]
    assert attacks.count(Button.ATTACK) == 4 and attacks[10] == 0
    first, second = (dummy_frame(DummyBehavior.WALK, f, manual) for f in (0, 60))
    assert world_to_stick(first.move)[0] > 0 > world_to_stick(second.move)[0]
    assert first.held == Button.WALK and first.move.length() < 0.8


# --- HUD layout ---------------------------------------------------------------------------


def test_stock_icons_and_the_count_for_many_stocks() -> None:
    assert [stock_icons_shown(n) for n in (None, 0, 1, 3, 5, 6, 99)] == [0, 0, 1, 3, 5, 1, 1]
    assert [stock_count_text(n) for n in (None, 3, 5, 6, 99)] == ["", "", "", "x6", "x99"]
    assert MAX_STOCK_ICONS == 5


def test_off_screen_markers_sit_on_the_nearest_edge() -> None:
    assert bubble_position(100, 100, NATIVE_W, NATIVE_H) is None
    assert bubble_position(0, 0, NATIVE_W, NATIVE_H) is None, "the edge itself is in view"
    assert bubble_position(-50, 100, NATIVE_W, NATIVE_H) == (BUBBLE_MARGIN, 100)
    assert bubble_position(900, 100, NATIVE_W, NATIVE_H) == (NATIVE_W - BUBBLE_MARGIN, 100)
    assert bubble_position(300, 500, NATIVE_W, NATIVE_H) == (300, NATIVE_H - BUBBLE_MARGIN)
    assert bubble_position(-9, -9, NATIVE_W, NATIVE_H) == (BUBBLE_MARGIN, BUBBLE_MARGIN)


# --- UI art -------------------------------------------------------------------------------


def test_panel_stock_icon_and_bubble_art() -> None:
    panel = art.build_panel(40, 20)
    assert panel.size == (40, 20)
    assert panel.getpixel((1, 0)) == art.PANEL_BORDER and panel.getpixel((5, 5)) == art.PANEL_FILL
    assert panel.getpixel((0, 0))[3] == 0, "clipped corners"
    icon = art.build_stock_icon(1)
    assert icon.size == (art.STOCK_ICON_SIZE,) * 2
    assert icon.getpixel((3, 3)) == art.player_color(1)
    bubble = art.build_bubble(2)
    assert bubble.size == (art.BUBBLE_SIZE,) * 2
    assert bubble.getpixel((7, 7)) == art.player_color(2) and bubble.getpixel((7, 1)) == art.WHITE


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_stage_gets_a_thumbnail(stage_id: str) -> None:
    stage = load_stage(stage_id)
    image = art.build_stage_thumbnail(stage)
    assert image.width <= 150 and image.height <= 110, "fits a stage-select slot"
    opaque = sum(1 for pixel in image.getdata() if pixel[3])
    cells = sum(cell is not None for row in stage.cells for cell in row)
    assert opaque >= cells * 8, "every cell is drawn"
    assert image.tobytes() == art.build_stage_thumbnail(stage).tobytes()


def test_platforms_show_in_the_thumbnail() -> None:
    image = art.build_stage_thumbnail(load_stage("sky_ruins"))
    colors = {pixel for pixel in image.getdata() if pixel[3]}
    assert art.DECK_PALETTE.top_light in colors


# --- Final Plateau ------------------------------------------------------------------------


def test_final_plateau_is_a_flat_14_by_10_island_without_platforms() -> None:
    stage = load_stage("final_plateau")
    assert (stage.size_x, stage.size_y, stage.display_name) == (14, 10, "Final Plateau")
    assert stage.soft_platforms == () and len(stage.ledges) == 4
    assert all(cell is not None and cell.top == 0 for row in stage.cells for cell in row)
    assert "final_plateau" in list_stage_ids() and RANDOM_STAGE not in list_stage_ids()
    spawns = [stage.spawn_point(index) for index in range(4)]
    assert len({(s.x, s.y) for s in spawns}) == 4 and all(s.z == 0 for s in spawns)


# --- results table ------------------------------------------------------------------------


def test_results_table_lists_players_in_placement_order() -> None:
    match = Match.create(load_stage("training_grid"), [ROOK] * 3, rules=MatchRules(stocks=1))
    for player in (0, 2):
        place(match, match.fighters[player], 5.5, 5.5, z=-9.0)
        match.tick(neutral(3))
    assert match.result is not None and match.result.winner == 1
    match.stats[1].damage_given = 123.4
    lines = results_table(match)
    assert lines[0].split() == [
        "PLACE",
        "PLAYER",
        "KOS",
        "FALLS",
        "SDS",
        "DEALT",
        "TAKEN",
        "PEAK",
        "COMBO",
    ]
    assert [line.split()[:3] for line in lines[1:]] == [
        ["1st", "P2", "Rook"],
        ["2nd", "P3", "Rook"],
        ["3rd", "P1", "Rook"],
    ]
    assert "123%" in lines[1]
    assert lines[3].split()[3:6] == ["0", "1", "1"], "no KOs, one fall, a self-destruct"
    assert len({len(line.split()) for line in lines[1:]}) == 1


def test_result_awards_name_the_standouts_and_skip_what_nobody_earned() -> None:
    match = Match.create(load_stage("training_grid"), [ROOK] * 3, rules=MatchRules(stocks=1))
    assert result_awards(match) == [], "nothing happened yet"
    match.stats[1].damage_given = 123.4
    match.stats[0].damage_given = 80.0
    match.stats[2].longest_combo = 4
    match.stats[0].peak_damage = 151.2
    assert result_awards(match) == [
        "Most damage: P2 Rook (123%)",
        "Longest combo: P3 Rook (4 hits)",
        "Toughest: P1 Rook (survived to 151%)",
    ]


def test_tied_players_share_a_place() -> None:
    rules = MatchRules(stocks=None, time_frames=5)
    match = Match.create(load_stage("training_grid"), [ROOK] * 3, rules=rules)
    place(match, match.fighters[0], 5.5, 5.5, z=-9.0)
    for _ in range(5):
        match.tick(neutral(3))
    # P2 and P3 tie on 0: sudden death; settle it.
    place(match, match.fighters[2], 5.5, 5.5, z=-9.0)
    match.tick(neutral(3))
    assert match.result is not None and match.result.winner == 1
    places = [line.split()[0] for line in results_table(match)[1:]]
    assert places[0] == "1st" and len(places) == 3


# --- command line -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "skips"),
    [
        ([], False),
        (["--p1", "rook"], False),
        (["--seed", "4"], False),
        (["--battle"], True),
        (["--stage", "sky_ruins"], True),
        (["--training"], True),
    ],
)
def test_the_game_starts_at_the_menus_unless_asked_for_a_match(
    argv: list[str], skips: bool
) -> None:
    assert skips_menus(build_parser().parse_args(argv)) is skips
