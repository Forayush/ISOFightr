"""Unit tests for the procedural M0 test pattern (image coordinates: origin top-left)."""

from isofightr.config import NATIVE_H, NATIVE_W, TICK_RATE
from isofightr.render import test_pattern as tp


def test_pattern_is_native_resolution_rgba() -> None:
    image = tp.build_test_pattern()
    assert image.size == (NATIVE_W, NATIVE_H)
    assert image.mode == "RGBA"


def test_pattern_is_deterministic() -> None:
    assert tp.build_test_pattern().tobytes() == tp.build_test_pattern().tobytes()


def test_pattern_is_fully_opaque() -> None:
    assert tp.build_test_pattern().getchannel("A").getextrema() == (255, 255)


def test_one_pixel_border_reaches_every_edge() -> None:
    image = tp.build_test_pattern()
    for point in [(0, 0), (NATIVE_W - 1, 0), (0, NATIVE_H - 1), (NATIVE_W - 1, NATIVE_H - 1)]:
        assert image.getpixel(point) == tp.BORDER


def test_corners_identify_orientation() -> None:
    image = tp.build_test_pattern()
    top_left, top_right, bottom_left, bottom_right = tp.CORNER_COLORS
    assert image.getpixel((1, 1)) == top_left
    assert image.getpixel((NATIVE_W - 2, 1)) == top_right
    assert image.getpixel((1, NATIVE_H - 2)) == bottom_left
    assert image.getpixel((NATIVE_W - 2, NATIVE_H - 2)) == bottom_right


def test_checker_block_alternates_every_pixel() -> None:
    image = tp.build_test_pattern()
    row = [image.getpixel((tp.BLOCK_LEFT + x, tp.BLOCK_TOP)) for x in range(4)]
    assert row == [tp.LIGHT, tp.DARK, tp.LIGHT, tp.DARK]
    assert image.getpixel((tp.BLOCK_LEFT, tp.BLOCK_TOP + 1)) == tp.DARK


def test_marker_moves_one_pixel_per_tick_and_bounces() -> None:
    assert [tp.marker_offset(tick) for tick in range(3)] == [0, 1, 2]
    assert tp.marker_offset(tp.TRACK_SPAN) == tp.TRACK_SPAN
    assert tp.marker_offset(tp.TRACK_SPAN + 1) == tp.TRACK_SPAN - 1
    assert tp.marker_offset(2 * tp.TRACK_SPAN) == 0
    steps = {
        abs(tp.marker_offset(tick + 1) - tp.marker_offset(tick))
        for tick in range(4 * tp.TRACK_SPAN)
    }
    assert steps == {1}


def test_marker_covers_one_notch_per_second() -> None:
    assert tp.marker_offset(TICK_RATE) - tp.marker_offset(0) == TICK_RATE
    assert tp.TRACK_SPAN % TICK_RATE == 0


def test_marker_stays_inside_the_buffer_and_on_whole_pixels() -> None:
    half = tp.MARKER_SIZE // 2
    assert tp.MARKER_SIZE % 2 == 0
    for tick in (0, tp.TRACK_SPAN // 2, tp.TRACK_SPAN):
        x, y = tp.marker_center_native(tick)
        assert isinstance(x, int) and isinstance(y, int)
        assert half <= x <= NATIVE_W - half
        assert half <= y <= NATIVE_H - half
