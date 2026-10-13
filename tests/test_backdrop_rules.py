"""The depth report: every stage's backdrop against the rules that keep it behind the stage
(decision D-065), and each rule against a picture built to break it. Pure: no window.
"""

import math

import pytest
from PIL import Image

from isofightr.data.backdrop_rules import (
    INK,
    LIGHT_SHARE,
    MAX_CONTRAST,
    MAX_HAZE_FAR,
    MAX_HAZE_NEAR,
    MAX_SHARED,
    RULES,
    check_layer,
    check_stage,
    colour_table,
    contrast,
    failures,
    haze_colour,
    mean_colour,
    oklab,
    playfield_table,
    report_lines,
    without_lights,
)
from isofightr.data.stage_loader import list_stage_ids, load_stage

NOT_YET_REPAINTED = {
    "dune_bazaar",
    "ember_forge",
    "final_plateau",
    "frostpeak",
    "neon_circuit",
    "training_grid",
}
"""Stages whose backdrops still break a rule: M15 group 2 repaints them in three batches and
takes each off this list as it passes. Never add a stage here."""

GRASS, DIRT, WHITE = (0x91, 0xDB, 0x69), (0x9E, 0x45, 0x39), (255, 255, 255)
SKY, PALE, NAVY = (0x4D, 0x9B, 0xE6), (0x8F, 0xD3, 0xFF), (0x32, 0x33, 0x53)
FIELD = {GRASS: 700, DIRT: 200, WHITE: 100}


def picture(*bands: tuple[tuple[int, int, int], int], size: int = 100) -> Image.Image:
    """A square picture filled top to bottom with rows of each colour (colour, rows); rows
    left over stay empty."""
    image = Image.new("RGBA", (size, size))
    row = 0
    for colour, rows in bands:
        image.paste((*colour, 255), (0, row, size, row + rows))
        row += rows
    return image


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_stage_backdrop_is_behind_the_stage(stage_id: str) -> None:
    reports = check_stage(load_stage(stage_id))
    assert reports and reports[0].sky and reports[0].passed, "the sky is exempt"
    broken = failures(reports)
    if stage_id in NOT_YET_REPAINTED:
        assert broken, f"{stage_id} passes now: take it off NOT_YET_REPAINTED"
    else:
        assert not broken, broken


def test_the_allow_list_only_names_real_stages() -> None:
    assert set(list_stage_ids()) >= NOT_YET_REPAINTED


def test_oklab_is_a_lightness_and_two_colour_axes() -> None:
    assert oklab((0, 0, 0)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    white = oklab(WHITE)
    assert white[0] == pytest.approx(1.0, abs=1e-3) and math.hypot(white[1], white[2]) < 1e-3
    assert oklab(PALE)[0] > oklab(SKY)[0] > oklab(NAVY)[0]
    assert math.dist(oklab(GRASS), oklab(DIRT)) > math.dist(oklab(SKY), oklab(PALE))


def test_tables_means_and_contrast() -> None:
    table = colour_table(picture((GRASS, 30), (DIRT, 20)))
    assert table == {GRASS: 3000, DIRT: 2000}, "empty rows are not counted"
    assert mean_colour({GRASS: 5})[0] == pytest.approx(oklab(GRASS)[0])
    assert contrast({GRASS: 5}) == pytest.approx(0.0, abs=1e-9)
    assert contrast({WHITE: 1, (0, 0, 0): 1}) == pytest.approx(0.5, abs=1e-3)


def test_lights_are_the_lightest_colours_up_to_a_share() -> None:
    table = {NAVY: 880, PALE: 100, WHITE: 20}
    assert without_lights(table) == {NAVY: 880}, "the windows go, the wall stays"
    assert without_lights({NAVY: 500, WHITE: 500}) == {NAVY: 500, WHITE: 500}, "half is no accent"
    assert without_lights({WHITE: 9}) == {WHITE: 9}, "something is always left"
    assert LIGHT_SHARE == 0.15


def test_the_playfield_is_the_top_faces_of_the_tiles_a_stage_uses() -> None:
    sky_ruins = playfield_table(load_stage("sky_ruins"))
    assert sum(sky_ruins.values()) > 256 * 4, "several tiles and their variants"
    plateau = playfield_table(load_stage("final_plateau"))
    assert len(set(plateau) - INK) < len(set(sky_ruins) - INK), "a plainer stage, fewer colours"
    assert (0x91, 0xDB, 0x69) in sky_ruins or (0xCD, 0xDF, 0x6C) in sky_ruins, "its grass"


def test_a_layer_in_the_playfields_own_colours_fails() -> None:
    haze = haze_colour(picture((SKY, 400), size=640))
    hill = check_layer(picture((GRASS, 40)), "hill.png", 0.2, FIELD, haze)
    assert "colours" in hill.failed and hill.shared == 1.0
    mostly_new = check_layer(picture((PALE, 37), (GRASS, 3)), "hill.png", 0.2, FIELD, haze)
    assert "colours" not in mostly_new.failed and mostly_new.shared <= MAX_SHARED
    white = check_layer(picture((WHITE, 40)), "cloud.png", 0.2, {**FIELD, WHITE: 500}, haze)
    assert white.shared == 0.0, "white is everybody's"


def test_a_layer_with_more_contrast_than_the_playfield_fails() -> None:
    haze = haze_colour(picture((SKY, 400), size=640))
    flat = check_layer(picture((PALE, 40)), "flat.png", 0.2, FIELD, haze)
    assert flat.contrast == 0.0 and "contrast" not in flat.failed
    harsh = check_layer(picture((PALE, 20), (NAVY, 20)), "harsh.png", 0.2, FIELD, haze)
    assert harsh.contrast > MAX_CONTRAST and "contrast" in harsh.failed
    lit = check_layer(picture((NAVY, 36), (WHITE, 4)), "windows.png", 0.2, FIELD, haze)
    assert lit.contrast == 0.0, "a few lights are left out"


def test_a_layer_further_from_the_sky_than_the_playfield_fails() -> None:
    haze = haze_colour(picture((SKY, 400), size=640))
    near_sky = check_layer(picture((PALE, 40)), "haze.png", 0.3, FIELD, haze)
    assert near_sky.haze < MAX_HAZE_NEAR and near_sky.passed
    stark = check_layer(picture(((0xE8, 0x3B, 0x3B), 40)), "red.png", 0.3, FIELD, haze)
    assert stark.haze > MAX_HAZE_NEAR and stark.failed == ("haze",)
    middling = (0x4D, 0x65, 0xB4)
    close = check_layer(picture((middling, 40)), "ridge.png", 0.3, FIELD, haze)
    far = check_layer(picture((middling, 40)), "ridge.png", 0.05, FIELD, haze)
    assert close.haze == far.haze and far.haze_limit == MAX_HAZE_FAR < close.haze_limit
    assert MAX_HAZE_FAR < MAX_HAZE_NEAR, "a far layer must be nearer the sky's colour"


def test_a_sparse_layer_only_has_to_avoid_the_playfields_colours() -> None:
    haze = haze_colour(picture((SKY, 400), size=640))
    birds = check_layer(picture((NAVY, 2), (WHITE, 2)), "birds.png", 0.1, FIELD, haze)
    assert birds.sparse and birds.passed
    grass_birds = check_layer(picture((GRASS, 2)), "birds.png", 0.1, FIELD, haze)
    assert grass_birds.failed == ("colours",)


def test_the_sky_is_exempt_and_the_report_says_what_failed() -> None:
    haze = haze_colour(picture((SKY, 400), size=640))
    sky = check_layer(picture((GRASS, 100)), "bg_0_sky.png", 0.0, FIELD, haze, sky=True)
    assert sky.passed and sky.sky
    hill = check_layer(picture((GRASS, 40)), "bg_3_hill.png", 0.2, FIELD, haze)
    lines = report_lines([sky, hill])
    assert lines[0].rstrip().endswith("sky") and "FAIL colours" in lines[1]
    assert failures([sky, hill])[0].startswith("bg_3_hill.png: colours")
    assert set(hill.failed) <= set(RULES)


def test_an_animated_layer_is_measured_on_one_frame() -> None:
    stage = load_stage("final_plateau")
    stars = next(layer for layer in stage.backgrounds if layer.frames > 1)
    report = next(each for each in check_stage(stage) if each.image == stars.image)
    assert report.cover < 0.05, "one frame's worth of stars over one frame's area"


MAX_PARALLAX = 0.35


@pytest.mark.parametrize("stage_id", sorted(set(list_stage_ids()) - NOT_YET_REPAINTED))
def test_a_repainted_backdrop_moves_apart_from_the_stage(stage_id: str) -> None:
    """Decision D-065: no layer follows the camera by more than 0.35, and at least two move by
    themselves (they drift, or they are animated), so the backdrop never moves like the
    stage."""
    layers = load_stage(stage_id).backgrounds
    assert all(layer.parallax <= MAX_PARALLAX for layer in layers)
    assert sum(layer.scroll != 0.0 or layer.frames > 1 for layer in layers) >= 2


def test_things_that_look_like_ground_keep_out_of_the_stages_columns() -> None:
    from isofightr.render.backdrop import LAYER_SHIFT, LAYER_WIDTH, STAGE_COLUMNS, clear_of_stage

    left, right = STAGE_COLUMNS
    for x in range(0, LAYER_WIDTH, 7):
        for half in (4, 18, 40):
            moved = clear_of_stage(x, half)
            screen = (moved + LAYER_SHIFT) % LAYER_WIDTH
            assert screen + half <= left or screen - half >= right, (x, half)
    far_off = (700 - LAYER_SHIFT) % LAYER_WIDTH
    assert clear_of_stage(far_off, 10) == far_off, "already clear: left where it was"
