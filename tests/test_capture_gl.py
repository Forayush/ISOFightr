"""Smoke test for the offscreen capture tool (plan note 16, decision D-060)."""

from typing import Any

import pytest

pytestmark = pytest.mark.gl


def test_a_scripted_battle_is_captured_as_a_contact_sheet(window: Any) -> None:
    from isofightr.capture import KeyStep, capture, parse_script

    script = parse_script("K@2, K!3")
    assert [(step.tick, step.down) for step in script] == [(2, True), (3, False)]
    assert isinstance(script[0], KeyStep)
    with pytest.raises(ValueError, match="bad key step"):
        parse_script("NOPE@2")
    sheet = capture(
        window,
        ["rook", "rook"],
        "training_grid",
        script,
        ticks=[5, 25],
        positions=[(4.0, 6.0, 0.0), (8.0, 6.0, 0.0)],
        crop=(160, 60, 320, 200),
        scale=2,
    )
    assert sheet.size == (2 * 320 * 2, 200 * 2), "two frames side by side, at 2x"
    colours = sheet.getcolors(maxcolors=100000)
    assert colours is not None and len(colours) > 8, "something was drawn"
    first = sheet.crop((0, 0, 640, 400))
    second = sheet.crop((640, 0, 1280, 400))
    assert first.tobytes() != second.tobytes(), "the projectile moved between the two ticks"


def test_a_stage_sheet_has_the_whole_screen_and_eight_close_ups_per_tick(window: Any) -> None:
    from isofightr.capture import CLOSE_UP, capture_stage_sheet, stage_views
    from isofightr.data.stage_loader import load_stage

    names = [name for name, _ in stage_views(load_stage("twin_isles"))]
    assert names == [
        "p1 spawn",
        "p2 spawn",
        "p3 spawn",
        "p4 spawn",
        "left edge",
        "right edge",
        "underside",
        "top",
    ]
    sheet = capture_stage_sheet(window, "twin_isles", ticks=[1, 10])
    wide, tall = CLOSE_UP[0] * 2, CLOSE_UP[1] * 2
    assert sheet.size == (640 + 4 * wide, 2 * 360), "one row per tick"
    for row in range(2):
        for index in range(len(names)):
            left, top = 640 + (index % 4) * wide, row * 360 + (index // 4) * tall
            tile = sheet.crop((left, top, left + wide, top + tall))
            colours = tile.getcolors(maxcolors=100000)
            assert colours is not None and len(colours) > 8, f"{names[index]} shows the stage"
    hud = sheet.crop((0, 312, 640, 360))
    spawn = sheet.crop((640, 0, 640 + wide, tall))
    assert hud.tobytes() != spawn.tobytes()
    view = window.current_view
    assert view.hud_display and view.camera.clamped, "the camera and the HUD are put back"
    with pytest.raises(ValueError, match="no ticks"):
        capture_stage_sheet(window, "twin_isles", ticks=[])


def test_the_depth_lab_puts_each_ground_point_beside_its_off_stage_twin(window: Any) -> None:
    """Decision D-065: the pair lands on the same pixels, so the two pictures of a row differ
    only around the fighter (its pose, and what the game draws to tell the places apart)."""
    from PIL import ImageChops

    from isofightr.capture import DEPTH_LAB_CROP, DEPTH_LAB_SCALE, capture_depth_lab

    wide, tall = DEPTH_LAB_CROP[0] * DEPTH_LAB_SCALE, DEPTH_LAB_CROP[1] * DEPTH_LAB_SCALE
    sheet = capture_depth_lab(window, "twin_isles", pairs=2)
    assert sheet.size == (2 * wide, 2 * tall), "a row per pair: on the ground, then in the air"
    label = 12 * DEPTH_LAB_SCALE
    for row in range(2):
        ground = sheet.crop((0, row * tall + label, wide, (row + 1) * tall)).convert("RGB")
        air = sheet.crop((wide, row * tall + label, 2 * wide, (row + 1) * tall)).convert("RGB")
        box = ImageChops.difference(ground, air).getbbox()
        assert box is not None, "the two are not the same picture"
        assert box[2] - box[0] <= wide // 2 and box[3] - box[1] <= tall * 3 // 4, (
            "and they differ only around the fighter"
        )
