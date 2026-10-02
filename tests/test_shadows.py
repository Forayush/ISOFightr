"""Unit tests for clipping a fighter's shadow to its surface (plan note 03, "Shadows")."""

from isofightr.data.stage_loader import load_stage
from isofightr.render import placeholder_art as art
from isofightr.render.camera import snap
from isofightr.render.iso import project
from isofightr.render.shadows import FULL_MASK, apply_mask, shadow_mask
from isofightr.sim.stage import Stage

SKY_RUINS = load_stage("sky_ruins")
WIDTH, HEIGHT = art.SHADOW_WIDTH, art.SHADOW_HEIGHT


def mask_at(stage: Stage, x: float, y: float, surface: float) -> bytes:
    centre_x, centre_y = (snap(value) for value in project(x, y, surface))
    return shadow_mask(stage, centre_x, centre_y, surface)


def ring_ends(mask: bytes) -> tuple[int, int]:
    """Return whether the ring's leftmost and rightmost pixels (middle row) are kept.

    Island edges run diagonally on screen, so a cut is a slanted line, not a vertical one;
    the ends of the ring on the middle row are the clearest thing to check.
    """
    middle = (HEIGHT // 2) * WIDTH
    return (mask[middle], mask[middle + WIDTH - 1])


def test_mask_is_one_byte_per_pixel() -> None:
    assert len(FULL_MASK) == WIDTH * HEIGHT
    assert set(FULL_MASK) == {1}


def test_whole_shadow_is_kept_in_the_middle_of_the_island() -> None:
    assert mask_at(SKY_RUINS, 6.5, 4.5, 0.0) is FULL_MASK


def test_nothing_is_kept_over_the_void() -> None:
    assert set(mask_at(SKY_RUINS, 16.0, 4.5, 0.0)) == {0}


def test_shadow_is_cut_at_the_south_east_edge() -> None:
    # 0.2 units inside the +x edge (x = 13), which runs down-left on screen: the right-hand
    # end of the ring hangs over the void.
    mask = mask_at(SKY_RUINS, 12.8, 4.5, 0.0)
    assert mask is not FULL_MASK
    assert ring_ends(mask) == (1, 0)
    kept = sum(mask)
    assert WIDTH * HEIGHT * 0.4 < kept < WIDTH * HEIGHT * 0.9


def test_shadow_is_cut_at_the_north_west_edge() -> None:
    mask = mask_at(SKY_RUINS, 0.2, 4.5, 0.0)
    assert ring_ends(mask) == (0, 1)


def test_more_is_cut_the_closer_the_fighter_is_to_the_edge() -> None:
    kept = [sum(mask_at(SKY_RUINS, x, 4.5, 0.0)) for x in (12.5, 12.7, 12.9, 13.0)]
    assert kept == sorted(kept, reverse=True)
    assert kept[0] > kept[-1]


def test_shadow_on_a_platform_is_cut_at_the_deck_edge() -> None:
    # The low screen-left platform covers x 2..5, y 6..9 at z 2.5.
    assert mask_at(SKY_RUINS, 3.5, 7.5, 2.5) is FULL_MASK
    mask = mask_at(SKY_RUINS, 4.8, 7.5, 2.5)
    assert ring_ends(mask) == (1, 0)


def test_ground_shadow_under_a_platform_is_not_cut_by_the_platform() -> None:
    assert mask_at(SKY_RUINS, 3.5, 7.0, 0.0) is FULL_MASK


def test_shadow_does_not_spill_onto_a_surface_at_another_height() -> None:
    # Standing at the corner of the deck: the ground is directly below the overhanging part,
    # but it is a different surface, so those pixels are still cut.
    mask = mask_at(SKY_RUINS, 4.95, 6.05, 2.5)
    assert 0 < sum(mask) < WIDTH * HEIGHT


def test_apply_mask_clears_only_masked_pixels() -> None:
    image = art.build_shadow(0, 0)
    assert apply_mask(image, FULL_MASK) is image

    mask = bytearray(FULL_MASK)
    for row in range(HEIGHT):
        for index in range(WIDTH // 2, WIDTH):
            mask[row * WIDTH + index] = 0
    clipped = apply_mask(image, bytes(mask))
    assert clipped is not image
    assert clipped.size == image.size
    middle = HEIGHT // 2
    assert clipped.getpixel((0, middle)) == image.getpixel((0, middle))
    assert clipped.getpixel((WIDTH - 1, middle))[3] == 0  # type: ignore[index]
    assert image.getpixel((WIDTH - 1, middle))[3] == 255, "the original is untouched"  # type: ignore[index]
