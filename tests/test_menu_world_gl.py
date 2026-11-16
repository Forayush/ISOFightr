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


def test_the_roster_strolls_on_the_plaza_but_not_at_the_ring(window: Any) -> None:
    from isofightr.data.character_loader import list_character_ids
    from isofightr.scenes.menu_world import MenuWorld
    from isofightr.scenes.menu_world_model import GLIDE_TICKS

    window.switch_to()
    world = MenuWorld(window.pixel_buffer, seed=3)
    assert [f.character.id for f in world.match.fighters] == list_character_ids()[:4]
    assert set(world.banks) == set(list_character_ids()), "sheets for the whole roster"
    assert world.bank("rook") is world.banks["rook"] and world.bank("nobody") is None
    assert world.strollers_shown
    entities, looks = world._entities()
    assert len(entities) == 4 and all(look.costume == 0 for look in looks.values())
    before = world.match.state_hash()
    with window.pixel_buffer.drawing():
        world.draw()
    assert world.match.state_hash() == before, "drawing changes nothing"
    world.tick()
    assert world.match.frame == 1 and world.match.state_hash() != before

    world.go("ring")
    assert not world.strollers_shown, "they leave as the camera starts for the ring"
    for _ in range(GLIDE_TICKS):
        world.tick()
    assert not world.strollers_shown and world._entities()[0] == []
    world.go("plaza")
    assert not world.strollers_shown, "and are back when it has left it"
    for _ in range(GLIDE_TICKS):
        world.tick()
    assert world.strollers_shown
    world.go("workshop")
    assert world.strollers_shown, "between the other stations they stay"


def test_a_fighter_at_the_ring_is_twice_its_battle_size(window: Any) -> None:
    from isofightr.capture import read_frame
    from isofightr.scenes.menu_world import MenuWorld
    from isofightr.scenes.menu_world_model import DROP_TICKS, LAND_TICKS, RING_SPOTS, Mood

    window.switch_to()
    world = MenuWorld(window.pixel_buffer)
    world.settle("ring")

    def shot() -> Any:
        with window.pixel_buffer.drawing():
            world.draw()
        return read_frame(window).convert("RGB")

    empty = shot()
    stand_in = world.stand(1, "rook", costume=0)
    assert stand_in.mood is Mood.DROP_IN and world.ring[1] is stand_in
    falling = shot()
    for _ in range(DROP_TICKS + LAND_TICKS + 2):
        world.tick()
    assert stand_in.pose(world.ticks).anim == "idle"
    standing = shot()
    column, row = world.screen_point(*RING_SPOTS[1])
    top = NATIVE_H - 1 - row

    def changed(picture: Any, box: tuple[int, int, int, int]) -> int:
        """Pixels of a box that differ from the empty ring."""
        there, before = picture.crop(box), empty.crop(box)
        return sum(1 for a, b in zip(there.getdata(), before.getdata(), strict=True) if a != b)

    body = (column - 40, top - 96, column + 40, top + 6)
    assert changed(standing, body) > 1500, "a fighter stands on the spot, large"
    assert changed(falling, (column - 40, 0, column + 40, top - 100)) > 300, "it drops in"
    frame_info = world.banks["rook"].frame("idle", 0, stand_in.facing)
    box = None
    for y in range(top - 110, top + 8):
        for x in range(column - 50, column + 50):
            if standing.getpixel((x, y)) != empty.getpixel((x, y)):
                box = (
                    (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
                    if box
                    else (x, y, x, y)
                )
    assert box is not None
    tall = box[3] - box[1] + 1
    assert tall >= 2 * frame_info.height - 12, "drawn at twice the size of its battle sprite"

    same = world.stand(1, "rook", costume=3)
    assert same is stand_in and stand_in.costume == 3, "the same fighter, recoloured"
    assert stand_in.since == 0, "and it does not drop in again"
    recoloured = shot()
    assert changed(recoloured, body) > 0 and recoloured.tobytes() != standing.tobytes()
    world.mood(1, Mood.READY)
    assert stand_in.mood is Mood.READY and stand_in.since == world.ticks
    world.mood(1, Mood.READY)
    other = world.stand(1, "mote")
    assert other is not stand_in and other.mood is Mood.DROP_IN, "another fighter drops in"
    world.leave(1)
    assert world.ring[1] is None
    world.mood(1, Mood.WIN)  # nobody there: nothing happens


def test_ring_pads_are_drawn_in_their_slots_colours(window: Any) -> None:
    from isofightr.capture import read_frame
    from isofightr.scenes.menu_world import MenuWorld
    from isofightr.scenes.menu_world_model import RING_SPOTS
    from isofightr.ui import theme

    window.switch_to()
    world = MenuWorld(window.pixel_buffer)
    world.settle("ring")
    world.pads[0] = theme.player_ramp(0)
    world.pads[2] = theme.EMPTY_RAMP
    with window.pixel_buffer.drawing():
        world.draw()
    picture = read_frame(window).convert("RGB")

    def colours_at(index: int) -> set[tuple[int, int, int]]:
        column, row = world.screen_point(*RING_SPOTS[index])
        top = NATIVE_H - 1 - row
        box = picture.crop((column - 46, top - 24, column + 46, top + 24))
        return {colour for _, colour in box.getcolors(1 << 16)}

    assert theme.RED in colours_at(0), "player 1's marker"
    assert theme.RED not in colours_at(1) and theme.RED not in colours_at(2)
    assert theme.DUST in colours_at(2), "an open slot's marker is grey"
    world.clear_ring()
    assert world.pads == [None] * 4 and world.ring == [None] * 4


def test_the_camera_leans_and_stands_straight_again(window: Any) -> None:
    from isofightr.scenes.menu_world import MenuWorld
    from isofightr.scenes.menu_world_model import STATIONS, rest_pose

    window.switch_to()
    world = MenuWorld(window.pixel_buffer)
    world.settle("plaza")
    rest = rest_pose(STATIONS["plaza"])
    world.nudge(-16, 14)
    assert world.pose == rest, "it eases there, it does not jump"
    for _ in range(60):
        world.tick()
    assert (world.pose.x, world.pose.y) == (rest.x - 16, rest.y + 14)
    assert world.pose.resting and not world.gliding, "a lean is not a glide"
    world.nudge(0, 0)
    for _ in range(60):
        world.tick()
    assert world.pose == rest
