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


def test_the_cursor_walks_a_two_column_grid() -> None:
    assert STAGE_COLUMNS == 2
    # Six tiles: three rows of two.
    assert move_in_grid(0, RIGHT, 6) == 1 and move_in_grid(1, RIGHT, 6) == 0
    assert move_in_grid(0, LEFT, 6) == 1
    assert move_in_grid(0, DOWN, 6) == 2 and move_in_grid(4, DOWN, 6) == 4, "stops at the end"
    assert move_in_grid(3, UP, 6) == 1 and move_in_grid(1, UP, 6) == 1
    # Five tiles: the last row has one.
    assert move_in_grid(3, DOWN, 5) == 4, "onto the lone tile below"
    assert move_in_grid(4, RIGHT, 5) == 4
    assert move_in_grid(2, MenuAction.CONFIRM, 5) == 2
    rects = stage_info.grid_rects(5, 10, 300, 90, 60, 6)
    assert rects[1].left == 106 and rects[2].top == rects[0].bottom - 6


def test_pool_text() -> None:
    assert stage_info.pool_text(["a", "c"], ["a", "b", "c"]) == "2 / 3"
    assert stage_info.pool_text(["a", "x"], ["a", "b"]) == "1 / 2"
