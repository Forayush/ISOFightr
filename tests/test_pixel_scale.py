"""Unit tests for integer scaling and letterboxing (plan note 03, "Native resolution")."""

import pytest

from isofightr.render.pixel_scale import (
    ScaledViewport,
    integer_scale_viewport,
    window_to_native,
)


@pytest.mark.parametrize(
    ("window", "scale"),
    [
        ((1280, 720), 2),
        ((1920, 1080), 3),
        ((2560, 1440), 4),
        ((3840, 2160), 6),
    ],
)
def test_exact_multiples_fill_the_window(window: tuple[int, int], scale: int) -> None:
    viewport = integer_scale_viewport(*window)
    assert viewport == ScaledViewport(scale, 0, 0, window[0], window[1])


def test_remainder_is_letterboxed_evenly() -> None:
    viewport = integer_scale_viewport(1366, 768)
    assert viewport.scale == 2
    assert (viewport.width, viewport.height) == (1280, 720)
    assert (viewport.left, viewport.bottom) == (43, 24)


def test_scale_is_limited_by_the_tighter_axis() -> None:
    assert integer_scale_viewport(1920, 720).scale == 2
    assert integer_scale_viewport(1280, 1080).scale == 2


def test_window_smaller_than_native_stays_at_one_x_and_crops_centered() -> None:
    viewport = integer_scale_viewport(600, 300)
    assert viewport.scale == 1
    assert (viewport.left, viewport.bottom) == (-20, -30)


def test_lbwh_is_in_opengl_viewport_order() -> None:
    assert integer_scale_viewport(1366, 768).lbwh == (43, 24, 1280, 720)


def test_custom_native_size() -> None:
    assert integer_scale_viewport(100, 100, native_width=30, native_height=20).scale == 3


# --- mouse: window position to native pixel (decision D-061) --------------------------------


def test_a_mouse_position_maps_to_the_native_pixel_under_it() -> None:
    for scale in (1, 2, 3, 4):
        viewport = integer_scale_viewport(640 * scale, 360 * scale)
        assert window_to_native(0, 0, viewport) == (0, 0), "bottom-left, y up"
        assert window_to_native(640 * scale - 1, 360 * scale - 1, viewport) == (639, 359)
        assert window_to_native(scale * 10 + scale - 1, scale * 20, viewport) == (10, 20)
        assert window_to_native(scale * 11, scale * 20, viewport) == (11, 20)
        assert window_to_native(640 * scale, 5, viewport) is None


def test_the_letterbox_is_outside_the_picture() -> None:
    viewport = integer_scale_viewport(1366, 768)  # 2x, 43 px left and right, 24 above and below
    assert window_to_native(42, 100, viewport) is None
    assert window_to_native(43, 24, viewport) == (0, 0)
    assert window_to_native(43 + 1279, 24 + 719, viewport) == (639, 359)
    assert window_to_native(43 + 1280, 400, viewport) is None
    assert window_to_native(600, 23, viewport) is None
    assert window_to_native(42.9, 100, viewport) is None, "fractions round toward the letterbox"


def test_a_window_smaller_than_the_picture_shows_its_middle() -> None:
    viewport = integer_scale_viewport(600, 300)  # 1x, cropped by 20 and 30 on each side
    assert window_to_native(0, 0, viewport) == (20, 30)
    assert window_to_native(599, 299, viewport) == (619, 329)


def test_the_pixel_ratio_scales_window_units_to_framebuffer_pixels() -> None:
    viewport = integer_scale_viewport(2560, 1440)  # a 1280x720 window at ratio 2
    assert viewport.scale == 4
    assert window_to_native(640, 360, viewport, pixel_ratio=2.0) == (320, 180)
    assert window_to_native(1279, 719, viewport, pixel_ratio=2.0) == (639, 359)
