"""The Isle on a real window (``pytest -m gl``): decision D-072, M21."""

from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS

pytestmark = pytest.mark.gl


def frame(window: Any) -> Any:
    """Draw the current view and return what it drew."""
    from isofightr.capture import read_frame

    window.current_view.on_draw()
    return read_frame(window)


def test_the_isle_fills_the_screen_at_every_station(window: Any) -> None:
    from isofightr.scenes.menu_world import IsleView, MenuWorld
    from isofightr.scenes.menu_world_model import STATIONS, rest_pose

    window.switch_to()
    world = MenuWorld(window.pixel_buffer)
    seen = set()
    for name in STATIONS:
        window.show_view(IsleView(window.pixel_buffer, world, name))
        window.current_view.on_update(TICK_SECONDS)
        assert world.pose == rest_pose(STATIONS[name]) and not world.gliding
        picture = frame(window)
        assert picture.size == (NATIVE_W, NATIVE_H)
        colours = picture.convert("RGB").getcolors(1 << 16)
        assert colours is not None and len(colours) > 20, "sky, island and props are drawn"
        seen.add(picture.tobytes())
    assert len(seen) == len(STATIONS), "every station is its own picture"


def test_the_camera_glides_from_station_to_station_and_then_rests(window: Any) -> None:
    from isofightr.scenes.menu_world import IsleView, MenuWorld
    from isofightr.scenes.menu_world_model import GLIDE_TICKS, STATIONS, rest_pose

    window.switch_to()
    world = MenuWorld(window.pixel_buffer)
    window.show_view(IsleView(window.pixel_buffer, world, "gate", "ring"))
    assert world.station is STATIONS["ring"]
    poses = []
    for _ in range(GLIDE_TICKS):
        assert world.gliding
        frame(window)  # a fraction of a zoom draws without complaint
        window.current_view.on_update(TICK_SECONDS)
        poses.append(world.pose)
    assert not world.gliding and world.pose == rest_pose(STATIONS["ring"])
    assert len(set(poses)) == len(poses), "it moves on every tick of the glide"
    world.go("ring")
    assert not world.gliding, "asking for the station it is at changes nothing"
    world.go("plaza")
    world.tick()
    half = world.pose
    world.go("gate")
    assert world.pose == half, "a new glide starts from where the camera is"


def test_a_world_point_is_drawn_where_screen_point_says(window: Any) -> None:
    from isofightr.scenes.menu_world import IsleView, MenuWorld
    from isofightr.scenes.menu_world_model import RING_SPOTS

    window.switch_to()
    world = MenuWorld(window.pixel_buffer)
    window.show_view(IsleView(window.pixel_buffer, world, "ring"))
    window.current_view.on_update(TICK_SECONDS)
    picture = frame(window).convert("RGB")
    sky = {colour for _, colour in picture.crop((0, 0, 40, 8)).getcolors(1 << 16)}
    for x, y in RING_SPOTS:
        column, row = world.screen_point(x, y)
        top = NATIVE_H - 1 - row
        around = picture.crop((column - 8, top - 8, column + 9, top + 9))
        ground = {colour for _, colour in around.getcolors(1 << 16)} - sky
        assert len(ground) >= 3, "the ring's mosaic is drawn there, not the sky"


def test_the_capture_tool_shows_a_station_and_a_glide(window: Any) -> None:
    from isofightr.capture import capture_screen

    still = capture_screen(window, "isle", ticks=(5,), station="plaza")
    assert still.size == (NATIVE_W, NATIVE_H)
    strip = capture_screen(window, "isle", ticks=(6, 12, 24), station="gate", goal="ring")
    assert strip.size == (3 * NATIVE_W, NATIVE_H)
    frames = [strip.crop((i * NATIVE_W, 0, (i + 1) * NATIVE_W, NATIVE_H)) for i in range(3)]
    assert len({each.tobytes() for each in frames}) == 3
    with pytest.raises(ValueError, match="unknown station"):
        capture_screen(window, "isle", station="nowhere")
