"""What stage select says about a stage, and how its cursor moves (plan note 13, decision
D-061, M13 group 6). Pure: no window. The screen itself is driven in ``tests/test_flow_gl.py``.
"""

from pathlib import Path

import pytest

from isofightr.data.character_loader import DataError
from isofightr.data.stage_loader import list_stage_ids, load_stage, parse_stage
from isofightr.render.iso import project, stage_screen_centre
from isofightr.scenes import stage_info
from isofightr.scenes.stage_info import STAGE_COLUMNS, move_in_grid
from isofightr.ui import font
from isofightr.ui.menu import MenuAction

LEFT, RIGHT, UP, DOWN = MenuAction.LEFT, MenuAction.RIGHT, MenuAction.UP, MenuAction.DOWN
DESCRIPTION_WIDTH = 408
"""The width the description line has on screen, under the preview."""


def small_stage(grid: str, platforms: list[dict[str, object]] | None = None, **extra: object):
    rows = [row for row in grid.strip().splitlines() if row]
    return parse_stage(
        {
            "id": "test",
            "display_name": "Test",
            "tileset": "grass_stone",
            "grid": "\n".join(rows),
            "legend": {"0": {"height": 0, "tile": "grass"}, "1": {"height": 1, "tile": "grass"}},
            "soft_platforms": platforms or [],
            "spawns": {
                "p1": [0.5, 0.5],
                "p2": [0.5, 0.5 + 4.5],
                "p3": [4.5, 0.5],
                "p4": [4.5, 4.5],
                "respawn": [0.5, 0.5],
            },
            **extra,
        },
        source="test",
    )


GRID = """
00000
00000
00000
00000
00000
00000
"""


def test_a_description_is_made_from_the_ground_when_there_is_none() -> None:
    plain = small_stage(GRID)
    assert stage_info.island_count(plain) == 1 and stage_info.is_flat(plain)
    assert stage_info.describe(plain) == "One island, flat and open."
    deck = {"rect": [1, 1, 3, 3], "z": 2.5}
    assert stage_info.describe(small_stage(GRID, [deck])) == "One island with one soft platform."
    split = GRID.replace("00000\n00000\n00000\n00000", "00000\n.....\n00000\n00000", 1)
    two = small_stage(split, [deck, {"rect": [1, 3, 3, 5], "z": 2.5}])
    assert stage_info.island_count(two) == 2
    assert stage_info.describe(two) == "Two islands with two soft platforms."
    raised = small_stage(GRID.replace("00000", "00100", 1))
    assert not stage_info.is_flat(raised)
    assert stage_info.describe(raised) == "One island with raised ground."
    given = small_stage(GRID, description="Hand written.")
    assert stage_info.describe(given) == "Hand written."


def test_description_is_an_optional_text_key() -> None:
    assert load_stage("sky_ruins").description.endswith(".")
    assert load_stage("training_grid").description == "", "left to be made from the data"
    with pytest.raises(DataError):
        small_stage(GRID, description=3)


def test_every_stage_description_fits_its_line() -> None:
    for name in list_stage_ids():
        text = stage_info.describe(load_stage(name))
        assert text.endswith(".") and font.text_width(text) <= DESCRIPTION_WIDTH, name


def test_music_titles_come_from_the_audio_manifest(tmp_path: Path) -> None:
    titles = stage_info.load_music_titles()
    stage = load_stage("sky_ruins")
    assert stage_info.music_line(stage, titles) == titles["sky_ruins"] != ""
    assert stage_info.music_line(stage, {}) == "Sky Ruins", "the song's id, if no title"
    assert stage_info.load_music_titles(tmp_path / "missing.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert stage_info.load_music_titles(broken) == {}
    assert stage_info.music_line(small_stage(GRID), titles) == ""


def test_size_line() -> None:
    assert stage_info.size_line(load_stage("sky_ruins")) == "13 x 9   3 PLATFORMS"
    assert stage_info.size_line(small_stage(GRID, [{"rect": [1, 1, 3, 3], "z": 2.5}])) == (
        "5 x 6   1 PLATFORM"
    )


def test_the_preview_frames_the_whole_stage() -> None:
    stage = load_stage("sky_ruins")
    x, y = stage_screen_centre(stage)
    corners = [project(0, 0, 0), project(stage.size_x, stage.size_y, 0)]
    assert min(c[1] for c in corners) < y < max(c[1] for c in corners) + 4 * 16
    left, right = project(0, stage.size_y, 0)[0], project(stage.size_x, 0, 0)[0]
    assert x == pytest.approx((left + right) / 2)


def test_the_cursor_walks_a_three_column_grid() -> None:
    assert STAGE_COLUMNS == 3
    # Nine tiles: three rows of three.
    assert move_in_grid(0, RIGHT, 9) == 1 and move_in_grid(2, RIGHT, 9) == 0
    assert move_in_grid(0, LEFT, 9) == 2
    assert move_in_grid(0, DOWN, 9) == 3 and move_in_grid(7, DOWN, 9) == 7, "stops at the end"
    assert move_in_grid(5, UP, 9) == 2 and move_in_grid(1, UP, 9) == 1
    # Seven tiles: the last row has one.
    assert move_in_grid(5, DOWN, 7) == 6, "onto the lone tile below"
    assert move_in_grid(6, RIGHT, 7) == 6
    assert move_in_grid(2, MenuAction.CONFIRM, 7) == 2
    rects = stage_info.grid_rects(7, 10, 300, 90, 60, 6)
    assert rects[1].left == 106 and rects[3].top == rects[0].bottom - 6


def test_the_grid_scrolls_by_rows_to_keep_the_cursor_in_view() -> None:
    first_row, row_count = stage_info.first_row, stage_info.row_count
    assert stage_info.STAGE_ROWS == 4
    assert [row_count(count) for count in (0, 1, 3, 4, 12, 13)] == [0, 1, 1, 2, 4, 5]
    # Twelve tiles are four rows: everything shows, nothing ever scrolls.
    assert all(first_row(cursor, 0, 12) == 0 for cursor in range(12))
    # Twenty tiles are seven rows, four on screen.
    assert first_row(11, 0, 20) == 0, "row 3 is the last one showing"
    assert first_row(12, 0, 20) == 1, "one row down brings row 4 in"
    assert first_row(19, 0, 20) == 3, "the last row: the grid stops at its end"
    assert first_row(9, 3, 20) == 3, "still in view: it stays put"
    assert first_row(6, 3, 20) == 2 and first_row(0, 3, 20) == 0, "and back up"
    assert first_row(4, 0, 7, rows=1) == 1 and first_row(6, 1, 7, rows=1) == 2
    assert first_row(0, 5, 3) == 0, "a first row left over from a longer list is pulled back"


def test_pool_text() -> None:
    assert stage_info.pool_text(["a", "c"], ["a", "b", "c"]) == "2 / 3"
    assert stage_info.pool_text(["a", "x"], ["a", "b"]) == "1 / 2"


def test_a_tile_badge_marks_stages_with_a_mechanic_and_dims_with_the_rule_off() -> None:
    plain, moving = load_stage("final_plateau"), load_stage("twin_isles")
    assert stage_info.badge(plain, True) == stage_info.badge(plain, False) == ""
    assert stage_info.badge(moving, True) == "on"
    assert stage_info.badge(moving, False) == "off"
    with_one = [name for name in list_stage_ids() if load_stage(name).has_mechanics]
    assert len(with_one) == 8, "the six new stages, Twin Isles and Lily Pads"
