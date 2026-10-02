"""Unit tests for the world draw order (plan note 03, "Depth sorting rules").

Each test places dynamic items on a small stage and checks what is painted before what.
"""

import itertools

import pytest

from isofightr.config import DECK_THICKNESS, ISLAND_THICKNESS
from isofightr.render.depth import (
    DepthSorter,
    DrawEntry,
    DynamicItem,
    ScreenRect,
    StaticKind,
    cell_block_rect,
    sprite_rect,
)
from isofightr.sim.math3d import Vec2
from isofightr.sim.stage import SoftPlatform, Stage, build_stage

BODY, SHADOW = 1, 0
BODY_HEIGHT = 2.5


def make_stage(rows: list[str], platforms: list[SoftPlatform] | None = None) -> Stage:
    cy, cx = next((y, x) for y, row in enumerate(rows) for x, s in enumerate(row) if s != ".")
    spawn = Vec2(cx + 0.5, cy + 0.5)
    return build_stage(
        id="test",
        display_name="Test",
        tileset="grid",
        grid_rows=rows,
        legend={},
        soft_platforms=platforms or [],
        spawns=[spawn] * 4,
        respawn=spawn,
        blast_side=7.0,
        blast_top=14.0,
        blast_bottom=-8.0,
        camera_margin=4.0,
    )


FLAT = make_stage(["00000"] * 5)
DECKED = make_stage(["0000000"] * 7, [SoftPlatform(2, 2, 5, 5, 2.5)])
TWO_ISLES = make_stage(["00...00"] * 4)


def body(item_id: int, x: float, y: float, z: float) -> DynamicItem:
    """A fighter-sized dynamic item: 20 px wide, 40 px (2.5 units) tall, feet at the position."""
    return DynamicItem(item_id, BODY, x, y, z, BODY_HEIGHT, sprite_rect(x, y, z, 10, 0, 40))


def shadow(item_id: int, x: float, y: float, z: float) -> DynamicItem:
    return DynamicItem(item_id, SHADOW, x, y, z, 0.0, sprite_rect(x, y, z, 10, 5, 5))


def index_of(sorter: DepthSorter, kind: StaticKind, cx: int, cy: int) -> int:
    return next(
        index
        for index, item in enumerate(sorter.statics)
        if (item.kind, item.cx, item.cy) == (kind, cx, cy)
    )


def drawn_before(order: list[DrawEntry], first: DrawEntry, second: DrawEntry) -> bool:
    return order.index(first) < order.index(second)


def static(sorter: DepthSorter, kind: StaticKind, cx: int, cy: int) -> DrawEntry:
    return DrawEntry(True, index_of(sorter, kind, cx, cy))


def dynamic(item_id: int) -> DrawEntry:
    return DrawEntry(False, item_id)


def overlapping(sorter: DepthSorter, item: DynamicItem) -> list[DrawEntry]:
    return [
        DrawEntry(True, index)
        for index, other in enumerate(sorter.statics)
        if other.rect.overlaps(item.rect)
    ]


# --- static order -------------------------------------------------------------------------


def test_stage_alone_draws_every_static_once() -> None:
    sorter = DepthSorter(DECKED)
    order = sorter.draw_order([])
    assert all(entry.is_static for entry in order)
    assert sorted(entry.index for entry in order) == list(range(len(sorter.statics)))
    kinds = [item.kind for item in sorter.statics]
    assert (kinds.count(StaticKind.COLUMN), kinds.count(StaticKind.DECK)) == (49, 9)
    assert kinds.count(StaticKind.DECAL) == 9


def test_columns_are_drawn_back_to_front() -> None:
    sorter = DepthSorter(FLAT)
    order = sorter.draw_order([])
    for cx, cy in itertools.product(range(4), range(5)):
        behind, in_front = (StaticKind.COLUMN, cx, cy), (StaticKind.COLUMN, cx + 1, cy)
        assert drawn_before(order, static(sorter, *behind), static(sorter, *in_front))
    for cx, cy in itertools.product(range(5), range(4)):
        behind, in_front = (StaticKind.COLUMN, cx, cy), (StaticKind.COLUMN, cx, cy + 1)
        assert drawn_before(order, static(sorter, *behind), static(sorter, *in_front))


def test_platform_shadow_decal_is_drawn_on_its_column_and_under_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    order = sorter.draw_order([])
    for cx, cy in itertools.product(range(2, 5), range(2, 5)):
        column = static(sorter, StaticKind.COLUMN, cx, cy)
        decal = static(sorter, StaticKind.DECAL, cx, cy)
        assert drawn_before(order, column, decal)
    # The front column of a shadowed pair repaints the shared edge row before its own decal.
    assert drawn_before(
        order, static(sorter, StaticKind.DECAL, 2, 2), static(sorter, StaticKind.COLUMN, 3, 2)
    )


def test_no_decal_where_there_is_no_ground_under_the_platform() -> None:
    stage = make_stage(["00.", "00.", "..."], [SoftPlatform(1, 1, 3, 3, 2.5)])
    decals = [item for item in DepthSorter(stage).statics if item.kind is StaticKind.DECAL]
    assert [(item.cx, item.cy) for item in decals] == [(1, 1)]


def test_a_deck_is_drawn_after_lower_ground_even_in_front_of_it() -> None:
    sorter = DepthSorter(DECKED)
    order = sorter.draw_order([])
    deck = static(sorter, StaticKind.DECK, 2, 2)
    for entry in overlapping_statics(sorter, deck.index):
        if sorter.statics[entry.index].kind is not StaticKind.DECK:
            assert drawn_before(order, entry, deck)


def test_a_tall_block_in_front_of_a_deck_is_drawn_after_it() -> None:
    stage = make_stage(["0000", "0000", "0050", "0000"], [SoftPlatform(0, 0, 2, 2, 2.5)])
    sorter = DepthSorter(stage)
    order = sorter.draw_order([])
    block = static(sorter, StaticKind.COLUMN, 2, 2)
    deck = static(sorter, StaticKind.DECK, 1, 1)
    assert sorter.statics[block.index].rect.overlaps(sorter.statics[deck.index].rect)
    assert drawn_before(order, deck, block)


def overlapping_statics(sorter: DepthSorter, index: int) -> list[DrawEntry]:
    rect = sorter.statics[index].rect
    return [
        DrawEntry(True, other)
        for other, item in enumerate(sorter.statics)
        if other != index and item.rect.overlaps(rect)
    ]


def test_static_rects_match_the_sprite_geometry() -> None:
    assert cell_block_rect(0, 0, -ISLAND_THICKNESS, 0.0) == ScreenRect(-16.0, -32.0, 16.0, 0.0)
    assert cell_block_rect(2, 1, 0.0, 0.0) == ScreenRect(0.0, -40.0, 32.0, -24.0)
    deck = cell_block_rect(0, 0, 2.5 - DECK_THICKNESS, 2.5)
    assert deck == ScreenRect(-16.0, 20.0, 16.0, 40.0)


# --- a single fighter against the stage ---------------------------------------------------


@pytest.mark.parametrize("position", [(0.5, 0.5), (2.5, 2.5), (4.9, 4.9), (0.1, 4.9)])
def test_standing_on_the_ground_is_drawn_after_all_ground(position: tuple[float, float]) -> None:
    sorter = DepthSorter(FLAT)
    assert sorter.draw_order([body(1, *position, 0.0)])[-1] == dynamic(1)


@pytest.mark.parametrize(
    ("position", "hidden_by", "drawn_over"),
    [
        # Fell off the far (north-west, -x) edge: hidden by the island in front of it.
        ((-0.4, 2.5), (0, 2), None),
        # Fell off the far (north-east, -y) edge.
        ((2.5, -0.4), (2, 0), None),
        # Fell off the near (south-east, +x) edge: in front of the island's side face.
        ((5.4, 2.5), None, (4, 2)),
        # Fell off the near (south-west, +y) edge.
        ((2.5, 5.4), None, (2, 4)),
    ],
)
def test_below_the_surface_at_each_edge(
    position: tuple[float, float],
    hidden_by: tuple[int, int] | None,
    drawn_over: tuple[int, int] | None,
) -> None:
    sorter = DepthSorter(FLAT)
    order = sorter.draw_order([body(1, *position, -1.0)])
    if hidden_by is not None:
        assert drawn_before(order, dynamic(1), static(sorter, StaticKind.COLUMN, *hidden_by))
    if drawn_over is not None:
        assert drawn_before(order, static(sorter, StaticKind.COLUMN, *drawn_over), dynamic(1))


def test_below_the_far_corner_is_hidden_by_every_column_it_overlaps() -> None:
    sorter = DepthSorter(FLAT)
    fighter = body(1, -0.5, -0.5, -1.0)
    order = sorter.draw_order([fighter])
    columns = overlapping(sorter, fighter)
    assert columns, "the fighter sprite should overlap the back corner of the island"
    assert all(drawn_before(order, dynamic(1), column) for column in columns)


def test_in_the_void_above_floor_level_behind_the_island_is_drawn_after_it() -> None:
    sorter = DepthSorter(FLAT)
    assert sorter.draw_order([body(1, -0.5, 2.5, 0.0)])[-1] == dynamic(1)


def test_under_a_platform_is_drawn_after_the_ground_and_before_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    fighter = body(1, 3.5, 3.5, 0.0)
    order = sorter.draw_order([fighter])
    assert drawn_before(order, static(sorter, StaticKind.COLUMN, 3, 3), dynamic(1))
    assert drawn_before(order, static(sorter, StaticKind.DECAL, 3, 3), dynamic(1))
    for cx, cy in [(3, 3), (4, 3), (3, 4), (4, 4)]:
        assert drawn_before(order, dynamic(1), static(sorter, StaticKind.DECK, cx, cy))


def test_under_a_platform_near_a_cell_boundary_is_still_drawn_after_the_ground() -> None:
    """The feet hang over the next ground cells, which must not be painted over them even
    though the deck cell above comes earlier in the default order."""
    sorter = DepthSorter(DECKED)
    fighter = body(1, 3.95, 3.5, 0.0)
    order = sorter.draw_order([fighter])
    neighbour = static(sorter, StaticKind.COLUMN, 4, 3)
    assert sorter.statics[neighbour.index].rect.overlaps(fighter.rect)
    assert drawn_before(order, neighbour, dynamic(1))
    assert drawn_before(order, static(sorter, StaticKind.DECAL, 4, 3), dynamic(1))
    assert drawn_before(order, dynamic(1), static(sorter, StaticKind.DECK, 3, 3))
    assert drawn_before(order, dynamic(1), static(sorter, StaticKind.DECK, 4, 3))


def test_standing_on_a_platform_is_drawn_after_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    assert sorter.draw_order([body(1, 3.5, 3.5, 2.5)])[-1] == dynamic(1)


def test_in_front_of_a_platform_is_drawn_after_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    # Just beyond the +x edge and the +y edge of the deck, on the ground.
    for position in [(5.3, 3.5), (3.5, 5.3), (5.3, 5.3)]:
        assert sorter.draw_order([body(1, *position, 0.0)])[-1] == dynamic(1)


def test_behind_a_platform_is_hidden_by_the_deck_cells_in_front() -> None:
    sorter = DepthSorter(DECKED)
    # On the ground just beyond the -x edge: the deck is between the fighter and the camera.
    fighter = body(1, 1.7, 4.5, 0.0)
    order = sorter.draw_order([fighter])
    deck_cell = static(sorter, StaticKind.DECK, 2, 4)
    assert sorter.statics[deck_cell.index].rect.overlaps(fighter.rect)
    assert drawn_before(order, dynamic(1), deck_cell)
    assert drawn_before(order, static(sorter, StaticKind.COLUMN, 2, 4), dynamic(1))


def test_jumping_through_a_platform_switches_as_the_feet_clear_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    deck = static(sorter, StaticKind.DECK, 3, 3)
    assert drawn_before(sorter.draw_order([body(1, 3.5, 3.5, 2.4)]), dynamic(1), deck)
    assert drawn_before(sorter.draw_order([body(1, 3.5, 3.5, 2.5)]), deck, dynamic(1))


def test_head_above_a_deck_behind_the_fighter_is_drawn_over_that_deck() -> None:
    """In front of a low platform, with a taller block further in front: the deck must come
    before the fighter and the block after it. A fixed "decks last" order cannot do this."""
    stage = make_stage(["00000"] * 4 + ["00003"], [SoftPlatform(0, 0, 2, 2, 1.5)])
    sorter = DepthSorter(stage)
    fighter = body(1, 2.3, 2.3, 0.0)
    order = sorter.draw_order([fighter])
    deck, block = static(sorter, StaticKind.DECK, 1, 1), static(sorter, StaticKind.COLUMN, 4, 4)
    assert sorter.statics[deck.index].rect.overlaps(fighter.rect)
    assert sorter.statics[block.index].rect.overlaps(fighter.rect)
    assert drawn_before(order, deck, dynamic(1))
    assert drawn_before(order, dynamic(1), block)


def test_things_that_do_not_overlap_the_sprite_add_no_constraint() -> None:
    stage = make_stage(["0000000", "0000000", "0000000", "0000003"])
    sorter = DepthSorter(stage)
    # A tall block far to the front-right does not overlap the fighter's sprite.
    assert sorter.draw_order([body(1, 0.5, 0.5, 0.0)])[-1] == dynamic(1)


def test_a_raised_block_in_front_hides_and_behind_does_not() -> None:
    stage = make_stage(["000", "020", "000"])
    sorter = DepthSorter(stage)
    block = static(sorter, StaticKind.COLUMN, 1, 1)
    behind = sorter.draw_order([body(1, 0.7, 1.5, 0.0)])
    assert drawn_before(behind, dynamic(1), block)
    assert drawn_before(behind, static(sorter, StaticKind.COLUMN, 0, 1), dynamic(1))
    in_front = sorter.draw_order([body(1, 2.3, 1.5, 0.0)])
    assert drawn_before(in_front, block, dynamic(1))
    on_top = sorter.draw_order([body(1, 1.5, 1.5, 2.0)])
    assert drawn_before(on_top, block, dynamic(1))


# --- fighters against each other ----------------------------------------------------------


def test_two_fighters_on_the_ground_sort_by_depth_key() -> None:
    sorter = DepthSorter(FLAT)
    order = sorter.draw_order([body(1, 3.0, 3.0, 0.0), body(2, 2.6, 2.6, 0.0)])
    assert drawn_before(order, dynamic(2), dynamic(1))


def test_equal_depth_breaks_ties_by_height_then_id() -> None:
    sorter = DepthSorter(FLAT)
    order = sorter.draw_order([body(1, 2.5, 2.5, 1.0), body(2, 2.5, 2.5, 0.0)])
    assert drawn_before(order, dynamic(2), dynamic(1))
    order = sorter.draw_order([body(2, 2.5, 2.5, 0.0), body(1, 2.5, 2.5, 0.0)])
    assert drawn_before(order, dynamic(1), dynamic(2))


def test_hanging_below_the_near_edge_is_in_front_of_a_fighter_standing_above() -> None:
    sorter = DepthSorter(FLAT)
    standing, hanging = body(1, 4.8, 2.5, 0.0), body(2, 5.35, 2.5, -1.8)
    assert standing.rect.overlaps(hanging.rect)
    order = sorter.draw_order([standing, hanging])
    assert drawn_before(order, dynamic(1), dynamic(2))


def test_hanging_below_the_far_edge_is_behind_a_fighter_standing_above() -> None:
    sorter = DepthSorter(FLAT)
    standing, hanging = body(1, 0.2, 2.5, 0.0), body(2, -0.35, 2.5, -1.8)
    order = sorter.draw_order([standing, hanging])
    assert drawn_before(order, dynamic(2), dynamic(1))
    assert drawn_before(order, dynamic(2), static(sorter, StaticKind.COLUMN, 0, 2))


def test_off_stage_behind_the_island_overlapping_fighters_keep_depth_order() -> None:
    """One fighter below floor level is hidden by the island; another above floor level is
    not. Where their sprites overlap, the nearer one must still be on top."""
    sorter = DepthSorter(FLAT)
    low_near, high_far = body(1, -0.4, 2.6, -1.0), body(2, -0.8, 2.4, 0.2)
    assert low_near.rect.overlaps(high_far.rect)
    assert low_near.key > high_far.key
    order = sorter.draw_order([low_near, high_far])
    assert drawn_before(order, dynamic(2), dynamic(1))


def test_in_a_gap_between_islands_the_nearer_fighter_stays_on_top() -> None:
    sorter = DepthSorter(TWO_ISLES)
    on_far_island_edge, hanging_in_gap = body(1, 1.8, 1.5, 0.0), body(2, 2.35, 1.5, -1.8)
    assert on_far_island_edge.rect.overlaps(hanging_in_gap.rect)
    order = sorter.draw_order([on_far_island_edge, hanging_in_gap])
    assert drawn_before(order, dynamic(1), dynamic(2))
    # ...and the standing fighter is still drawn after the ground it stands on.
    assert drawn_before(order, static(sorter, StaticKind.COLUMN, 1, 1), dynamic(1))


def test_fighter_on_a_platform_and_one_under_it_do_not_constrain_each_other() -> None:
    sorter = DepthSorter(DECKED)
    on_deck, under_deck = body(1, 3.3, 3.3, 2.5), body(2, 3.6, 3.6, 0.0)
    order = sorter.draw_order([on_deck, under_deck])
    deck = static(sorter, StaticKind.DECK, 3, 3)
    assert drawn_before(order, dynamic(2), deck)
    assert drawn_before(order, deck, dynamic(1))


# --- shadows ------------------------------------------------------------------------------


def test_shadow_is_drawn_after_its_surface_and_before_its_fighter() -> None:
    sorter = DepthSorter(FLAT)
    order = sorter.draw_order([body(1, 2.5, 2.5, 0.0), shadow(2, 2.5, 2.5, 0.0)])
    assert drawn_before(order, static(sorter, StaticKind.COLUMN, 2, 2), dynamic(2))
    assert drawn_before(order, dynamic(2), dynamic(1))


def test_a_ground_shadow_never_paints_over_a_fighter_standing_on_that_ground() -> None:
    sorter = DepthSorter(FLAT)
    # The shadow's centre is nearer the camera than the other fighter's feet, yet a fighter
    # standing on the same ground is entirely above it.
    fighter, other_shadow = body(1, 2.5, 2.5, 0.0), shadow(2, 2.7, 2.7, 0.0)
    assert other_shadow.key > fighter.key
    assert fighter.rect.overlaps(other_shadow.rect)
    order = sorter.draw_order([fighter, other_shadow])
    assert drawn_before(order, dynamic(2), dynamic(1))


def test_shadow_under_a_platform_is_hidden_by_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    # A deck 2.5 units up appears 40 px higher on screen, so the part of it that covers a
    # ground shadow at the back of the platform is the deck's front cell.
    ground_shadow = shadow(2, 2.3, 2.3, 0.0)
    front_deck_cell = static(sorter, StaticKind.DECK, 4, 4)
    assert sorter.statics[front_deck_cell.index].rect.overlaps(ground_shadow.rect)
    order = sorter.draw_order([ground_shadow])
    assert drawn_before(order, static(sorter, StaticKind.DECAL, 2, 2), dynamic(2))
    assert drawn_before(order, dynamic(2), front_deck_cell)


def test_shadow_on_a_platform_is_drawn_after_the_deck() -> None:
    sorter = DepthSorter(DECKED)
    deck_shadow = shadow(2, 3.5, 3.5, 2.5)
    order = sorter.draw_order([deck_shadow, body(1, 3.5, 3.5, 2.5)])
    for entry in overlapping(sorter, deck_shadow):
        assert drawn_before(order, entry, dynamic(2))
    assert drawn_before(order, dynamic(2), dynamic(1))


def test_shadow_on_a_platform_is_drawn_over_a_fighter_under_the_platform() -> None:
    sorter = DepthSorter(DECKED)
    under_deck, deck_shadow = body(1, 3.4, 3.4, 0.0), shadow(2, 3.5, 3.5, 2.5)
    assert under_deck.rect.overlaps(deck_shadow.rect)
    order = sorter.draw_order([under_deck, deck_shadow])
    assert drawn_before(order, dynamic(1), dynamic(2))


# --- determinism and structure ------------------------------------------------------------


def test_draw_order_contains_everything_exactly_once() -> None:
    sorter = DepthSorter(DECKED)
    items = [body(1, 3.5, 3.5, 0.0), body(2, -0.5, 3.0, -1.0), shadow(3, 3.5, 3.5, 0.0)]
    order = sorter.draw_order(items)
    assert len(order) == len(sorter.statics) + len(items)
    assert sorted(entry.index for entry in order if entry.is_static) == list(
        range(len(sorter.statics))
    )
    assert sorted(entry.index for entry in order if not entry.is_static) == [1, 2, 3]


def test_order_does_not_depend_on_input_order() -> None:
    sorter = DepthSorter(DECKED)
    items = [
        body(1, 3.5, 3.5, 0.0),
        body(2, 3.3, 3.3, 2.5),
        body(3, -0.5, 3.0, -1.0),
        shadow(4, 3.5, 3.5, 0.0),
        shadow(5, 3.3, 3.3, 2.5),
    ]
    expected = sorter.draw_order(items)
    for permutation in itertools.permutations(items):
        assert sorter.draw_order(list(permutation)) == expected


def test_same_constraints_reuse_the_cached_order_and_new_ones_do_not() -> None:
    sorter = DepthSorter(FLAT)
    first = sorter.draw_order([body(1, 2.5, 2.5, 0.0)])
    assert sorter.draw_order([body(1, 2.51, 2.5, 0.0)]) == first
    moved = sorter.draw_order([body(1, -0.5, 2.5, -1.0)])
    assert moved != first
    assert sorter.draw_order([body(1, 2.5, 2.5, 0.0)]) == first


def test_a_cycle_still_yields_a_complete_order() -> None:
    """Passing through a deck while another fighter stands on it can make the constraints
    cyclic. The order must still contain everything, and be deterministic."""
    sorter = DepthSorter(DECKED)
    items = [body(1, 3.5, 3.5, 1.5), body(2, 3.45, 3.45, 2.5), shadow(3, 3.45, 3.45, 2.5)]
    order = sorter.draw_order(items)
    assert len(order) == len(sorter.statics) + len(items)
    assert sorter.draw_order(list(reversed(items))) == order
