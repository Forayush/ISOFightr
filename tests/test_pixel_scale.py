"""Unit tests for integer scaling and letterboxing (plan note 03, "Native resolution")."""

import pytest

from isofightr.render.pixel_scale import ScaledViewport, integer_scale_viewport


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
