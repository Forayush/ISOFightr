"""Render smoke tests: need a real OpenGL window, so they are opt-in (``pytest -m gl``).

Plan note "16 - Testing Debug and Tooling" lists these as optional and skipped in CI. They
prove the M0 exit criterion mechanically: the native buffer holds the test pattern exactly,
and the upscale reproduces every native pixel as an exact ``scale x scale`` block.
"""

from collections.abc import Iterator

import pytest
from PIL import Image, ImageChops

from isofightr.config import DEFAULT_WINDOW_SCALE, NATIVE_H, NATIVE_W, TICK_SECONDS
from isofightr.render import test_pattern as tp
from isofightr.render.pixel_scale import integer_scale_viewport

pytestmark = pytest.mark.gl

LETTERBOX_PROBE_COLOR = (255, 0, 255, 255)


@pytest.fixture(scope="module")
def window() -> Iterator["GameWindow"]:  # type: ignore[name-defined]  # noqa: F821
    from isofightr.app import GameWindow

    game_window = GameWindow(visible=False)
    yield game_window
    game_window.close()


def _read_rgba(framebuffer, size: tuple[int, int]) -> Image.Image:  # type: ignore[no-untyped-def]
    """Read a framebuffer back as an upright RGBA image (OpenGL rows run bottom to top)."""
    data = framebuffer.read(components=4)
    return Image.frombytes("RGBA", size, data).transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def _expected_native_frame(tick: int) -> Image.Image:
    """The pattern with the marker composited where the view should draw it at ``tick``."""
    expected = tp.build_test_pattern()
    center_x, center_y_up = tp.marker_center_native(tick)
    half = tp.MARKER_SIZE // 2
    expected.paste(tp.build_marker(), (center_x - half, NATIVE_H - center_y_up - half))
    return expected


def _draw_view(window, max_ticks: int | None = None):  # type: ignore[no-untyped-def]
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    view = BattleView(window.pixel_buffer, max_ticks=max_ticks)
    window.show_view(view)
    return view


def test_window_is_sized_in_real_pixels(window) -> None:  # type: ignore[no-untyped-def]
    """A display scale such as 125% must not stretch the framebuffer (it once gave 2.5x)."""
    expected = (NATIVE_W * DEFAULT_WINDOW_SCALE, NATIVE_H * DEFAULT_WINDOW_SCALE)
    assert window.get_framebuffer_size() == expected
    assert window.get_size() == expected
    assert window.get_pixel_ratio() == 1.0


def test_native_buffer_matches_the_pattern_pixel_for_pixel(window) -> None:  # type: ignore[no-untyped-def]
    view = _draw_view(window)
    view.on_draw()
    actual = _read_rgba(window.pixel_buffer.framebuffer, (NATIVE_W, NATIVE_H))
    assert ImageChops.difference(actual, _expected_native_frame(tick=0)).getbbox() is None


def test_fixed_timestep_drives_the_marker(window) -> None:  # type: ignore[no-untyped-def]
    view = _draw_view(window)
    view.on_update(TICK_SECONDS * 3)
    assert view.tick_count == 3
    view.on_draw()
    actual = _read_rgba(window.pixel_buffer.framebuffer, (NATIVE_W, NATIVE_H))
    assert ImageChops.difference(actual, _expected_native_frame(tick=3)).getbbox() is None


@pytest.mark.parametrize("target_size", [(1280, 720), (1920, 1080), (1366, 768)])
def test_upscale_is_exact_integer_nearest_neighbor(window, target_size) -> None:  # type: ignore[no-untyped-def]
    view = _draw_view(window)
    view.on_draw()

    ctx = window.ctx
    target = ctx.framebuffer(color_attachments=[ctx.texture(target_size, components=4)])
    target.clear(color=LETTERBOX_PROBE_COLOR)
    viewport = integer_scale_viewport(*target_size)
    window.pixel_buffer.blit(target, viewport)
    actual = _read_rgba(target, target_size)

    expected = Image.new("RGBA", target_size, LETTERBOX_PROBE_COLOR)
    upscaled = _expected_native_frame(tick=0).resize(
        (viewport.width, viewport.height), Image.Resampling.NEAREST
    )
    top = target_size[1] - viewport.bottom - viewport.height
    expected.paste(upscaled, (viewport.left, top))
    assert ImageChops.difference(actual, expected).getbbox() is None
