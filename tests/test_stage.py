"""Unit tests for stage geometry and ledge generation (plan notes 04, 06 and 11)."""

import pytest

from isofightr.config import LEDGE_MIN_DROP
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import (
    Cell,
    LedgeLine,
    SoftPlatform,
    Stage,
    StageError,
    build_stage,
    generate_ledges,
)

PLUS_X, MINUS_X, PLUS_Y, MINUS_Y = Vec2(1.0, 0.0), Vec2(-1.0, 0.0), Vec2(0.0, 1.0), Vec2(0.0, -1.0)


def make_stage(
    rows: list[str],
    *,
    legend: dict[str, Cell] | None = None,
    platforms: list[SoftPlatform] | None = None,
    spawns: list[Vec2] | None = None,
    respawn: Vec2 | None = None,
) -> Stage:
    """Build a stage from grid rows; spawns default to the first solid cell's centre."""
    cy, cx = next(
        (y, x) for y, row in enumerate(rows) for x, symbol in enumerate(row) if symbol != "."
    )
    default_spawn = Vec2(cx + 0.5, cy + 0.5)
    return build_stage(
        id="test",
        display_name="Test",
        tileset="grid",
        grid_rows=rows,
        legend=legend or {},
        soft_platforms=platforms or [],
        spawns=spawns or [default_spawn] * 4,
        respawn=respawn or default_spawn,
        blast_side=7.0,
        blast_top=14.0,
        blast_bottom=-8.0,
        camera_margin=4.0,
    )


def ledges_of(rows: list[str], legend: dict[str, Cell] | None = None) -> set[LedgeLine]:
    return set(make_stage(rows, legend=legend).ledges)


# --- grid and queries ---------------------------------------------------------------------


def test_rows_are_world_y_and_columns_are_world_x() -> None:
    stage = make_stage(["01.", "2.."])
    assert (stage.size_x, stage.size_y) == (3, 2)
    assert stage.cell(0, 0) == Cell(top=0.0)
    assert stage.cell(1, 0) == Cell(top=1.0)
    assert stage.cell(0, 1) == Cell(top=2.0)
    assert stage.cell(2, 0) is None
    assert stage.cell(1, 1) is None


def test_out_of_range_cells_are_void() -> None:
    stage = make_stage(["0"])
    for cx, cy in [(-1, 0), (0, -1), (1, 0), (0, 1)]:
        assert stage.cell(cx, cy) is None


def test_cell_lookup_floors_coordinates_so_boundaries_are_deterministic() -> None:
    stage = make_stage(["01"])
    assert stage.surface_top(0.999, 0.5) == 0.0
    assert stage.surface_top(1.0, 0.5) == 1.0
    assert stage.surface_top(2.0, 0.5) is None
    assert stage.surface_top(-0.001, 0.5) is None
    assert stage.surface_top(0.5, 1.0) is None


def test_legend_overrides_digits_and_defines_letters() -> None:
    legend = {"0": Cell(top=0.0, tile="grass"), "R": Cell(top=3.0, tile="stone", ledge=False)}
    stage = make_stage(["0R"], legend=legend)
    assert stage.cell(0, 0) == Cell(top=0.0, tile="grass")
    assert stage.cell(1, 0) == Cell(top=3.0, tile="stone", ledge=False)


def test_bounds_cover_only_solid_cells() -> None:
    stage = make_stage(["....", ".02.", "...."])
    bounds = stage.bounds
    assert (bounds.x_min, bounds.x_max, bounds.y_min, bounds.y_max) == (1.0, 3.0, 1.0, 2.0)
    assert (bounds.z_min, bounds.z_max) == (0.0, 2.0)


def test_blast_zone_is_the_solid_bounds_plus_margins() -> None:
    blast = make_stage(["....", ".00.", "...."]).blast_zone
    assert (blast.x_min, blast.x_max) == (1.0 - 7.0, 3.0 + 7.0)
    assert (blast.y_min, blast.y_max) == (1.0 - 7.0, 2.0 + 7.0)
    assert (blast.z_min, blast.z_max) == (-8.0, 14.0)
    assert blast.contains(Vec3(2.0, 1.5, 0.0))
    assert not blast.contains(Vec3(2.0, 1.5, -8.1))
    assert not blast.contains(Vec3(10.1, 1.5, 0.0))


def test_camera_bounds_reach_above_the_highest_platform() -> None:
    stage = make_stage(["000", "000", "000"], platforms=[SoftPlatform(0, 0, 2, 2, 4.5)])
    camera = stage.camera_bounds
    assert (camera.x_min, camera.x_max) == (-4.0, 7.0)
    assert (camera.z_min, camera.z_max) == (-4.0, 8.5)


def test_spawn_points_stand_on_the_surface() -> None:
    stage = make_stage(
        ["02"], spawns=[Vec2(0.5, 0.5), Vec2(1.5, 0.5)] * 2, respawn=Vec2(1.25, 0.25)
    )
    assert stage.spawn_point(0) == Vec3(0.5, 0.5, 0.0)
    assert stage.spawn_point(1) == Vec3(1.5, 0.5, 2.0)
    assert stage.respawn_point() == Vec3(1.25, 0.25, 2.0)


# --- support_below ------------------------------------------------------------------------


def test_support_below_picks_the_highest_surface_under_the_feet() -> None:
    stage = make_stage(["000", "000", "000"], platforms=[SoftPlatform(0, 0, 2, 2, 2.5)])
    assert stage.support_below(0.5, 0.5, 5.0) == 2.5
    assert stage.support_below(0.5, 0.5, 2.5) == 2.5
    assert stage.support_below(0.5, 0.5, 2.4) == 0.0
    assert stage.support_below(2.5, 2.5, 5.0) == 0.0


def test_support_below_is_none_over_void_and_under_the_surface() -> None:
    stage = make_stage(["0.", ".."], platforms=[SoftPlatform(1, 1, 2, 2, 2.0)])
    assert stage.support_below(1.5, 0.5, 5.0) is None
    assert stage.support_below(0.5, 0.5, -0.5) is None
    assert stage.support_below(1.5, 1.5, 3.0) == 2.0
    assert stage.support_below(1.5, 1.5, 1.0) is None


def test_platform_far_edges_are_exclusive_like_cells() -> None:
    platform = SoftPlatform(2, 2, 5, 5, 2.5)
    assert platform.contains(2.0, 2.0)
    assert platform.contains(4.999, 4.999)
    assert not platform.contains(5.0, 3.0)
    assert not platform.contains(3.0, 1.999)


# --- ledges -------------------------------------------------------------------------------


def test_single_cell_has_four_unit_ledges() -> None:
    assert ledges_of(["0"]) == {
        LedgeLine(Vec2(1.0, 0.0), Vec2(1.0, 1.0), 0.0, PLUS_X),
        LedgeLine(Vec2(0.0, 0.0), Vec2(0.0, 1.0), 0.0, MINUS_X),
        LedgeLine(Vec2(0.0, 1.0), Vec2(1.0, 1.0), 0.0, PLUS_Y),
        LedgeLine(Vec2(0.0, 0.0), Vec2(1.0, 0.0), 0.0, MINUS_Y),
    }


def test_collinear_segments_merge_into_one_line_per_side() -> None:
    ledges = make_stage(["000", "000"]).ledges
    assert set(ledges) == {
        LedgeLine(Vec2(3.0, 0.0), Vec2(3.0, 2.0), 0.0, PLUS_X),
        LedgeLine(Vec2(0.0, 0.0), Vec2(0.0, 2.0), 0.0, MINUS_X),
        LedgeLine(Vec2(0.0, 2.0), Vec2(3.0, 2.0), 0.0, PLUS_Y),
        LedgeLine(Vec2(0.0, 0.0), Vec2(3.0, 0.0), 0.0, MINUS_Y),
    }
    assert sorted(ledge.length for ledge in ledges) == [2.0, 2.0, 3.0, 3.0]


def test_interior_sides_are_not_ledges() -> None:
    for ledge in make_stage(["000", "000", "000"]).ledges:
        fixed = ledge.start.x if ledge.normal.x else ledge.start.y
        assert fixed in (0.0, 3.0)


def test_a_gap_splits_a_ledge_line() -> None:
    minus_y = [ledge for ledge in make_stage(["0.0", "000"]).ledges if ledge.normal == MINUS_Y]
    assert set(minus_y) == {
        LedgeLine(Vec2(0.0, 0.0), Vec2(1.0, 0.0), 0.0, MINUS_Y),
        LedgeLine(Vec2(2.0, 0.0), Vec2(3.0, 0.0), 0.0, MINUS_Y),
        LedgeLine(Vec2(1.0, 1.0), Vec2(2.0, 1.0), 0.0, MINUS_Y),
    }


def test_notch_sides_face_into_the_void() -> None:
    ledges = ledges_of(["0.0", "000"])
    assert LedgeLine(Vec2(1.0, 0.0), Vec2(1.0, 1.0), 0.0, PLUS_X) in ledges
    assert LedgeLine(Vec2(2.0, 0.0), Vec2(2.0, 1.0), 0.0, MINUS_X) in ledges


def test_ledge_normals_point_away_from_the_solid_cell() -> None:
    stage = make_stage(["..000..", ".00000.", "0000000", ".00000.", "..000.."])
    for ledge in stage.ledges:
        middle = (ledge.start + ledge.end) / 2
        inside = middle - ledge.normal * 0.5
        outside = middle + ledge.normal * 0.5
        assert stage.surface_top(inside.x, inside.y) is not None
        assert stage.surface_top(outside.x, outside.y) is None


def test_a_small_step_is_not_a_ledge_but_a_tall_drop_is() -> None:
    assert LEDGE_MIN_DROP == 2.0

    def inner_step(rows: list[str]) -> list[LedgeLine]:
        """Ledges on the +x side of the raised left cell, where it meets the lower one."""
        ledges = make_stage(rows).ledges
        return [ledge for ledge in ledges if ledge.normal == PLUS_X and ledge.start.x == 1.0]

    assert inner_step(["20"]) == []
    assert inner_step(["30"]) == [LedgeLine(Vec2(1.0, 0.0), Vec2(1.0, 1.0), 3.0, PLUS_X)]


def test_lines_at_different_heights_do_not_merge() -> None:
    minus_y = [ledge for ledge in make_stage(["01"]).ledges if ledge.normal == MINUS_Y]
    assert set(minus_y) == {
        LedgeLine(Vec2(0.0, 0.0), Vec2(1.0, 0.0), 0.0, MINUS_Y),
        LedgeLine(Vec2(1.0, 0.0), Vec2(2.0, 0.0), 1.0, MINUS_Y),
    }


def test_cells_can_opt_out_of_ledges() -> None:
    ledges = make_stage(["N0"], legend={"N": Cell(top=0.0, ledge=False)}).ledges
    assert len(ledges) == 3
    assert all(ledge.start.x >= 1.0 and ledge.end.x >= 1.0 for ledge in ledges)


def test_ledge_generation_is_deterministic() -> None:
    rows = ["..000..", ".00000.", "0000000", ".00000.", "..000.."]
    assert make_stage(rows).ledges == make_stage(rows).ledges
    assert generate_ledges(make_stage(rows).cells) == make_stage(rows).ledges


# --- validation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "grid is empty"),
        (["00", "0"], "row 1 has 1 cells, expected 2"),
        (["0?"], "unknown symbol '?'"),
        (["..", ".."], "no solid cells"),
    ],
)
def test_bad_grids_are_rejected(rows: list[str], message: str) -> None:
    with pytest.raises(StageError, match=message.replace("?", r"\?")):
        build_stage(
            id="test",
            display_name="Test",
            tileset="grid",
            grid_rows=rows,
            legend={},
            soft_platforms=[],
            spawns=[Vec2(0.5, 0.5)] * 4,
            respawn=Vec2(0.5, 0.5),
            blast_side=7.0,
            blast_top=14.0,
            blast_bottom=-8.0,
            camera_margin=4.0,
        )


def test_spawn_in_the_void_is_rejected() -> None:
    with pytest.raises(StageError, match=r"spawn p2 at .* is not on solid ground"):
        make_stage(["0."], spawns=[Vec2(0.5, 0.5), Vec2(1.5, 0.5), Vec2(0.5, 0.5), Vec2(0.5, 0.5)])
    with pytest.raises(StageError, match="spawn respawn"):
        make_stage(["0."], respawn=Vec2(1.5, 0.5))


def test_wrong_spawn_count_is_rejected() -> None:
    with pytest.raises(StageError, match="expected 4 spawns, got 2"):
        make_stage(["0"], spawns=[Vec2(0.5, 0.5)] * 2)


@pytest.mark.parametrize(
    ("platform", "message"),
    [
        (SoftPlatform(2, 0, 2, 1, 3.0), "x0 < x1"),
        (SoftPlatform(0, 0, 4, 1, 3.0), "outside the grid"),
        (SoftPlatform(0, 0, 1, 1, 0.5), "less than 1.0 above"),
    ],
)
def test_bad_platforms_are_rejected(platform: SoftPlatform, message: str) -> None:
    with pytest.raises(StageError, match=message):
        make_stage(["000"], platforms=[platform])


def test_blast_zone_must_enclose_the_stage() -> None:
    with pytest.raises(StageError, match="blast zone"):
        build_stage(
            id="test",
            display_name="Test",
            tileset="grid",
            grid_rows=["9"],
            legend={},
            soft_platforms=[],
            spawns=[Vec2(0.5, 0.5)] * 4,
            respawn=Vec2(0.5, 0.5),
            blast_side=7.0,
            blast_top=5.0,
            blast_bottom=-8.0,
            camera_margin=4.0,
        )
