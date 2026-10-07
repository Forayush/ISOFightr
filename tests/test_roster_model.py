"""The character select screen's model: grid, costumes, stat bars, and the costume a setup
gives each player (plan note 13, decision D-061, M13 group 5).

Pure: no window. The screen itself is driven in ``tests/test_flow_gl.py``.
"""

import itertools

import pytest

from isofightr.data.character_loader import DataError, list_character_ids, load_character
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.scenes import roster_model
from isofightr.scenes.roster_model import (
    RANDOM,
    STAT_FLOOR,
    STAT_NAMES,
    TILES_PER_ROW,
    costume_swatches,
    free_costume,
    move_cursor,
    next_costume,
    raw_stats,
    roster_entries,
    roster_tiles,
    tile_rects,
)
from isofightr.scenes.setup import MatchSetup
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, InputFrame
from isofightr.ui import font
from isofightr.ui.menu import MenuAction, held_actions

ROSTER = [load_character(name) for name in list_character_ids()]
LEFT, RIGHT, UP, DOWN = MenuAction.LEFT, MenuAction.RIGHT, MenuAction.UP, MenuAction.DOWN


# --- grid ------------------------------------------------------------------------------------


def test_the_roster_is_every_character_then_random() -> None:
    assert roster_tiles(["a", "b"]) == ("a", "b", RANDOM)
    assert roster_tiles([]) == (RANDOM,)


@pytest.mark.parametrize("count", [1, 5, 6, 7, 12, 13])
def test_tiles_lay_themselves_out_in_rows_of_six(count: int) -> None:
    rects = tile_rects(count, 10, 300, 46, 46, 4)
    assert len(rects) == count
    for first, second in itertools.combinations(rects, 2):
        assert not first.overlaps(second)
    assert rects[0].left == 10 and rects[0].top == 300
    rows = {rect.bottom for rect in rects}
    assert len(rows) == (count + TILES_PER_ROW - 1) // TILES_PER_ROW
    assert max(rect.right for rect in rects) <= 10 + TILES_PER_ROW * 50
    if count > TILES_PER_ROW:
        assert rects[TILES_PER_ROW].left == 10 and rects[TILES_PER_ROW].top < rects[0].bottom


def test_the_cursor_wraps_along_a_row_and_leaves_the_grid_at_top_and_bottom() -> None:
    assert move_cursor(0, RIGHT, 5) == 1 and move_cursor(4, RIGHT, 5) == 0
    assert move_cursor(0, LEFT, 5) == 4
    assert move_cursor(2, UP, 5) is None and move_cursor(2, DOWN, 5) is None, "one row"
    assert move_cursor(2, MenuAction.CONFIRM, 5) == 2
    # Two rows: six tiles, then three.
    assert move_cursor(1, DOWN, 9) == 7 and move_cursor(7, UP, 9) == 1
    assert move_cursor(5, DOWN, 9) == 8, "onto the last tile of a shorter row"
    assert move_cursor(8, RIGHT, 9) == 6 and move_cursor(6, LEFT, 9) == 8
    assert move_cursor(7, DOWN, 9) is None and move_cursor(1, UP, 9) is None
    assert move_cursor(0, RIGHT, 1) == 0 and move_cursor(0, RIGHT, 0) == 0


# --- costumes --------------------------------------------------------------------------------


def test_costumes_cycle_and_skip_the_ones_others_wear() -> None:
    assert [next_costume(costume, 1, 6) for costume in range(6)] == [1, 2, 3, 4, 5, 0]
    assert next_costume(0, -1, 6) == 5
    assert next_costume(0, 1, 6, taken=[1, 2]) == 3
    assert next_costume(4, 1, 6, taken=[5, 0]) == 1
    assert next_costume(2, 1, 6, taken=[0, 1, 3, 4, 5]) == 2, "nothing else is free"
    assert next_costume(0, 1, 1) == 0
    assert free_costume(3, 6) == 3 and free_costume(9, 6) == 3
    assert free_costume(3, 6, taken=[3]) == 4 and free_costume(5, 6, taken=[5, 0]) == 1


def test_swatches_show_the_colour_that_tells_costumes_apart() -> None:
    def ramp(base: int) -> list[tuple[int, int, int]]:
        return [(base, base + shade, 0) for shade in range(5)]

    clear = [(0, 0, 0)]
    first = ("a", (*clear, *ramp(10), *ramp(100), *ramp(200)))
    second = ("b", (*clear, *ramp(10), *ramp(160), *ramp(40)))
    # Material 0 never changes; material 2 changes most; a swatch is a ramp's light shade.
    assert costume_swatches([first, second]) == [(200, 201, 0), (40, 41, 0)]
    covered = {6: 90, 7: 90, 11: 1, 1: 300}
    assert costume_swatches([first, second], covered) == [(100, 101, 0), (160, 161, 0)], (
        "weighted by how much of the picture the material covers"
    )
    mostly_first = {1: 100_000, 11: 400, 12: 400}
    assert costume_swatches([first, second], mostly_first) == [(200, 201, 0), (40, 41, 0)], (
        "a material that never changes is never the swatch, however much it covers"
    )
    assert costume_swatches([]) == []
    for name in list_character_ids():
        sprite_set = load_sprite_set(name)
        assert sprite_set is not None
        swatches = costume_swatches(sprite_set.costumes)
        assert len(set(swatches)) == len(sprite_set.costumes) == 6, f"{name}: six looks"


def test_a_setup_gives_each_player_a_costume() -> None:
    free = MatchSetup(characters=("rook",) * 4)
    assert [free.costume_of(player, 6) for player in range(4)] == [0, 2, 3, 4], "as before M13"
    picked = MatchSetup(characters=("rook",) * 3, costumes=(5, 1))
    assert [picked.costume_of(player, 6) for player in range(3)] == [5, 1, 3]
    assert picked.costume_of(0, 4) == 1, "a costume number past the character's wraps"
    teams = MatchSetup(
        characters=("rook",) * 4, team_play=True, teams=(0, 1, 1, 0), costumes=(5, 5, 5, 5)
    )
    assert [teams.costume_of(player, 6) for player in range(4)] == [1, 2, 2, 1], "team colours win"
    training = MatchSetup(characters=("rook", "rook"), training=True, team_play=True, teams=(0, 0))
    assert training.costume_of(1, 6) == 2
    assert picked.rules() == MatchSetup(characters=("rook",) * 3).rules(), "presentation only"


# --- stats and text --------------------------------------------------------------------------


def test_stats_come_from_the_character_data() -> None:
    by_id = {character.id: raw_stats(character) for character in ROSTER}
    for character in ROSTER:
        stats = by_id[character.id]
        assert stats["weight"] == character.weight
        assert stats["speed"] == character.movement.run_speed
        assert stats["air"] == character.movement.air_speed
        assert stats["power"] > 5.0
    assert by_id["bramble"]["power"] == max(stats["power"] for stats in by_id.values())


def test_bars_are_scaled_across_the_roster() -> None:
    entries = roster_entries(ROSTER)
    assert set(entries) == set(list_character_ids())
    for stat in STAT_NAMES:
        values = [entry.stats[stat] for entry in entries.values()]
        assert min(values) == pytest.approx(STAT_FLOOR) and max(values) == pytest.approx(1.0)
    assert entries["bramble"].stats["weight"] == 1.0, "the heavy"
    assert entries["zephyr"].stats["speed"] == 1.0, "the rushdown"
    assert entries["mote"].stats["air"] == 1.0, "the floaty one"
    assert entries["zephyr"].stats["weight"] == pytest.approx(STAT_FLOOR)
    alone = roster_entries(ROSTER[:1])
    assert all(value == 1.0 for value in next(iter(alone.values())).stats.values())


def test_every_character_has_an_archetype_and_a_blurb_that_fit_the_strip() -> None:
    entries = roster_entries(ROSTER)
    for character in ROSTER:
        entry = entries[character.id]
        assert entry.name == character.display_name
        assert entry.archetype.startswith("the ") and len(entry.archetype) <= 20
        assert entry.blurb.endswith(".") and 20 <= len(entry.blurb) <= 80
        assert font.text_width(entry.blurb) <= 2 * 286, "two lines of the detail strip"
    assert len({entry.archetype for entry in entries.values()}) == len(ROSTER)
    assert roster_model.RANDOM_ENTRY.stats == {} and roster_model.RANDOM_ENTRY.blurb


def test_archetype_and_blurb_are_optional_text_keys(tmp_path: object) -> None:
    from isofightr.data.character_loader import parse_character

    rook = load_character("rook")
    assert rook.archetype == "the all-rounder" and "knight" in rook.blurb
    assert hash(rook.archetype) is not None
    import tomllib

    from isofightr.data.paths import CHARACTERS_DIR

    with (CHARACTERS_DIR / "rook" / "fighter.toml").open("rb") as file:
        data = tomllib.load(file)
    del data["archetype"], data["blurb"]
    plain = parse_character(data, moves=rook.moves, source="test")
    assert plain.archetype == "" and plain.blurb == ""
    with pytest.raises(DataError):
        parse_character({**data, "archetype": 3}, moves=rook.moves, source="test")
    with pytest.raises(DataError):
        parse_character({**data, "nickname": "x"}, moves=rook.moves, source="test")


# --- menu actions for the costume keys -------------------------------------------------------


def test_strong_and_the_modifiers_are_menu_actions() -> None:
    assert held_actions(InputFrame(held=int(Button.STRONG))) == {MenuAction.ALT}
    assert held_actions(InputFrame(vertical=VERTICAL_UP)) == {MenuAction.ALT}
    assert held_actions(InputFrame(vertical=VERTICAL_DOWN)) == {MenuAction.ALT_BACK}
    assert held_actions(InputFrame()) == frozenset()
    from isofightr.ui.menu import MENU_SOUNDS, Menu, MenuItem

    assert set(MENU_SOUNDS) == set(MenuAction) and MENU_SOUNDS[MenuAction.ALT] == ""
    menu = Menu([MenuItem("a", "A"), MenuItem("b", "B")])
    assert menu.apply(MenuAction.ALT) is None and menu.cursor == 0, "plain menus ignore them"


# --- quitting a match that cannot be paused ---------------------------------------------------


def test_the_quit_chord_needs_the_quit_control_attack_and_special() -> None:
    from isofightr.scenes.setup import quit_chord
    from isofightr.settings import QUIT_KEY, RESERVED_KEYS

    both = InputFrame(held=int(Button.ATTACK | Button.SPECIAL))
    attack = InputFrame(held=int(Button.ATTACK))
    assert quit_chord([attack, both], [False, True])
    assert not quit_chord([both, attack], [False, True]), "one player's own control"
    assert not quit_chord([attack], [True]) and not quit_chord([both], [False])
    assert not quit_chord([], [])
    assert QUIT_KEY == "BACKSPACE" and QUIT_KEY in RESERVED_KEYS
