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


def test_a_hit_strip_follows_the_target_from_before_the_hit(window: Any) -> None:
    """Decision D-066: ticks count from the hit, earlier ones included, and every picture is
    a crop of the same size centred on the target."""
    from isofightr.capture import capture_hit_strip

    sheet = capture_hit_strip(
        window, "rook", "rook", "fsmash", 100, [-2, 0, 20, 40], crop=(100, 80), columns=2
    )
    assert sheet.size == (2 * 100, 2 * 80), "four pictures, two to a row"
    pictures = [sheet.crop((x, y, x + 100, y + 80)).tobytes() for y in (0, 80) for x in (0, 100)]
    assert len(set(pictures)) == 4, "the hit, the freeze and the flight all differ"
    with pytest.raises(ValueError, match="does not hit"):
        capture_hit_strip(window, "rook", "rook", "taunt", 0, [0, 2], crop=(100, 80))


def test_a_hit_strip_can_show_a_blocked_hit_and_a_parry(window: Any) -> None:
    """Decision D-068: with a guard the strip starts at the blocked hit; a parried attacker is
    frozen longer than the target (its hitlag gains ``PARRY_EXTRA_HITLAG``)."""
    from isofightr.capture import capture_hit_strip

    for guard in ("shield", "parry"):
        sheet = capture_hit_strip(
            window, "rook", "rook", "fsmash", 0, [0, 12], crop=(100, 80), guard=guard
        )
        assert sheet.size == (2 * 100, 80)
        left, right = sheet.crop((0, 0, 100, 80)), sheet.crop((100, 0, 200, 80))
        assert left.tobytes() != right.tobytes()
    with pytest.raises(ValueError, match="guard"):
        capture_hit_strip(window, "rook", "rook", "fsmash", 0, [0], guard="dodge")


def test_a_splash_sheet_has_a_row_per_tier_and_angle_and_a_column_per_tick(window: Any) -> None:
    """Decision D-068: rows are tiers times launch angles, columns the ticks from the hit;
    the hit shows on the contact tick and has faded by the end of the default ticks."""
    from isofightr.capture import capture_splash_sheet, splash_ticks

    ticks = splash_ticks(11)
    sheet = capture_splash_sheet(window, "slash", tiers=(0, 3), angles=(0, 4), crop=(60, 60))
    assert sheet.size == (len(ticks) * 60 * 2, 4 * 60 * 2)
    first = sheet.crop((0, 0, 120, 120)).tobytes()
    last = sheet.crop((sheet.width - 120, 0, sheet.width, 120)).tobytes()
    assert first != last
    with pytest.raises(ValueError, match="theme"):
        capture_splash_sheet(window, "plasma")


def test_splash_sheet_ticks_cover_the_burst_the_freeze_and_the_launch() -> None:
    from isofightr.capture import splash_ticks

    for hitlag in (3, 8, 11, 30):
        ticks = splash_ticks(hitlag)
        assert ticks == sorted(set(ticks)) and ticks[:2] == [0, 1]
        assert hitlag in ticks and hitlag + 1 in ticks and max(ticks) > hitlag + 10
        assert len([tick for tick in ticks if 1 < tick < hitlag]) <= 4


def test_screen_launch_points_where_the_projection_shows_it() -> None:
    """Every one of the 16 screen directions round-trips through the launch's own angle."""
    from isofightr.capture import screen_launch
    from isofightr.render.effects import streak_angle
    from isofightr.sim.fighter import Launch

    for angle in range(16):
        heading, elevation = screen_launch(angle)
        assert abs(heading.length() - 1.0) < 1e-9 and -90.0 <= elevation <= 90.0
        assert streak_angle(Launch(100.0, heading, elevation, True)) == angle


def test_a_splash_sheet_shows_character_themes_and_the_hit_effects_setting(window: Any) -> None:
    """Decision D-068: a character theme (a normal hit by an attacker with that hit theme) and
    the "Hit effects" setting, so before (off) and after can be captured from the same code."""
    from isofightr.capture import capture_splash_sheet

    def sheet(hit_effects: str) -> Any:
        return capture_splash_sheet(
            window, "earth", tiers=(2,), angles=(0,), ticks=[2, 12], crop=(60, 60),
            hit_effects=hit_effects,
        )  # fmt: skip

    off, full = sheet("off"), sheet("full")
    assert off.size == full.size == (2 * 60 * 2, 60 * 2)
    assert off.tobytes() != full.tobytes()
    with pytest.raises(ValueError, match="hit_effects"):
        capture_splash_sheet(window, "slash", hit_effects="loud")
