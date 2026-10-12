"""Stage art systems (decision D-063, M14 group 1): tile variants and rims, props, the mass
under an island, ambient sprites, animated backdrop layers and the stage-name intro.

Pure: no window. What the renderer draws with them is in ``tests/test_stage_decor_gl.py``.
"""

from pathlib import Path

import pytest
from PIL import Image

from isofightr.art.palettes import ART_SRC, load_master
from isofightr.art.tileset import pack_prop, source_hash
from isofightr.config import AMBIENT_KINDS, AMBIENT_MAX, NATIVE_H, NATIVE_W, TILE_H, Z_PX
from isofightr.data.stage_loader import list_stage_ids, load_stage, parse_stage
from isofightr.data.tileset_art import load_tileset_art, variant_index
from isofightr.data.validation import DataError
from isofightr.render import ambient
from isofightr.render import placeholder_art as art
from isofightr.render.depth import DepthSorter, DynamicItem, StaticKind
from isofightr.render.props import PROP_ITEM_BASE, ground_props, placed_props
from isofightr.render.stage_art import (
    EDGE_FOOT,
    EDGE_NONE,
    EDGE_RIM,
    NO_EDGES,
    StageArt,
    cell_edges,
    tile_variant,
)
from isofightr.render.underside import hanging, lowest_point, rim_distances, under_depths
from isofightr.sim.stage import Ambient, Stage
from isofightr.ui import hud_layout

GRASS_STONE = load_tileset_art("grass_stone")
MASTER = load_master("resurrect64")
SQUARE = "\n".join(["0000000"] * 7)


def build(grid: str = SQUARE, **extra: object) -> Stage:
    rows = [row for row in grid.strip().splitlines() if row]
    width, depth = len(rows[0]), len(rows)
    data: dict[str, object] = {
        "id": "test",
        "display_name": "Test",
        "tileset": "grass_stone",
        "grid": "\n".join(rows),
        "legend": {"0": {"height": 0, "tile": "grass"}, "2": {"height": 2, "tile": "stone"}},
        "spawns": {
            "p1": [0.5, 0.5],
            "p2": [width - 0.5, 0.5],
            "p3": [0.5, depth - 0.5],
            "p4": [width - 0.5, depth - 0.5],
            "respawn": [0.5, 0.5],
        },
        **extra,
    }
    return parse_stage(data, source="test")


def colours(image: Image.Image) -> set[tuple[int, int, int]]:
    return {pixel[:3] for pixel in image.convert("RGBA").getdata() if pixel[3]}


# --- variants ------------------------------------------------------------------------------


def test_variant_choice_is_a_fixed_function_of_the_cell() -> None:
    first = [[variant_index(cx, cy, 4) for cx in range(13)] for cy in range(9)]
    again = [[variant_index(cx, cy, 4) for cx in range(13)] for cy in range(9)]
    assert first == again, "the same every time"
    flat = [value for row in first for value in row]
    assert set(flat) == {0, 1, 2, 3}, "every variant appears on a Sky Ruins sized floor"
    assert max(flat.count(value) for value in range(4)) < len(flat) * 0.45, "none dominates"
    assert all(variant_index(cx, cy, 1) == 0 for cx in range(5) for cy in range(5))
    assert variant_index(3, 4, 0) == 0
    rows_alike = sum(first[cy] == first[cy + 1] for cy in range(8))
    assert rows_alike == 0, "no two rows repeat, so the floor does not read as stripes"


def test_the_tileset_has_variants_and_transitions() -> None:
    assert GRASS_STONE is not None
    assert GRASS_STONE.variants("grass") == ("grass", "grass_b", "grass_c", "grass_d")
    assert len(GRASS_STONE.variants("stone")) == 4 and len(GRASS_STONE.variants("deck")) == 2
    assert len(GRASS_STONE.variants("under")) == 2
    assert GRASS_STONE.variants("path") == ("path",) and GRASS_STONE.variants("mossy") == ("mossy",)
    assert GRASS_STONE.variants("lava") == ()
    assert tile_variant(GRASS_STONE, "grass", 3, 5) == variant_index(3, 5, 4)
    stage_art = StageArt(GRASS_STONE)
    pictures = {
        stage_art.tile("grass", True, 16, variant).tobytes()  # type: ignore[union-attr]
        for variant in range(4)
    }
    assert len(pictures) == 4, "the variants are different pictures"
    wrapped = stage_art.tile("grass", True, 16, 5)
    assert wrapped is stage_art.tile("grass", True, 16, 5), "cached"
    assert wrapped.tobytes() == stage_art.tile("grass", True, 16, 1).tobytes()  # type: ignore[union-attr]


@pytest.mark.parametrize("tile", ["grass", "stone", "path", "mossy", "under"])
def test_every_variant_and_rim_keeps_the_block_shape_and_the_palette(tile: str) -> None:
    assert GRASS_STONE is not None
    stage_art = StageArt(GRASS_STONE)
    shape = art.build_block(art.tile_palette(tile), True, 32).getchannel("A")
    edges = (EDGE_RIM, EDGE_FOOT, EDGE_RIM, EDGE_NONE)
    for variant in range(len(GRASS_STONE.variants(tile))):
        for marks in (NO_EDGES, edges):
            image = stage_art.tile(tile, True, 32, variant, marks)
            assert image is not None
            drawn = image.getchannel("A").point(lambda a: 255 * (a > 0))
            assert list(drawn.getdata()) == list(shape.getdata()), "the silhouette (D-019)"
            assert colours(image) <= MASTER


def test_a_rim_brightens_and_a_foot_darkens_only_the_top_edge() -> None:
    assert GRASS_STONE is not None
    stage_art = StageArt(GRASS_STONE)
    plain = stage_art.tile("grass", True, 32)
    rim = stage_art.tile("grass", True, 32, 0, (EDGE_RIM, EDGE_RIM, EDGE_RIM, EDGE_RIM))
    foot = stage_art.tile("grass", True, 32, 0, (EDGE_FOOT, EDGE_FOOT, EDGE_FOOT, EDGE_FOOT))
    assert plain is not None and rim is not None and foot is not None

    def light(image: Image.Image) -> int:
        return sum(sum(pixel[:3]) for pixel in image.getdata() if pixel[3])

    assert light(foot) < light(plain) < light(rim)
    below = (0, TILE_H + 2, 32, TILE_H + 32)
    assert rim.crop(below).tobytes() == plain.crop(below).tobytes(), "the sides are untouched"
    middle = (12, 6, 20, 10)
    assert rim.crop(middle).tobytes() == plain.crop(middle).tobytes(), "and the top's middle"


def test_edges_come_from_the_neighbours() -> None:
    stage = build("\n".join(["0000", "0200", "00.0", "0000"]))
    assert cell_edges(stage, 0, 0) == (EDGE_RIM, EDGE_NONE, EDGE_RIM, EDGE_NONE)
    assert cell_edges(stage, 1, 0) == (EDGE_NONE, EDGE_NONE, EDGE_RIM, EDGE_FOOT), "under a wall"
    assert cell_edges(stage, 1, 1) == (EDGE_RIM, EDGE_RIM, EDGE_RIM, EDGE_RIM), "the high cell"
    assert cell_edges(stage, 1, 2) == (EDGE_NONE, EDGE_RIM, EDGE_FOOT, EDGE_NONE)
    assert cell_edges(stage, 2, 2) == NO_EDGES, "the void has none"


# --- props ---------------------------------------------------------------------------------


def test_the_tileset_has_props_with_frames_and_a_standing_point() -> None:
    assert GRASS_STONE is not None
    assert {"bush", "column", "flowers", "pennant", "roots", "sapling"} <= set(
        GRASS_STONE.prop_names
    )
    stage_art = StageArt(GRASS_STONE)
    for prop in GRASS_STONE.props:
        strip = Image.open(GRASS_STONE.prop_path(prop.name))
        assert strip.mode == "P" and strip.size == (prop.width * prop.frames, prop.height)
        assert 0 <= prop.pivot_x <= prop.width and 0 <= prop.pivot_y <= prop.height
        for frame in range(prop.frames):
            image = stage_art.prop(prop.name, frame)
            assert image.size == (prop.width, prop.height) and colours(image) <= MASTER
    assert GRASS_STONE.prop("flowers").frames == 2  # type: ignore[union-attr]
    assert GRASS_STONE.prop("pennant").frames == 3  # type: ignore[union-attr]
    assert GRASS_STONE.prop("anvil") is None
    with pytest.raises(KeyError):
        stage_art.prop("anvil", 0)
    roots = GRASS_STONE.prop("roots")
    column = GRASS_STONE.prop("column")
    assert roots is not None and column is not None
    assert roots.pivot_y < roots.height / 3, "roots hang below their point"
    assert column.pivot_y > column.height * 2 / 3, "a column stands on its point"


def test_the_committed_tileset_matches_its_sources() -> None:
    assert GRASS_STONE is not None
    assert GRASS_STONE.source == source_hash(ART_SRC / "tilesets" / "grass_stone"), (
        "art_src/tilesets/grass_stone changed: run tools/build_art.py grass_stone and commit"
    )
    sources = {path.stem for path in (ART_SRC / "tilesets/grass_stone/anims").glob("*.toml")}
    assert set(GRASS_STONE.tiles) == sources
    props = {path.stem for path in (ART_SRC / "tilesets/grass_stone/props").glob("*.toml")}
    assert set(GRASS_STONE.prop_names) == props


def test_packing_a_prop_cuts_every_frame_to_the_same_box() -> None:
    first, second = Image.new("L", (128, 224)), Image.new("L", (128, 224))
    first.paste(7, (60, 130, 70, 144))
    second.paste(7, (64, 126, 76, 150))
    strip, entry = pack_prop([first, second])
    assert entry == {"frames": 2, "size": [16, 24], "pivot": [4, 18]}
    assert strip.size == (32, 24)
    with pytest.raises(ValueError, match="draws nothing"):
        pack_prop([Image.new("L", (128, 224))])


PROPS = [
    {"sprite": "column", "at": [3.5, 0.5]},
    {"sprite": "flowers", "at": [2.5, 5.5], "period": 10, "phase": 3},
    {"sprite": "roots", "at": [6.5, 6.5], "layer": "below"},
]


def test_props_load_and_are_placed_on_and_under_the_island() -> None:
    assert GRASS_STONE is not None
    stage = build(props=PROPS, underside={"depth": 2.0})
    assert [prop.sprite for prop in stage.props] == ["column", "flowers", "roots"]
    assert stage.props[1].period == 10 and stage.props[2].layer == "below"
    column, flowers, roots = placed_props(stage, GRASS_STONE)
    assert column.z == 0.0 and not column.below
    item = column.item
    assert item.item_id == PROP_ITEM_BASE and item.fixed and item.z == 0.0
    assert item.height == pytest.approx(column.art.pivot_y / Z_PX)
    rect = column.rect
    assert (rect.right - rect.left, rect.top - rect.bottom) == (column.art.width, column.art.height)
    depth = under_depths(stage)[(6, 6)]
    assert roots.below and roots.z == pytest.approx(stage.underside - depth)
    hung = roots.item
    assert hung.z + hung.height == pytest.approx(roots.z), "it reaches down from its point"
    assert [flowers.frame(tick) for tick in (0, 6, 7, 16, 17, 27)] == [0, 0, 1, 1, 0, 1]
    assert column.frame(99) == 0, "one frame"
    assert placed_props(stage, None) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"props": [{"sprite": "anvil", "at": [1.5, 1.5]}]}, "has no prop 'anvil'"),
        ({"props": [{"sprite": "bush", "at": [40.0, 1.5]}]}, "not over solid ground"),
        ({"props": [{"sprite": "bush", "at": [1.5, 1.5], "layer": "sky"}]}, "layer must be"),
        ({"props": [{"sprite": "bush", "at": [1.5, 1.5], "glow": 1}]}, "unknown key"),
        ({"props": [{"sprite": "bush", "at": [1.5, 1.5], "period": -2}]}, "0 or more"),
        ({"underside": {"depth": 2.0, "hang": ["anvil"]}}, "has no prop 'anvil'"),
        ({"underside": {"depth": 0.0}}, "depth must be"),
        ({"underside": {"depth": 9.0}}, "depth must be"),
        ({"underside": {"depth": 2.0, "hang": "roots"}}, "list of prop names"),
        ({"ambient": {"kind": "bees", "count": 4}}, "kind must be one of"),
        ({"ambient": {"kind": "snow", "count": AMBIENT_MAX + 1}}, f"1 to {AMBIENT_MAX}"),
        ({"ambient": {"kind": "snow", "count": 0}}, f"1 to {AMBIENT_MAX}"),
        ({"ambient": {"kind": "snow", "count": 4, "front": 5}}, "between 0 and count"),
        ({"ambient": {"kind": "snow", "count": 4, "speed": 2}}, "unknown key"),
        (
            {"background": [{"image": "a.png", "parallax": 0.1, "frames": 0}]},
            "frames must be 1 or more",
        ),
        ({"background": [{"image": "a.png", "parallax": 0.1, "wobble": 1}]}, "unknown key"),
    ],
)
def test_bad_decor_is_refused(change: dict[str, object], message: str) -> None:
    with pytest.raises(DataError, match=message):
        build(**change)


def test_props_on_a_tileset_without_art_are_refused() -> None:
    with pytest.raises(DataError, match="has no prop 'bush'"):
        build(tileset="grid", props=[{"sprite": "bush", "at": [1.5, 1.5]}])


def test_backdrop_layers_take_a_drift_and_frames() -> None:
    stage = build(
        background=[
            {"image": "a.png", "parallax": 0.1},
            {"image": "b.png", "parallax": 0.2, "scroll": 0.05, "frames": 3, "frame_ticks": 8},
        ]
    )
    still, moving = stage.backgrounds
    assert (still.scroll, still.frames, still.frame_ticks) == (0.0, 1, 0)
    assert (moving.scroll, moving.frames, moving.frame_ticks) == (0.05, 3, 8)


# --- the sorter ----------------------------------------------------------------------------


def body(x: float, y: float, z: float = 0.0) -> DynamicItem:
    from isofightr.render.depth import sprite_rect

    return DynamicItem(8, 2, x, y, z, 2.5, sprite_rect(x, y, z, 10, 0, 40))


def order_of(sorter: DepthSorter, items: list[DynamicItem]) -> list[int]:
    return [entry.index for entry in sorter.draw_order(items) if not entry.is_static]


def test_a_fighter_passes_behind_and_in_front_of_a_prop() -> None:
    assert GRASS_STONE is not None
    stage = build(props=[{"sprite": "column", "at": [3.5, 3.5]}])
    sorter = DepthSorter(stage)
    (column,) = placed_props(stage, GRASS_STONE)
    prop = column.item
    behind, in_front = body(3.2, 3.2), body(3.8, 3.8)
    assert behind.rect.overlaps(prop.rect) and in_front.rect.overlaps(prop.rect)
    assert order_of(sorter, [behind, prop]) == [8, prop.item_id], "the column is drawn over them"
    assert order_of(sorter, [in_front, prop]) == [prop.item_id, 8], "they are drawn over it"


def test_a_standing_prop_is_drawn_after_the_ground_it_stands_on() -> None:
    assert GRASS_STONE is not None
    stage = build(props=[{"sprite": "column", "at": [3.5, 3.5]}], underside={"depth": 2.0})
    sorter = DepthSorter(stage)
    (column,) = placed_props(stage, GRASS_STONE)
    order = sorter.draw_order([column.item])
    at = next(index for index, entry in enumerate(order) if not entry.is_static)
    for index, entry in enumerate(order):
        if entry.is_static:
            static = sorter.statics[entry.index]
            if static.rect.overlaps(column.rect) and static.kind is not StaticKind.DECK:
                assert index < at, "no column or under block hides a prop standing on top"


def test_a_fixed_items_place_among_the_statics_is_worked_out_once() -> None:
    assert GRASS_STONE is not None
    stage = build(props=PROPS, underside={"depth": 2.0})
    sorter = DepthSorter(stage)
    items = [prop.item for prop in placed_props(stage, GRASS_STONE)]
    first = sorter.draw_order(items)
    calls = []
    original = sorter._overlapping_statics
    sorter._overlapping_statics = lambda rect: calls.append(rect) or original(rect)  # type: ignore[method-assign]
    assert sorter.draw_order(items) == first
    assert calls == [], "remembered"
    moving = body(1.5, 1.5)
    sorter.draw_order([*items, moving])
    assert calls == [moving.rect], "only the moving item is looked up again"


# --- the underside -------------------------------------------------------------------------


def test_the_mass_under_an_island_is_shallow_at_the_rim_and_deeper_inside() -> None:
    plain = build()
    assert under_depths(plain) == {} and lowest_point(plain) == plain.underside
    stage = build(underside={"depth": 3.0})
    distances = rim_distances(stage)
    assert distances[(0, 0)] == 1 and distances[(3, 3)] == 4 and len(distances) == 49
    depths = under_depths(stage)
    assert set(depths) == set(distances)
    assert all(0.25 <= depth <= 3.0 for depth in depths.values())
    assert all(depth * 4 == int(depth * 4) for depth in depths.values()), "whole 4 px steps"
    rim = [depths[cell] for cell, distance in distances.items() if distance == 1]
    assert max(rim) <= 1.0 < depths[(3, 3)], "it tapers"
    assert len(set(rim)) > 1, "and the rim is uneven"
    assert under_depths(stage) == depths, "the same every time"
    assert lowest_point(stage) == stage.underside - max(depths.values())
    shallow = under_depths(build(underside={"depth": 0.75}))
    assert max(shallow.values()) == 0.75


def test_under_blocks_join_the_sorter_below_the_island() -> None:
    stage = build(underside={"depth": 3.0})
    sorter = DepthSorter(stage)
    under = [item for item in sorter.statics if item.kind is StaticKind.UNDER]
    assert len(under) == 49
    depths = under_depths(stage)
    for item in under:
        assert item.top == stage.underside
        assert item.bottom == pytest.approx(stage.underside - depths[(item.cx, item.cy)])
    order = [sorter.statics[entry.index] for entry in sorter.draw_order([])]
    seen_column = set()
    for item in order:
        if item.kind is StaticKind.COLUMN:
            seen_column.add((item.cx, item.cy))
        elif item.kind is StaticKind.UNDER:
            assert (item.cx, item.cy) not in seen_column, "a cell's under block is drawn first"
    assert not [item for item in DepthSorter(build()).statics if item.kind is StaticKind.UNDER]


def test_under_blocks_are_ragged_but_never_outside_the_block() -> None:
    assert GRASS_STONE is not None
    stage_art = StageArt(GRASS_STONE)
    block = stage_art.tile("under", True, 32)
    ragged = stage_art.under("under", 32)
    assert block is not None and ragged is not None and ragged is stage_art.under("under", 32)
    kept = sum(1 for pixel in ragged.getdata() if pixel[3])
    whole = sum(1 for pixel in block.getdata() if pixel[3])
    assert whole * 0.8 < kept < whole
    for have, had in zip(ragged.getdata(), block.getdata(), strict=True):
        assert not have[3] or have == had, "only pixels are removed"
    assert ragged.crop((0, 0, 32, TILE_H)).tobytes() == block.crop((0, 0, 32, TILE_H)).tobytes()
    assert stage_art.under("lava", 32) is None
    assert stage_art.under("under", 32, 1).tobytes() != ragged.tobytes()


def test_roots_hang_from_some_of_the_rim_that_faces_the_camera() -> None:
    assert GRASS_STONE is not None
    stage = build(underside={"depth": 2.0, "hang": ["roots", "vine"]})
    hung = hanging(stage)
    assert hung == hanging(stage) and 2 <= len(hung) <= 8
    for name, cx, cy in hung:
        assert name in ("roots", "vine")
        assert stage.cell(cx + 1, cy) is None or stage.cell(cx, cy + 1) is None
    assert hanging(build(underside={"depth": 2.0})) == [] and hanging(build()) == []
    placed = placed_props(stage, GRASS_STONE)
    assert len(placed) == len(hung) and all(prop.below for prop in placed)
    assert len({prop.phase for prop in placed}) == len(placed), "they do not sway in step"


# --- ambience ------------------------------------------------------------------------------


def test_every_kind_has_a_style_in_palette() -> None:
    assert set(ambient.STYLES) == set(AMBIENT_KINDS)
    for kind, style in ambient.STYLES.items():
        for frame in range(len(style.frames)):
            image = ambient.build_mote(kind, frame)
            assert max(image.size) <= 4, "small"
            assert colours(image) and colours(image) <= MASTER, kind


def test_ambient_sprites_are_a_function_of_the_tick() -> None:
    leaves = Ambient("leaves", 12, 4)
    first = ambient.motes(leaves, 100, (0, 0))
    assert first == ambient.motes(leaves, 100, (0, 0)) and len(first) == 12
    assert [mote.front for mote in first] == [False] * 8 + [True] * 4
    later = ambient.motes(leaves, 160, (0, 0))
    moved = [(b.x - a.x, b.y - a.y) for a, b in zip(first, later, strict=True)]
    assert all(abs(dx) < 60 and abs(dy) < 40 for dx, dy in moved if abs(dx) < 300), "slow"
    assert any(dx != 0 or dy != 0 for dx, dy in moved)
    for tick in range(0, 4000, 37):
        for mote in ambient.motes(leaves, tick, (tick, -tick)):
            assert -ambient.WRAP_MARGIN <= mote.x <= NATIVE_W + ambient.WRAP_MARGIN
            assert -ambient.WRAP_MARGIN <= mote.y <= NATIVE_H + ambient.WRAP_MARGIN
    assert ambient.motes(None, 5, (0, 0)) == []
    # The ones in front move with the world; the ones behind lag as a far layer does.
    shifted = ambient.motes(leaves, 100, (40, 0))
    assert (first[11].x - shifted[11].x) % (NATIVE_W + 2 * ambient.WRAP_MARGIN) == 40
    assert (first[0].x - shifted[0].x) % (NATIVE_W + 2 * ambient.WRAP_MARGIN) == 12


def test_reduce_flashing_stops_the_blinking_and_turning() -> None:
    flies = Ambient("fireflies", 16, 0)
    lively = [ambient.motes(flies, tick, (0, 0)) for tick in range(0, 600, 12)]
    assert any(not mote.visible for frame in lively for mote in frame), "they blink"
    assert len({mote.frame for frame in lively for mote in frame}) == 2
    calm = [ambient.motes(flies, tick, (0, 0), calm=True) for tick in range(0, 600, 12)]
    assert all(mote.visible and mote.frame == 0 for frame in calm for mote in frame)


def test_a_sprite_in_front_never_covers_a_fighter() -> None:
    fighter = (300.0, 150.0, 320.0, 190.0)
    assert ambient.covers(ambient.Mote(310, 170, 0, True), [fighter])
    assert ambient.covers(ambient.Mote(322, 192, 0, True), [fighter]), "nor just beside one"
    assert not ambient.covers(ambient.Mote(330, 170, 0, True), [fighter])
    assert not ambient.covers(ambient.Mote(310, 170, 0, True), [])


# --- the stages and the intro --------------------------------------------------------------


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_stages_decor_is_in_bounds(stage_id: str) -> None:
    stage = load_stage(stage_id)
    tileset = load_tileset_art(stage.tileset)
    placed = placed_props(stage, tileset)
    flat = ground_props(stage, tileset)
    assert len(placed) + len(flat) == len(stage.props) + len(hanging(stage))
    assert len(placed) <= 40, "a few decorations, not a forest (the sorter's budget)"
    for spawn in stage.spawns:
        for prop in stage.props:
            if prop.layer == "world":
                apart = abs(prop.x - spawn.x) + abs(prop.y - spawn.y)
                assert apart >= 1.0, f"{prop.sprite} stands on a spawn"
    if stage.ambient is not None:
        assert stage.ambient.count <= AMBIENT_MAX
    for layer in stage.backgrounds:
        image = Image.open(Path("assets/stages") / stage_id / layer.image)
        assert image.height % layer.frames == 0


def test_the_stage_name_fades_in_and_is_gone_by_go() -> None:
    total = 180
    alphas = [hud_layout.intro_alpha(age, total) for age in range(total + 5)]
    assert alphas[0] == 0 and alphas[hud_layout.INTRO_FADE_IN] == 255
    assert alphas[total // 2] == 255 and alphas[total - 1] < 20
    assert alphas[total:] == [0] * 5
    rising = alphas[: hud_layout.INTRO_FADE_IN + 1]
    assert rising == sorted(rising)
    assert hud_layout.intro_alpha(10, 0) == 0, "no countdown, no intro"
    assert hud_layout.intro_alpha(-1, total) == 0
    assert hud_layout.PLAY_AREA.bottom < hud_layout.INTRO_BOTTOM < hud_layout.PLAY_AREA.top - 25


@pytest.mark.parametrize(
    ("stage_id", "theme", "mood", "seed"),
    [
        ("sky_ruins", "cloud_sea", "day", 5),
        ("twin_isles", "meadow", "golden", 4),
        ("lily_pads", "pond", "dusk", 6),
        ("final_plateau", "aurora", "night", 9),
        ("training_grid", "holo", "void", 2),
        ("ember_forge", "volcano", "ember", 3),
        ("frostpeak", "peaks", "dawn", 5),
        ("neon_circuit", "city", "glow", 8),
        ("dune_bazaar", "dunes", "haze", 7),
        ("glowcap_grove", "grove", "mist", 9),
        ("storm_galleon", "storm", "squall", 4),
    ],
)
def test_a_painter_reproduces_its_stages_backdrop(
    stage_id: str, theme: str, mood: str, seed: int
) -> None:
    from isofightr.render.backdrop import MOODS, PAINTERS

    layers = PAINTERS[theme](MOODS[mood], seed)
    assert list(layers) == [layer.image for layer in load_stage(stage_id).backgrounds]
    for name, image in layers.items():
        committed = Image.open(Path("assets/stages") / stage_id / name).convert("RGBA")
        assert committed.tobytes() == image.convert("RGBA").tobytes(), name
        assert colours(image) <= MASTER, "every backdrop colour is in the palette"
    files = {path.name for path in (Path("assets/stages") / stage_id).glob("bg_*.png")}
    assert files == set(layers), "no layer image is left over from an older backdrop"


# --- flat props: decals on the ground -------------------------------------------------------

RUNESTONE = load_tileset_art("runestone")


def test_a_ground_prop_is_a_decal_not_a_standing_thing() -> None:
    from isofightr.render.ground_items import DECAL_RANK
    from isofightr.render.props import GROUND_PROP_BASE, centred, ground_items

    assert RUNESTONE is not None
    stage = build(
        tileset="runestone",
        props=[
            {"sprite": "rune_a", "at": [3.5, 3.5], "layer": "ground", "period": 10},
            {"sprite": "obelisk", "at": [1.5, 0.5]},
        ],
    )
    assert [prop.art.name for prop in placed_props(stage, RUNESTONE)] == ["obelisk"]
    (rune,) = ground_props(stage, RUNESTONE)
    assert rune.art.name == "rune_a" and rune.z == 0.0 and rune.art.frames == 4
    assert ground_props(stage, None) == []

    asked = []

    def frame_image(name: str, frame: int) -> Image.Image:
        asked.append((name, frame))
        return Image.new("RGBA", (rune.art.width, rune.art.height), (1, 2, 3, 255))

    (item,) = ground_items([rune], 0, frame_image)
    assert item.item_id == GROUND_PROP_BASE and item.rank == DECAL_RANK
    assert (item.x, item.y, item.surface) == (3.5, 3.5, 0.0)
    keys = [ground_items([rune], tick, frame_image)[0].key for tick in (0, 10, 20, 30, 40)]
    assert len(set(keys)) == 4 and keys[0] == keys[4], "four frames, then round again"
    calm = [ground_items([rune], tick, frame_image, calm=True)[0].key for tick in (0, 10, 20)]
    assert len(set(calm)) == 1, "with reduce flashing it holds one frame"

    # The picture is padded so that the prop's pivot is its middle, where a decal is anchored.
    picture = item.build()
    assert asked == [("rune_a", 0)]
    art = rune.art
    assert picture.width == 2 * max(art.pivot_x, art.width - art.pivot_x)
    assert picture.height == 2 * max(art.pivot_y, art.height - art.pivot_y)
    left, top = picture.width // 2 - art.pivot_x, picture.height // 2 - art.pivot_y
    assert picture.getpixel((left, top)) == (1, 2, 3, 255)
    assert centred(picture, art).size >= picture.size


def test_a_stage_may_put_a_ground_prop_on_a_spawn() -> None:
    stage = load_stage("final_plateau")
    flat = [prop for prop in stage.props if prop.layer == "ground"]
    assert len(flat) == 9 and flat[0].sprite == "sigil"
    assert (flat[0].x, flat[0].y) == (stage.respawn.x, stage.respawn.y)
