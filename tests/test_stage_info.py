"""What stage select says about a stage, and how its cursor moves (plan note 13, decision
D-061, M13 group 6). Pure: no window. The screen itself is driven in ``tests/test_flow_gl.py``.
"""

from pathlib import Path

import pytest

from isofightr.data.character_loader import DataError
from isofightr.data.stage_loader import list_stage_ids, load_stage, parse_stage
from isofightr.render.iso import project, stage_screen_centre
from isofightr.scenes import stage_info
from isofightr.scenes.stage_info import move_in_strip
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


def test_the_cursor_walks_the_strip_and_wraps_at_its_ends() -> None:
    assert move_in_strip(0, RIGHT, 9) == 1 and move_in_strip(8, RIGHT, 9) == 0
    assert move_in_strip(0, LEFT, 9) == 8 and move_in_strip(4, LEFT, 9) == 3
    assert move_in_strip(4, UP, 9) == 4 == move_in_strip(4, DOWN, 9), "one row: nowhere to go"
    assert move_in_strip(2, MenuAction.CONFIRM, 7) == 2
    assert move_in_strip(0, RIGHT, 0) == 0


def test_the_strip_scrolls_to_keep_the_cursor_in_view() -> None:
    first = stage_info.strip_first
    shown = stage_info.STRIP_SHOWN
    assert shown == 10
    # Ten tiles or fewer: everything shows, nothing ever scrolls.
    assert all(first(cursor, 0, 10) == 0 for cursor in range(10))
    # Twelve tiles, ten on screen.
    assert first(9, 0, 12) == 0, "the tenth is the last one showing"
    assert first(10, 0, 12) == 1, "one more brings the eleventh in"
    assert first(11, 0, 12) == 2, "the last: the strip stops at its end"
    assert first(5, 2, 12) == 2, "still in view: it stays put"
    assert first(1, 2, 12) == 1 and first(0, 2, 12) == 0, "and back"
    assert first(4, 0, 7, shown=2) == 3 and first(6, 3, 7, shown=2) == 5
    assert first(0, 5, 3) == 0, "a first tile left over from a longer list is pulled back"
    rects = stage_info.strip_rects(12, 2, 10, 20, 58, 42, 4)
    assert rects[0] is None and rects[1] is None and rects[12 - 1] is not None
    assert rects[2] is not None and (rects[2].left, rects[2].bottom) == (10, 20)
    third = rects[3]
    assert third is not None and third.left == 10 + 62
    assert sum(rect is not None for rect in rects) == shown


@pytest.mark.parametrize("count", range(1, 31))
def test_the_cursors_tile_is_always_whole_on_screen(count: int) -> None:
    left, width, gap = 12, 58, 4
    first = 0
    for cursor in [*range(count), *reversed(range(count)), 0, count - 1, 0]:
        first = stage_info.strip_first(cursor, first, count)
        rects = stage_info.strip_rects(count, first, left, 22, width, 42, gap)
        rect = rects[cursor]
        assert rect is not None, (count, cursor)
        assert left <= rect.left and rect.right <= 640 - left + gap
        shown = [each for each in rects if each is not None]
        assert len(shown) == min(count, stage_info.STRIP_SHOWN)


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
