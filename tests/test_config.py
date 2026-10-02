"""Sanity checks on the compile-time constants other code builds on."""

from isofightr import config


def test_tick_is_one_sixtieth_of_a_second() -> None:
    assert config.TICK_RATE == 60
    assert config.TICK_SECONDS * config.TICK_RATE == 1.0


def test_projection_is_two_to_one_dimetric() -> None:
    assert config.TILE_W == 2 * config.TILE_H
    assert (config.TILE_W, config.TILE_H, config.Z_PX) == (32, 16, 16)


def test_native_resolution_scales_to_common_windows() -> None:
    assert (config.NATIVE_W, config.NATIVE_H) == (640, 360)
    scale = config.DEFAULT_WINDOW_SCALE
    assert (config.NATIVE_W * scale, config.NATIVE_H * scale) == (1280, 720)


def test_frame_clamp_allows_at_least_one_tick() -> None:
    assert config.MAX_FRAME_SECONDS >= config.TICK_SECONDS
