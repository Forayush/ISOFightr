"""Unit tests for the procedural placeholder art (plan note 09, "Placeholder art")."""

import pytest
from PIL import Image

from isofightr.config import DECK_THICKNESS, NATIVE_H, NATIVE_W, TILE_H, TILE_W, Z_PX
from isofightr.render import placeholder_art as art
from isofightr.sim.input_frame import Dir8

OPAQUE = 255


def alpha_at(image: Image.Image, x: int, y: int) -> int:
    return image.getpixel((x, y))[3]  # type: ignore[index]


def opaque_columns(image: Image.Image, row: int) -> list[int]:
    return [x for x in range(image.width) if alpha_at(image, x, row) == OPAQUE]


# --- tiles --------------------------------------------------------------------------------


def test_diamond_rows_step_one_pixel_down_per_two_across() -> None:
    assert art.diamond_row_range(0) == (7, 8)
    assert art.diamond_row_range(1) == (7, 8)
    assert art.diamond_row_range(2) == (6, 9)
    assert art.diamond_row_range(15) == (0, 15)
    assert art.diamond_row_range(16) == (0, 15)
    assert art.diamond_row_range(31) == (7, 8)


def test_top_diamond_is_32_wide_and_16_tall() -> None:
    block = art.build_tile("grass", light=True, side_px=16)
    assert block.size == (TILE_W, TILE_H + 16)
    assert len(opaque_columns(block, 7)) == TILE_W
    assert opaque_columns(block, 0) == [14, 15, 16, 17]
    top_color = art.tile_palette("grass").top_light
    assert block.getpixel((15, 0)) == top_color
    assert block.getpixel((0, 7)) == top_color


def test_neighbouring_tiles_tessellate_with_one_shared_edge_row() -> None:
    """The tile at (+1, 0) sits 16 px right and 8 px down. Its top edge must start on the row
    where this tile's diamond ends, in every pixel column they share."""
    for column in range(TILE_W // 2, TILE_W):
        _, last_row = art.diamond_row_range(column)
        neighbour_first_row, _ = art.diamond_row_range(column - TILE_W // 2)
        assert neighbour_first_row + TILE_H // 2 == last_row


def test_side_faces_hang_the_requested_height_below_the_diamond() -> None:
    for side_px in (4, 16, 48):
        block = art.build_tile("stone", light=False, side_px=side_px)
        assert block.height == TILE_H + side_px
        # Centre columns: diamond ends at row 15, faces fill the rest, down to the last row.
        assert alpha_at(block, 15, TILE_H + side_px - 1) == OPAQUE
        # Outer columns: diamond ends at row 8, so the face stops 7 rows short of the bottom.
        assert alpha_at(block, 0, 8 + side_px) == OPAQUE
        assert alpha_at(block, 0, 8 + side_px + 1) == 0


def test_left_face_is_lit_and_right_face_is_shaded() -> None:
    palette = art.tile_palette("stone")
    block = art.build_tile("stone", light=True, side_px=16)
    assert block.getpixel((4, 24)) == palette.left
    assert block.getpixel((27, 24)) == palette.right
    assert sum(palette.left[:3]) > sum(palette.right[:3])


def test_grass_has_a_turf_lip_over_the_side_faces() -> None:
    palette = art.tile_palette("grass")
    block = art.build_tile("grass", light=True, side_px=16)
    assert palette.lip is not None
    assert block.getpixel((15, TILE_H)) == palette.lip
    assert block.getpixel((15, TILE_H + art.GRASS_LIP_PX)) == palette.left


def test_checker_tones_differ() -> None:
    light = art.build_tile("grid", light=True, side_px=16)
    dark = art.build_tile("grid", light=False, side_px=16)
    assert light.getpixel((15, 8)) != dark.getpixel((15, 8))


def test_unknown_tile_names_fall_back_to_the_default_look() -> None:
    assert art.tile_palette("no_such_tile") == art.tile_palette(art.DEFAULT_TILE_PALETTE)
    assert art.tile_palette("default") == art.tile_palette("grass")


def test_deck_is_a_thin_slab() -> None:
    deck = art.build_deck(light=True)
    assert deck.size == (TILE_W, TILE_H + round(DECK_THICKNESS * Z_PX))
    assert deck.getpixel((15, 8)) == art.DECK_PALETTE.top_light


def test_platform_shadow_is_a_translucent_diamond() -> None:
    shadow = art.build_platform_shadow()
    assert shadow.size == (TILE_W, TILE_H)
    assert shadow.getpixel((15, 8)) == art.PLATFORM_SHADOW
    assert 0 < art.PLATFORM_SHADOW[3] < OPAQUE
    assert alpha_at(shadow, 0, 0) == 0


# --- fighters -----------------------------------------------------------------------------


@pytest.mark.parametrize("facing", list(Dir8))
def test_fighter_stands_on_the_pivot_and_is_two_and_a_half_units_tall(facing: Dir8) -> None:
    image = art.build_fighter(0, facing)
    assert image.size == (art.FIGHTER_CANVAS, art.FIGHTER_CANVAS)
    feet_row = art.FIGHTER_CANVAS - art.FIGHTER_PIVOT_FROM_BOTTOM
    left, top, right, bottom = image.getbbox()  # type: ignore[misc]
    assert bottom == feet_row, "nothing is drawn below the feet"
    assert top == feet_row - art.BODY_HEIGHT
    assert art.BODY_HEIGHT == 2.5 * Z_PX
    # Everything, arrow tips included, stays inside the rectangle the depth sorter assumes.
    assert left >= art.FIGHTER_PIVOT_X - art.BODY_HALF_WIDTH - 3
    assert right <= art.FIGHTER_PIVOT_X + art.BODY_HALF_WIDTH + 3
    # The body is centred on the pivot column boundary.
    assert image.getpixel((art.FIGHTER_PIVOT_X - 1, feet_row - 5)) == art.player_color(0)
    assert image.getpixel((art.FIGHTER_PIVOT_X, feet_row - 5)) == art.player_color(0)


def test_each_facing_looks_different() -> None:
    images = {art.build_fighter(0, facing).tobytes() for facing in Dir8}
    assert len(images) == len(Dir8)


def test_only_camera_facing_fighters_have_eyes() -> None:
    def has_eyes(facing: Dir8) -> bool:
        image = art.build_fighter(0, facing)
        feet_row = art.FIGHTER_CANVAS - art.FIGHTER_PIVOT_FROM_BOTTOM
        eye_row = feet_row - art.EYE_HEIGHT_ABOVE_FEET
        return any(image.getpixel((x, eye_row)) == art.WHITE for x in range(art.FIGHTER_CANVAS))

    assert all(has_eyes(facing) for facing in (Dir8.S, Dir8.SE, Dir8.SW, Dir8.E, Dir8.W))
    assert not any(has_eyes(facing) for facing in (Dir8.N, Dir8.NE, Dir8.NW))


def test_player_colors_follow_the_plan_and_wrap() -> None:
    assert art.player_color(0) == (232, 59, 59, 255)
    assert art.player_color(1) == (77, 155, 230, 255)
    assert art.player_color(2) == (249, 194, 43, 255)
    assert art.player_color(3) == (30, 188, 115, 255)
    assert art.player_color(4) == art.player_color(0)
    assert art.build_fighter(1, Dir8.S).tobytes() != art.build_fighter(0, Dir8.S).tobytes()


def test_art_is_deterministic() -> None:
    assert art.build_fighter(2, Dir8.NE).tobytes() == art.build_fighter(2, Dir8.NE).tobytes()
    assert (
        art.build_tile("grass", True, 16).tobytes() == art.build_tile("grass", True, 16).tobytes()
    )


# --- shadows ------------------------------------------------------------------------------


def test_shadow_has_a_player_colored_ring_at_every_height() -> None:
    for variant in range(len(art.SHADOW_VARIANTS)):
        shadow = art.build_shadow(1, variant)
        assert shadow.size == (art.SHADOW_WIDTH, art.SHADOW_HEIGHT)
        assert art.SHADOW_WIDTH % 2 == 0 and art.SHADOW_HEIGHT % 2 == 0
        assert shadow.getpixel((0, art.SHADOW_HEIGHT // 2)) == art.player_color(1)
        assert shadow.getpixel((art.SHADOW_WIDTH - 1, art.SHADOW_HEIGHT // 2)) == art.player_color(
            1
        )


def test_shadow_blob_shrinks_and_fades_with_height() -> None:
    variants = art.SHADOW_VARIANTS
    assert [v.blob_width for v in variants] == sorted(
        (v.blob_width for v in variants), reverse=True
    )
    assert [v.blob_alpha for v in variants] == sorted(
        (v.blob_alpha for v in variants), reverse=True
    )
    centre = (art.SHADOW_WIDTH // 2, art.SHADOW_HEIGHT // 2)
    alphas = [art.build_shadow(0, index).getpixel(centre)[3] for index in range(len(variants))]  # type: ignore[index]
    assert alphas == [v.blob_alpha for v in variants]


def test_shadow_variant_by_height() -> None:
    assert art.shadow_variant_index(0.0) == 0
    assert art.shadow_variant_index(0.75) == 0
    assert art.shadow_variant_index(0.76) == 1
    assert art.shadow_variant_index(2.5) == 1
    assert art.shadow_variant_index(9.0) == 2


# --- sky ----------------------------------------------------------------------------------


def test_sky_fills_the_native_buffer_dark_at_the_top() -> None:
    sky = art.build_sky()
    assert sky.size == (NATIVE_W, NATIVE_H)
    assert sky.getchannel("A").getextrema() == (OPAQUE, OPAQUE)
    assert sky.getpixel((0, 0)) == art.SKY_BANDS[0]
    assert sky.getpixel((NATIVE_W - 1, NATIVE_H - 1)) == art.SKY_BANDS[-1]
    assert sum(art.SKY_BANDS[0][:3]) < sum(art.SKY_BANDS[-1][:3])


def test_shade_scales_color_and_keeps_alpha() -> None:
    assert art.shade((200, 100, 50, 128), 0.5) == (100, 50, 25, 128)
