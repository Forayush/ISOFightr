"""The depth aids on the screen (decision D-065, M15 group 1): the dashed ring over the void,
the height line, markers the stage cannot hide, the outline of a hidden fighter, the grid of
the "strong" setting, and "off" drawing the world as it was."""

from dataclasses import replace
from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, OCCLUDED_FIGHTER_ALPHA, Z_PX
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render.iso import project
from isofightr.sim.math3d import Vec3

pytestmark = pytest.mark.gl
RED = (232, 59, 59)
ON_GROUND = (8.5, 5.5, 0.0)
OFF_STAGE = (11.5, 8.5, 3.0)
"""D-065's pair on Sky Ruins: the same pixels, one on the island and one in the air off it."""
BEHIND_A_PLATFORM = (0.5, 6.5, 0.0)
UNDER_THE_ISLAND = (6.5, 4.5, -5.0)


def make_view(window: Any, aids: str = "standard", training: bool = False) -> Any:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    view = BattleView(
        window.pixel_buffer,
        load_stage("sky_ruins"),
        [load_character("rook")] * 2,
        training=training,
    )
    view.show_help = False
    view.hud_display = False
    view.settings = replace(view.settings, depth_aids=aids)
    window.show_view(view)
    return view


def show(view: Any, spot: tuple[float, float, float]) -> Any:
    """Put player 1 at a spot (player 2 far away on the island), draw, and return the frame."""
    from isofightr.capture import read_frame

    first, second = view.match.fighters[0], view.match.fighters[1]
    first.pos, second.pos = Vec3(*spot), Vec3(6.5, 7.5, 0.0)
    view.camera.clamped = False
    view.camera.x, view.camera.y = project(8.5, 5.5, 0.0)
    view.on_draw()
    return read_frame(view.window).convert("RGB")


def on_frame(view: Any, world_x: float, world_y: float) -> tuple[int, int]:
    """Return where a world pixel is in the frame (rows count down)."""
    centre_x, centre_y = view.view_centre()
    return (NATIVE_W // 2 + round(world_x - centre_x), NATIVE_H // 2 - round(world_y - centre_y))


def reds(frame: Any, left: int, top: int, right: int, bottom: int) -> int:
    box = frame.crop((left, top, right, bottom))
    return sum(1 for pixel in box.getdata() if pixel == RED)


def parts(view: Any) -> Any:
    from isofightr.render.world_renderer import Part

    renderer = view.renderer
    entity = view.match.fighters[0].player_index
    found = {part: renderer._parts.get((entity, part)) for part in Part}
    return found, renderer


def test_a_fighter_over_the_void_has_a_dashed_ring_on_the_plane_below(window: Any) -> None:
    from isofightr.render.world_renderer import Part

    view = make_view(window)
    frame = show(view, OFF_STAGE)
    found, _ = parts(view)
    ring = found[Part.SHADOW]
    assert ring.visible and ring.position == project(11.5, 8.5, 0.0), "on the reference plane"
    assert ring.draw_rank >= 0, "sorted with the world"
    x, y = on_frame(view, *project(11.5, 8.5, 0.0))
    assert reds(frame, x - 10, y - 5, x + 10, y + 5) >= 16, "the ring's own pixels, in red"
    feet_x, feet_y = on_frame(view, *project(*OFF_STAGE))
    assert y - feet_y == 3 * Z_PX, "three units below the feet on the screen"

    grounded = show(view, ON_GROUND)
    assert found[Part.SHADOW].position == project(*ON_GROUND), "under the feet on the ground"
    assert (feet_x, feet_y) == on_frame(view, *project(*ON_GROUND)), "the twin: the same pixels"
    assert reds(grounded, x - 10, y - 5, x + 10, y + 5) == 0, "and nothing out there now"


def test_a_height_line_joins_the_feet_to_the_marker_only_in_the_air(window: Any) -> None:
    from isofightr.render.world_renderer import Part

    view = make_view(window)
    frame = show(view, OFF_STAGE)
    found, _ = parts(view)
    line = found[Part.LINE]
    assert line.visible and line.texture.height == 3 * Z_PX and line.texture.width == 1
    x, feet_y = on_frame(view, *project(*OFF_STAGE))
    column = [frame.getpixel((x, feet_y + row)) for row in range(4, 3 * Z_PX - 6)]
    assert column.count(RED) >= len(column) // 2 - 1, "a red dot every other pixel"

    grounded = show(view, ON_GROUND)
    assert not found[Part.LINE].visible
    column = [grounded.getpixel((x, feet_y + row)) for row in range(12, 3 * Z_PX - 6)]
    assert RED not in column

    show(view, (8.5, 5.5, 0.9))
    assert not found[Part.LINE].visible, "a short hop has none"
    show(view, (8.5, 5.5, 2.0))
    assert found[Part.LINE].visible and found[Part.LINE].texture.height == 2 * Z_PX
    assert found[Part.SHADOW].position == project(8.5, 5.5, 0.0), "over ground: the usual shadow"


def test_a_marker_behind_a_platform_is_still_drawn(window: Any) -> None:
    from isofightr.render.world_renderer import Part

    view = make_view(window)
    frame = show(view, BEHIND_A_PLATFORM)
    _, renderer = parts(view)
    entity = view.match.fighters[0].player_index
    over = renderer._covered_of[(entity, Part.SHADOW)]
    assert over.visible, "the stage is in front of the ring: its thinned copy shows"
    x, y = on_frame(view, *project(*BEHIND_A_PLATFORM))
    shown = reds(frame, x - 10, y - 5, x + 10, y + 5)
    assert shown >= 8

    off = make_view(window, "off")
    hidden = reds(show(off, BEHIND_A_PLATFORM), x - 10, y - 5, x + 10, y + 5)
    assert hidden < shown, "which the old picture hid"

    show(view, ON_GROUND)
    assert not over.visible, "in the open there is nothing to redraw"


def test_a_hidden_fighter_is_outlined_in_its_players_colour(window: Any) -> None:
    from isofightr.render.world_renderer import Part

    view = make_view(window)
    show(view, BEHIND_A_PLATFORM)
    found, renderer = parts(view)
    entity = view.match.fighters[0].player_index
    ghost, body = renderer._ghost_of[entity], found[Part.BODY]
    assert ghost.visible and ghost.alpha == 255
    assert ghost.texture.width == body.texture.width + 2, "one pixel bigger on every side"
    colours = {pixel[:3] for pixel in ghost.texture.image.getdata() if pixel[3] == 255}
    assert colours == {RED}, "the only solid pixels are the outline"
    show(view, ON_GROUND)
    assert not ghost.visible


def test_under_the_island_the_marker_is_on_the_ground_above(window: Any) -> None:
    from isofightr.render.world_renderer import Part

    view = make_view(window)
    show(view, UNDER_THE_ISLAND)
    found, renderer = parts(view)
    entity = view.match.fighters[0].player_index
    assert found[Part.SHADOW].position == project(6.5, 4.5, 0.0)
    assert not found[Part.LINE].visible, "the line would pass through solid ground"
    assert renderer._covered_of[(entity, Part.LINE)].visible, "so it is drawn over it, thinner"
    assert renderer._covered_of[(entity, Part.LINE)].texture.height == 5 * Z_PX


def test_strong_adds_a_grid_on_the_plane_around_a_fighter_off_the_stage(window: Any) -> None:
    from isofightr.render.world_renderer import Part

    strong = make_view(window, "strong")
    show(strong, OFF_STAGE)
    found, _ = parts(strong)
    grid = found[Part.GRID]
    assert grid is not None and grid.visible and grid.draw_rank >= 0
    assert grid.texture.width == 7 * 32, "three cells each way from the fighter's"
    show(strong, ON_GROUND)
    assert not grid.visible, "nothing while the fighter is over ground"

    standard = make_view(window)
    show(standard, OFF_STAGE)
    assert parts(standard)[0][Part.GRID] is None


def test_off_draws_the_world_as_it_was(window: Any) -> None:
    """Depth aids off is the picture from before M15: no marker over the void, no line, the
    faint copy of a hidden fighter, and for a fighter standing in the open the same pixels as
    the standard setting gives."""
    from isofightr.render.world_renderer import Part

    off = make_view(window, "off")
    standing = show(off, ON_GROUND)
    found, renderer = parts(off)
    entity = off.match.fighters[0].player_index
    assert found[Part.SHADOW].visible and found[Part.LINE] is None and not renderer._covered_of
    show(off, OFF_STAGE)
    assert not found[Part.SHADOW].visible, "absent over the void (D-021)"
    show(off, BEHIND_A_PLATFORM)
    ghost = renderer._ghost_of[entity]
    assert ghost.visible and ghost.alpha == OCCLUDED_FIGHTER_ALPHA
    assert ghost.texture is found[Part.BODY].texture, "the same picture, faint (D-025)"

    standard = make_view(window)
    with_halo = show(standard, ON_GROUND)
    assert with_halo.tobytes() != standing.tobytes(), "standard also rims the island"
    standard.renderer._separation.clear()
    assert show(standard, ON_GROUND).tobytes() == standing.tobytes(), "and nothing else differs"


def test_the_training_menu_changes_the_depth_aids(window: Any) -> None:
    from isofightr.scenes.battle import MENU_DEPTH
    from isofightr.ui.menu import MenuAction

    view = make_view(window, training=True)
    view.open_menu()
    row = view.pause_menu.item(MENU_DEPTH)
    assert row.value == "standard"
    while view.pause_menu.selected.key != MENU_DEPTH:
        view.menu_action(MenuAction.DOWN)
    view.menu_action(MenuAction.RIGHT)
    assert view.settings.depth_aids == "strong"
    view.menu_action(MenuAction.LEFT)
    view.menu_action(MenuAction.LEFT)
    assert view.settings.depth_aids == "off"
    view.close_menu()
    show(view, OFF_STAGE)
    assert view.renderer.depth_aids == "off"
