"""The backdrop stays behind the stage (decision D-065, M15 group 2): with every stage's
backdrop swapped for solid magenta, no magenta shows through the stage, and nothing but the
stage, its halo and its shadow is drawn over the magenta."""

from dataclasses import replace
from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.sim.math3d import Vec3

pytestmark = pytest.mark.gl
MAGENTA = (255, 0, 255)
OUT_OF_SIGHT = Vec3(200.0, 200.0, 0.0)


def magenta_view(window: Any, stage_id: str, aids: str = "standard") -> Any:
    """A battle on a stage with no ambience, its fighters out of sight, the camera on the
    stage's middle and the backdrop replaced by one magenta picture."""
    import arcade
    from PIL import Image

    from isofightr.scenes.battle import BattleView

    window.switch_to()
    stage = replace(load_stage(stage_id), ambient=None)
    view = BattleView(window.pixel_buffer, stage, [load_character("rook")] * 2)
    view.show_help = False
    view.hud_display = False
    view.settings = replace(view.settings, depth_aids=aids)
    window.show_view(view)
    for fighter in view.match.fighters:
        fighter.pos = OUT_OF_SIGHT
    renderer = view.renderer
    view.camera.clamped = False
    view.camera.x, view.camera.y = renderer._backdrop_reference
    renderer._background.clear()
    renderer._layers = []
    flat = arcade.Texture(Image.new("RGBA", (NATIVE_W, NATIVE_H), (*MAGENTA, 255)))
    renderer._background.append(arcade.Sprite(flat, center_x=NATIVE_W / 2, center_y=NATIVE_H / 2))
    return view


def coverage(view: Any, sprites: Any) -> Any:
    """Return, for the frame, the strongest alpha any of the sprites draws at each pixel."""
    from PIL import Image, ImageChops

    centre_x, centre_y = view.view_centre()
    cover = Image.new("L", (NATIVE_W, NATIVE_H))
    for sprite in sprites:
        if not sprite.visible:
            continue
        alpha = sprite.texture.image.getchannel("A")
        left = NATIVE_W // 2 + round(sprite.center_x - alpha.width / 2 - centre_x)
        top = NATIVE_H // 2 - round(sprite.center_y + alpha.height / 2 - centre_y)
        patch = Image.new("L", (NATIVE_W, NATIVE_H))
        patch.paste(alpha, (left, top))
        cover = ImageChops.lighter(cover, patch)
    return cover


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_no_backdrop_shows_through_the_stage_and_nothing_else_covers_it(
    window: Any, stage_id: str
) -> None:
    from isofightr.capture import read_frame

    view = magenta_view(window, stage_id)
    view.on_draw()
    frame = read_frame(window).convert("RGB")
    renderer = view.renderer
    world = coverage(view, [sprite for sprite in renderer.sprites if sprite.draw_rank >= 0])
    around = coverage(view, renderer._separation)
    pixels, solid, rim = frame.load(), world.load(), around.load()
    shown = holes = strays = 0
    for y in range(NATIVE_H):
        for x in range(NATIVE_W):
            is_backdrop = pixels[x, y] == MAGENTA
            if solid[x, y] == 255:
                shown += 1
                holes += is_backdrop
            elif solid[x, y] == 0 and rim[x, y] == 0:
                strays += not is_backdrop
    assert shown > 2000, "the stage is on the screen"
    assert holes == 0, "the backdrop shows through the stage"
    assert strays == 0, "something other than the stage, its halo and its shadow is drawn"
    assert len(renderer._separation) >= 1, "every stage has its halo"


def test_the_halo_goes_with_the_depth_aids(window: Any) -> None:
    from isofightr.capture import read_frame

    on = magenta_view(window, "sky_ruins")
    on.on_draw()
    with_halo = read_frame(window).convert("RGB")
    off = magenta_view(window, "sky_ruins", "off")
    off.on_draw()
    without = read_frame(window).convert("RGB")
    assert with_halo.tobytes() != without.tobytes()
    world = coverage(off, [sprite for sprite in off.renderer.sprites if sprite.draw_rank >= 0])
    pixels, solid = without.load(), world.load()
    assert all(
        pixels[x, y] == MAGENTA
        for y in range(NATIVE_H)
        for x in range(NATIVE_W)
        if solid[x, y] == 0
    ), "off: the stage alone on its backdrop, as before"


def test_only_water_stages_cast_a_shadow(window: Any) -> None:
    assert len(magenta_view(window, "lily_pads").renderer._separation) == 2
    assert len(magenta_view(window, "sky_ruins").renderer._separation) == 1
