"""The stage report: every stage in ``assets/stages`` against the design rules, and each rule
against a stage built to break it (plan note 11, decision D-063, M14 group 0). Pure: no window.
"""

from dataclasses import replace

import pytest

from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage, parse_stage
from isofightr.data.stage_rules import (
    PLATFORM_REACH,
    RULES,
    check_stage,
    failures,
    hop_height,
    islands,
    screen_extent,
)
from isofightr.sim.math3d import Vec2
from isofightr.sim.stage import Stage

ROSTER = [load_character(name) for name in list_character_ids()]


def build(grid: str, platforms: list[dict[str, object]] | None = None, **extra: object) -> Stage:
    rows = [row for row in grid.strip().splitlines() if row]
    width, depth = len(rows[0]), len(rows)
    return parse_stage(
        {
            "id": "test",
            "display_name": "Test",
            "tileset": "grass_stone",
            "grid": "\n".join(rows),
            "legend": {"0": {"height": 0, "tile": "grass"}},
            "soft_platforms": platforms or [],
            "spawns": {
                "p1": [0.5, 0.5],
                "p2": [width - 0.5, 0.5],
                "p3": [0.5, depth - 0.5],
                "p4": [width - 0.5, depth - 0.5],
                "respawn": [0.5, 0.5],
            },
            **extra,
        },
        source="test",
    )


SQUARE = "\n".join(["000000"] * 6)


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_stage_passes_the_design_rules(stage_id: str) -> None:
    checks = check_stage(load_stage(stage_id), ROSTER)
    assert [check.rule for check in checks] == list(RULES)
    assert failures(checks) == [], [check.detail for check in checks if not check.passed]


def test_a_good_square_passes_everything() -> None:
    checks = check_stage(build(SQUARE, [{"rect": [2, 2, 4, 4], "z": 2.5}]), ROSTER)
    assert failures(checks) == [] and all(check.detail for check in checks)


def test_spawns_too_close_or_off_the_ground_fail() -> None:
    stage = build(SQUARE)
    crowded = replace(stage, spawns=(Vec2(0.5, 0.5), Vec2(2.5, 0.5), *stage.spawns[2:]))
    assert failures(check_stage(crowded, ROSTER)) == ["spawns"]
    floating = replace(stage, spawns=(Vec2(-3.0, 0.5), *stage.spawns[1:]))
    check = check_stage(floating, ROSTER)[0]
    assert not check.passed and "p1 is not on solid ground" in check.detail


def test_an_island_without_a_ledge_fails() -> None:
    stage = build(SQUARE)
    assert failures(check_stage(replace(stage, ledges=()), ROSTER)) == ["ledges"]
    two = build("\n".join(["000...000"] * 6))
    assert len(islands(two)) == 2 and failures(check_stage(two, ROSTER)) == []
    left_only = tuple(ledge for ledge in two.ledges if max(ledge.start.x, ledge.end.x) <= 3)
    check = check_stage(replace(two, ledges=left_only), ROSTER)[1]
    assert not check.passed and "1 island(s) have none" in check.detail


def test_a_platform_out_of_reach_fails_and_a_stair_of_platforms_passes() -> None:
    hop = min(hop_height(character) for character in ROSTER)
    assert 2.5 < hop < 6.0, "about three units: the roster's lowest full hop"
    too_high = hop * PLATFORM_REACH + 0.5
    lone = build(SQUARE, [{"rect": [2, 2, 4, 4], "z": too_high}])
    assert failures(check_stage(lone, ROSTER)) == ["platforms_reachable"]
    stair = build(
        SQUARE, [{"rect": [0, 0, 2, 2], "z": too_high / 2}, {"rect": [3, 3, 5, 5], "z": too_high}]
    )
    assert failures(check_stage(stair, ROSTER)) == [], "reached from the lower platform"


def test_a_stage_wider_than_the_play_area_fails() -> None:
    huge = build("\n".join(["0" * 24] * 24))
    assert screen_extent(huge)[0] == 24 * 32
    assert failures(check_stage(huge, ROSTER)) == ["fits_play_area"]
    assert screen_extent(build(SQUARE))[0] == 6 * 32


def test_blast_zones_too_close_fail() -> None:
    tight = build(SQUARE, blast_zone={"side": 3.0, "top": 14.0, "bottom": -8.0})
    check = check_stage(tight, ROSTER)[4]
    assert not check.passed and "side zone" in check.detail
    low = build(
        SQUARE,
        [{"rect": [2, 2, 4, 4], "z": 3.0}],
        blast_zone={"side": 7.0, "top": 6.0, "bottom": -8.0},
    )
    assert failures(check_stage(low, ROSTER)) == ["blast_zones"]


def test_a_notch_one_cell_wide_fails() -> None:
    notched = build("000000\n000000\n00.000\n000000\n000000\n000000")
    check = check_stage(notched, ROSTER)[5]
    assert not check.passed and "(2, 2)" in check.detail
    wide_gap = build("\n".join(["00..00"] * 6))
    assert check_stage(wide_gap, ROSTER)[5].passed, "a gap two cells wide is fine"
