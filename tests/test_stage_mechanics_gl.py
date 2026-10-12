"""Stage mechanics on the screen (decision D-063, M14 group 4): moving platforms as sorted
blocks, hazard marks and effects, the training toggle and the Rules row."""

from dataclasses import replace
from typing import Any

import pytest

from isofightr.config import TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.sim.match import MatchRules
from test_stage_mechanics import BRIDGE, GEYSER, WIND, build

pytestmark = pytest.mark.gl
ON = MatchRules(stocks=None, stage_hazards=True)


def make_view(window: Any, rules: MatchRules = ON, training: bool = False, **stage: object) -> Any:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    view = BattleView(
        window.pixel_buffer,
        build(**stage),
        [load_character("rook")] * 2,
        rules=rules,
        training=training,
    )
    view.show_help = False
    window.show_view(view)
    return view


def step(view: Any, ticks: int) -> None:
    for _ in range(ticks):
        view.on_update(TICK_SECONDS)
    view.on_draw()


def test_a_moving_platforms_cells_are_sprites_that_follow_it(window: Any) -> None:
    view = make_view(window, soft_platforms=[BRIDGE])
    renderer = view.renderer
    assert len(renderer._blocks) == 4, "2 by 2 cells"
    view.on_draw()
    start = {key: sprite.position for key, sprite in renderer._blocks.items()}
    step(view, 60)
    assert view.match.stage is not view.stage and renderer.live is view.match.stage
    for key, sprite in renderer._blocks.items():
        moved = (sprite.position[0] - start[key][0], sprite.position[1] - start[key][1])
        assert moved == (24.0, -12.0), "1.5 units along x: 24 px right and 12 down"
        assert sprite in renderer.sprites and sprite.draw_rank >= 0
    step(view, 180)
    assert {key: sprite.position for key, sprite in renderer._blocks.items()} == start

    resting = make_view(window, MatchRules(stocks=None), soft_platforms=[BRIDGE])
    resting.on_draw()
    before = [sprite.position for sprite in resting.renderer._blocks.values()]
    step(resting, 60)
    assert [sprite.position for sprite in resting.renderer._blocks.values()] == before


def test_a_fighters_shadow_rides_the_platform_it_stands_on(window: Any) -> None:
    from helpers import place
    from isofightr.render.world_renderer import Part

    view = make_view(window, soft_platforms=[BRIDGE])
    rider = view.match.fighters[0]
    place(view.match, rider, 5.0, 5.0)
    step(view, 90)
    shadow = view.renderer._parts[(rider.entity_id, Part.SHADOW)]
    assert shadow.visible and rider.pos.z == 2.5 and rider.pos.x > 7.0
    deck = view.match.stage.soft_platforms[0]
    assert deck.contains(rider.pos.x, rider.pos.y)


def test_hazards_put_a_mark_on_the_ground_then_an_effect_over_it(window: Any) -> None:
    from isofightr.render.hazard_look import HAZARD_DECAL_BASE, STREAKS_ACTIVE

    view = make_view(window, hazards=[GEYSER, WIND | {"at": [7.0, 7.0]}])
    step(view, 100)
    assert view.hazard_renderer.shown == 0 and HAZARD_DECAL_BASE not in view.renderer._ground
    step(view, 110)
    assert HAZARD_DECAL_BASE in view.renderer._ground, "the geyser's warning lies on the ground"
    assert view.renderer._ground[HAZARD_DECAL_BASE].draw_rank >= 0, "sorted with the world"
    step(view, 52)
    shown = view.hazard_renderer.shown
    assert shown == 1 + STREAKS_ACTIVE, "a jet and the wind's streaks"
    visible = [sprite for sprite in view.hazard_renderer.sprites if sprite.visible]
    assert len(visible) == shown
    played = [played.name for played in window.audio.backend.played]
    assert "hazard_warn" in played and "geyser" in played and "gust" in played
    step(view, 40)
    assert view.hazard_renderer.shown == STREAKS_ACTIVE, "the jet is over, the wind still blows"

    quiet = make_view(window, MatchRules(stocks=None), hazards=[GEYSER])
    step(quiet, 262)
    assert quiet.hazard_renderer.shown == 0 and HAZARD_DECAL_BASE not in quiet.renderer._ground


def test_training_can_switch_stage_hazards_while_playing(window: Any) -> None:
    from isofightr.scenes.battle import MENU_HAZARDS
    from isofightr.ui.menu import MenuAction

    view = make_view(window, training=True, soft_platforms=[BRIDGE])
    step(view, 60)
    assert view.match.stage is not view.stage
    view.open_menu()
    item = view.pause_menu.item(MENU_HAZARDS)
    assert item.index == 1 and item.label == "Stage hazards"
    while view.pause_menu.selected.key != MENU_HAZARDS:
        view.pause_menu.move(1)
    view.menu_action(MenuAction.LEFT)
    assert not view.match.rules.stage_hazards
    assert view.match.stage is view.stage, "the platforms are back where they rest"
    view.close_menu()
    step(view, 30)
    assert view.match.stage is view.stage


def test_the_rules_screen_has_the_stage_hazards_row(window: Any, tmp_path: Any) -> None:
    from isofightr.scenes.flow import GameFlow
    from isofightr.settings import load_settings

    window.switch_to()
    path = tmp_path / "settings.toml"
    flow = GameFlow(window, window.pixel_buffer, seed=1, settings_path=path)
    flow.show_rules(cursor="stage_hazards")
    for _ in range(3):
        window.current_view.on_update(TICK_SECONDS)
    window.current_view.on_draw()
    assert flow.setup.stage_hazards
    flow.set_rules(replace(flow.setup, stage_hazards=False))
    assert not load_settings(path).rules.stage_hazards, "saved"
    assert not flow.setup.rules().stage_hazards
