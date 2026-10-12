"""What the renderer draws with the stage art systems (decision D-063, M14 group 1): props in
the sorted world, the faint copy of a fighter behind one, drifting and animated backdrop
layers, ambient sprites and the stage-name intro."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.match import MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import BackgroundLayer

pytestmark = pytest.mark.gl
FAR_AWAY = Vec3(40.0, 40.0, 0.0)
BODY_PART = 2


def make_view(window: Any, stage_id: str = "sky_ruins", rules: MatchRules | None = None) -> Any:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    stage = load_stage(stage_id)
    view = BattleView(window.pixel_buffer, stage, [load_character("rook")] * 2, rules=rules)
    view.show_help = False
    window.show_view(view)
    return view


def test_props_are_sprites_in_the_sorted_world_and_animate(window: Any) -> None:
    view = make_view(window)
    renderer = view.renderer
    names = [prop.art.name for prop in renderer.props]
    assert names[:6] == ["support"] * 6 and {"arch", "arch_broken_r", "banner"} <= set(names)
    assert any(prop.below for prop in renderer.props), "something hangs under the island"
    view.on_draw()
    for sprite in renderer._prop_sprites:
        assert sprite in renderer.sprites and sprite.draw_rank >= 0, "it has a place in the order"
    pennant = renderer._prop_sprites[names.index("banner")]
    column = renderer._prop_sprites[names.index("support")]
    still = column.texture
    seen = set()
    for _ in range(60):
        view.on_update(TICK_SECONDS)
        view.on_draw()
        seen.add(id(pennant.texture))
    assert len(seen) == 3, "the banner's three frames all showed"
    assert column.texture is still


def test_a_fighter_behind_a_prop_shows_through_it(window: Any) -> None:
    view = make_view(window)
    renderer = view.renderer
    # These flowers stand in the open at the island's front edge: nothing else is near.
    column = next(prop for prop in renderer.props if prop.art.name == "flowers")
    fighter, other = view.match.fighters
    other.pos = FAR_AWAY
    fighter.pos = Vec3(column.x - 0.3, column.y - 0.2, 0.0)
    view.on_draw()
    assert renderer._ghost_of[fighter.entity_id].visible, "the faint copy shows them"
    body = renderer._parts[(fighter.entity_id, BODY_PART)]
    prop_sprite = renderer._prop_sprites[column.index]
    order = list(renderer.sprites)
    assert order.index(body) < order.index(prop_sprite), "the flowers are drawn over the fighter"
    fighter.pos = Vec3(column.x + 0.4, column.y + 0.4, 0.0)
    view.on_draw()
    order = list(renderer.sprites)
    assert order.index(body) > order.index(prop_sprite), "in front of it now"
    assert not renderer._ghost_of[fighter.entity_id].visible


def test_cloud_layers_drift_by_themselves(window: Any) -> None:
    renderer = make_view(window).renderer

    def centres(tick: int) -> list[float]:
        renderer._tick = tick
        renderer._place_backdrop((0, 0))
        return [copies[1].center_x for _, _, copies in renderer._layers]

    start, later = centres(0), centres(500)
    widths = [copies[1].width for _, _, copies in renderer._layers]
    moved = [round(a - b) % width for a, b, width in zip(start, later, widths, strict=True)]
    assert moved == [0, 8, 55, 0, 15, 35], (
        "clouds, birds and the two cloud banks drift left; the sky and the islands do not"
    )


def test_a_backdrop_layer_with_frames_plays_them(
    window: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from isofightr.render import world_renderer

    folder = tmp_path / "flicker"
    folder.mkdir()
    strip = Image.new("RGBA", (64, 40), (46, 34, 47, 255))
    strip.paste((255, 255, 255, 255), (0, 20, 64, 40))
    strip.save(folder / "glow.png")
    monkeypatch.setattr(world_renderer, "STAGES_DIR", tmp_path)
    stage = replace(
        load_stage("training_grid"),
        id="flicker",
        backgrounds=(BackgroundLayer("glow.png", 0.0, 0.0, 2, 5),),
    )
    window.switch_to()
    renderer = world_renderer.WorldRenderer(window.pixel_buffer, stage)
    ((_, textures, copies),) = renderer._layers
    assert [texture.height for texture in textures] == [20, 20]
    shown = []
    for tick in (0, 4, 5, 9, 10):
        renderer._tick = tick
        renderer._place_backdrop((0, 0))
        shown.append(textures.index(copies[0].texture))
    assert shown == [0, 0, 1, 1, 0]


def test_ambient_sprites_drift_and_leave_fighters_clear(window: Any) -> None:
    from isofightr.render import ambient

    view = make_view(window)
    renderer = view.renderer
    assert len(renderer._mote_sprites) == 12
    assert len(renderer._motes_front) == 4 and len(renderer._motes_back) == 8
    view.on_draw()
    before = [sprite.position for sprite in renderer._mote_sprites]
    for _ in range(40):
        view.on_update(TICK_SECONDS)
    view.on_draw()
    assert [sprite.position for sprite in renderer._mote_sprites] != before

    # Whatever the tick, a sprite in front that is showing is not on a fighter.
    for _ in range(300):
        view.on_update(TICK_SECONDS)
        view.on_draw()
        centre_x, centre_y = view.view_centre()
        rects = [
            (
                rect.left - centre_x + NATIVE_W / 2,
                rect.bottom - centre_y + NATIVE_H / 2,
                rect.right - centre_x + NATIVE_W / 2,
                rect.top - centre_y + NATIVE_H / 2,
            )
            for rect in renderer._body_rects
        ]
        found = ambient.motes(view.match.stage.ambient, renderer._tick, (centre_x, centre_y))
        for mote, sprite in zip(found, renderer._mote_sprites, strict=True):
            if mote.front and sprite.visible:
                assert not ambient.covers(mote, rects)
    assert not make_view(window, "training_grid").renderer._mote_sprites, "none without a table"


def test_the_stage_name_shows_over_the_countdown_only(window: Any) -> None:
    view = make_view(window, rules=MatchRules(countdown_frames=180))
    intro = view.extras.intro
    for _ in range(40):
        view.on_update(TICK_SECONDS)
    view.on_draw()
    assert intro.text == "SKY RUINS" and intro.alpha == 255
    for _ in range(150):
        view.on_update(TICK_SECONDS)
    view.on_draw()
    assert intro.alpha == 0, "gone when the fight starts"
    sandbox = make_view(window)
    for _ in range(40):
        sandbox.on_update(TICK_SECONDS)
    sandbox.on_draw()
    assert sandbox.extras.intro.alpha == 0, "no countdown, no intro"


def test_ground_props_lie_under_the_fighters_and_pulse(window: Any) -> None:
    from isofightr.render.props import GROUND_PROP_BASE

    view = make_view(window, "final_plateau")
    renderer = view.renderer
    view.on_draw()
    flat = [renderer._ground[GROUND_PROP_BASE + index] for index in range(9)]
    sigil = flat[0]
    assert all(sprite in renderer.sprites for sprite in flat)
    # A fighter standing on the seal is drawn after it, wherever on it they stand.
    for x, y in ((7.0, 5.0), (6.0, 4.0), (8.2, 6.1), (6.0, 6.0)):
        view.match.fighters[0].pos = Vec3(x, y, 0.0)
        view.on_draw()
        body = renderer._parts[(0, BODY_PART)]
        assert body.draw_rank > sigil.draw_rank, f"standing at {x}, {y}"
    seen = set()
    for _ in range(130):
        view.on_update(TICK_SECONDS)
        view.on_draw()
        seen.add(id(sigil.texture))
    assert len(seen) == 4, "all four frames of its pulse showed"
    view.settings = replace(view.settings, reduce_flashing=True)
    held = set()
    for _ in range(70):
        view.on_update(TICK_SECONDS)
        view.on_draw()
        held.add(id(sigil.texture))
    assert len(held) == 1, "reduce flashing: the runes hold still"
