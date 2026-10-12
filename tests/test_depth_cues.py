"""The marker model: where a fighter's ground marker and height line go (decision D-065).
Pure: no window.
"""

import pytest

from isofightr.data.stage_loader import list_stage_ids, load_stage, parse_stage
from isofightr.render.depth_cues import (
    LINE_MIN_HEIGHT,
    Place,
    cue,
    off_stage_twins,
    twin,
)
from isofightr.render.iso import project
from isofightr.sim.stage import Stage


def build(grid: str, legend: dict[str, object], platforms: list[dict[str, object]]) -> Stage:
    rows = [row for row in grid.strip().splitlines() if row]
    return parse_stage(
        {
            "id": "test",
            "display_name": "Test",
            "tileset": "grass_stone",
            "grid": "\n".join(rows),
            "legend": legend,
            "soft_platforms": platforms,
            "spawns": {
                "p1": [0.5, 0.5],
                "p2": [5.5, 0.5],
                "p3": [0.5, 5.5],
                "p4": [5.5, 5.5],
                "respawn": [0.5, 0.5],
            },
        },
        source="test",
    )


STEPPED = build(
    """
000000
000000
000000
000000
000011
000011
""",
    {"0": {"height": 0}, "1": {"height": 1}},
    [{"rect": [1, 1, 3, 3], "z": 2.5}],
)


def test_a_point_and_its_twin_land_on_the_same_pixels() -> None:
    for lift in (0.5, 1.0, 3.0, 7.25):
        assert project(*twin(8.5, 5.5, 0.0, lift)) == project(8.5, 5.5, 0.0)
    assert project(11.5, 8.5, 3.0) == project(8.5, 5.5, 0.0) == (48.0, -112.0), "D-065's pair"


def test_the_reference_plane_is_the_height_most_cells_have() -> None:
    assert STEPPED.reference_z == 0.0
    high = chr(10).join(["111111"] * 4 + ["000000"] * 2)
    assert build(high, {"0": {"height": 0}, "1": {"height": 1}}, []).reference_z == 1.0
    tie = chr(10).join(["111000"] * 6)
    assert build(tie, {"0": {"height": 0}, "1": {"height": 2}}, []).reference_z == 0.0, (
        "the lower of two that tie"
    )
    assert [load_stage(name).reference_z for name in list_stage_ids()] == [0.0] * 11


def test_on_the_ground_the_marker_is_the_surface_and_there_is_no_line() -> None:
    standing = cue(STEPPED, 0.5, 4.5, 0.0)
    assert (standing.place, standing.marker_z, standing.dashed, standing.line) == (
        Place.SURFACE,
        0.0,
        False,
        0.0,
    )
    assert standing.grounded
    raised = cue(STEPPED, 4.5, 4.5, 1.0)
    assert raised.marker_z == 1.0 and raised.grounded, "a raised cell is its own surface"
    on_deck = cue(STEPPED, 1.5, 1.5, 2.5)
    assert on_deck.marker_z == 2.5 and on_deck.grounded, "so is a platform's deck"


def test_in_the_air_over_ground_a_line_appears_from_one_unit_up() -> None:
    hop = cue(STEPPED, 0.5, 4.5, LINE_MIN_HEIGHT - 0.01)
    assert hop.line == 0.0 and not hop.dashed and hop.place is Place.SURFACE
    jump = cue(STEPPED, 0.5, 4.5, 2.0)
    assert jump.line == 2.0 and jump.marker_z == 0.0 and not jump.dashed and not jump.grounded
    under_the_deck = cue(STEPPED, 1.5, 1.5, 1.5)
    assert under_the_deck.marker_z == 0.0, "the deck above is no ground for it"
    over_the_deck = cue(STEPPED, 1.5, 1.5, 4.0)
    assert over_the_deck.marker_z == 2.5 and over_the_deck.line == 1.5


def test_over_the_void_the_marker_is_dashed_on_the_reference_plane() -> None:
    off = cue(STEPPED, 8.0, 3.0, 2.0)
    assert (off.place, off.marker_z, off.dashed, off.line) == (Place.VOID, 0.0, True, 2.0)
    assert not off.through_solid and not off.grounded
    level = cue(STEPPED, 8.0, 3.0, 0.3)
    assert level.dashed and level.line == 0.0, "level with the plane: a ring, no line"
    fallen = cue(STEPPED, 8.0, 3.0, -4.0)
    assert fallen.height == -4.0 and fallen.line == 4.0, "below the plane the line goes up to it"
    beside_the_step = cue(STEPPED, 7.0, 5.5, 1.0)
    assert beside_the_step.marker_z == 0.0, "one plane for the whole stage, not the nearest ledge"


def test_under_the_island_the_marker_is_on_the_ground_above() -> None:
    below = cue(STEPPED, 2.5, 4.5, -5.0)
    assert (below.place, below.marker_z, below.dashed) == (Place.UNDER, 0.0, True)
    assert below.line == 5.0 and below.through_solid
    under_the_step = cue(STEPPED, 4.5, 4.5, -5.0)
    assert under_the_step.marker_z == 1.0 and under_the_step.line == 6.0


def test_a_moving_platform_is_ground_only_where_it_is_now() -> None:
    stage = load_stage("frostpeak")
    resting = stage.soft_platforms[0]
    x, y = (resting.x0 + resting.x1) / 2, (resting.y0 + resting.y1) / 2
    assert cue(stage, x, y, resting.z + 0.5).marker_z == resting.z
    live = stage.at(240)
    moved = live.soft_platforms[0]
    assert moved.x0 != resting.x0, "the floe has drifted"
    out_x = (moved.x0 + moved.x1) / 2
    over = cue(live, out_x, y, moved.z + 0.5)
    assert over.place is Place.SURFACE and over.marker_z == moved.z
    if stage.surface_top(out_x, y) is None:
        gone = cue(stage, out_x, y, moved.z + 0.5)
        assert gone.place is Place.VOID and gone.dashed, "against the resting stage: the void"


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_stage_has_twins_the_marker_tells_apart(stage_id: str) -> None:
    """The case the user reported: standing on the island, and in the air off it, on the
    same pixels. The two must get different markers."""
    stage = load_stage(stage_id)
    pairs = off_stage_twins(stage)
    assert len(pairs) >= 2, "enough pairs for a lab sheet"
    for pair in pairs:
        assert project(*pair.ground) == project(*pair.air)
        on, off = cue(stage, *pair.ground), cue(stage, *pair.air)
        assert on.grounded and not on.dashed and on.line == 0.0
        assert off.place is Place.VOID and off.dashed and off.line >= 2.0
        assert stage.surface_top(pair.air[0], pair.air[1]) is None, "outside the footprint"
        marker_on = project(pair.ground[0], pair.ground[1], on.marker_z)
        marker_off = project(pair.air[0], pair.air[1], off.marker_z)
        assert marker_off[1] <= marker_on[1] - 16 * off.line + 1e-6, (
            "the off-stage marker is drawn well below the feet"
        )


def test_twins_are_spread_across_the_stage() -> None:
    pairs = off_stage_twins(load_stage("sky_ruins"), 4)
    across = [pair.ground[0] - pair.ground[1] for pair in pairs]
    assert len(pairs) == 4 and across == sorted(across) and across[-1] - across[0] >= 6
    assert len(off_stage_twins(load_stage("sky_ruins"), 2)) == 2
