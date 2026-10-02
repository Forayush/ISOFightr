"""Battle scene tests for M3's presentation and training tools: need a real OpenGL window
(``pytest -m gl``).

Plan note "13 - Game Modes UI and Flow" (training mode keys, HUD) and the M3 exit criterion
"the hitbox overlay matches the visuals".
"""

from typing import Any

import pytest

from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.data.validation import DataError
from isofightr.render.camera import snap
from isofightr.render.iso import project
from isofightr.sim.combat.hitbox import active_hitboxes
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import ZERO3, Vec3

pytestmark = pytest.mark.gl

P1_POS = Vec3(4.5, 6.5, 0.0)
P2_POS = Vec3(5.5, 6.5, 0.0)


def make_view(window: Any, training: bool = True, players: int = 2) -> Any:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    stage = load_stage("training_grid")
    view = BattleView(
        window.pixel_buffer, stage, [load_character("rook")] * players, training=training
    )
    window.show_view(view)
    first, second = view.match.fighters[:2]
    first.pos, first.facing = P1_POS, Dir8.SE
    second.pos, second.facing = P2_POS, Dir8.NW
    view.camera.snap_to([P1_POS])
    return view


def keys() -> Any:
    """Arcade's key codes, imported lazily: collecting this file must not load ``arcade``,
    because the default (CI) test run has no display."""
    import arcade

    return arcade.key


def ticks(view: Any, count: int) -> None:
    view.on_update(TICK_SECONDS * count)


def tap(view: Any, key: int) -> None:
    view.on_key_press(key, 0)
    view.on_key_release(key, 0)


def frame_bytes(window: Any) -> bytes:
    return bytes(window.pixel_buffer.framebuffer.read(components=4))


def pixel_at(window: Any, view: Any, world: Vec3) -> tuple[int, ...]:
    """Read the native pixel under a world point."""
    centre = view.camera.pixel_centre
    sx, sy = (snap(value) for value in project(world.x, world.y, world.z))
    x = sx - centre[0] + NATIVE_W // 2
    y = sy - centre[1] + NATIVE_H // 2
    return tuple(window.pixel_buffer.framebuffer.read(viewport=(x, y, 1, 1), components=4))


def count_color(window: Any, color: tuple[int, int, int, int]) -> int:
    data = frame_bytes(window)
    target = bytes(color[:3])
    return sum(data[index : index + 3] == target for index in range(0, len(data), 4))


# --- training dummy -----------------------------------------------------------------------


def test_training_dummy_ignores_its_keys_until_handed_control(window: Any) -> None:
    view = make_view(window)
    dummy = view.match.fighters[1]
    view.on_key_press(keys().NUM_0, 0)  # player 2's jump key
    ticks(view, 6)
    assert dummy.state is StateId.IDLE
    tap(view, keys().TAB)
    assert not view.dummies
    ticks(view, 6)
    assert dummy.state in (StateId.JUMP_SQUAT, StateId.JUMP)


def test_outside_training_player_two_plays_and_training_keys_do_nothing(window: Any) -> None:
    view = make_view(window, training=False)
    tap(view, keys().EQUAL)
    assert view.match.fighters[1].damage == 0
    view.on_key_press(keys().NUM_0, 0)
    ticks(view, 6)
    assert view.match.fighters[1].state in (StateId.JUMP_SQUAT, StateId.JUMP)


def test_dummy_damage_keys(window: Any) -> None:
    view = make_view(window, players=3)
    for _ in range(3):
        tap(view, keys().EQUAL)
    tap(view, keys().MINUS)
    assert [fighter.damage for fighter in view.match.fighters] == [0.0, 20.0, 20.0]
    view.on_draw()
    assert view.hud._damage[1].text == "20%" and view.hud._damage[0].text == "0%"
    assert view.status_line() == "dummy damage 20%"
    tap(view, keys().MINUS)
    tap(view, keys().MINUS)
    tap(view, keys().MINUS)
    assert view.match.fighters[1].damage == 0.0, "never below zero"
    tap(view, keys().EQUAL)
    tap(view, keys().KEY_0)
    assert view.match.fighters[1].damage == 0.0


# --- pause and frame advance --------------------------------------------------------------


def test_pause_stops_the_match_and_frame_advance_steps_it(window: Any) -> None:
    view = make_view(window)
    ticks(view, 3)
    assert view.match.frame == 3
    tap(view, keys().F5)
    ticks(view, 10)
    assert view.match.frame == 3 and view.paused
    assert view.status_line().startswith("PAUSED frame 3")
    tap(view, keys().F6)
    ticks(view, 10)
    assert view.match.frame == 4, "exactly one frame per press"
    tap(view, keys().F6)
    tap(view, keys().F6)
    ticks(view, 5)
    assert view.match.frame == 5, "presses do not queue up"
    tap(view, keys().F5)
    ticks(view, 2)
    assert view.match.frame == 7 and not view.paused


def test_frame_advance_pauses_a_running_match(window: Any) -> None:
    view = make_view(window)
    ticks(view, 2)
    tap(view, keys().F6)
    ticks(view, 5)
    assert view.paused and view.match.frame == 3


def test_inputs_held_while_frame_advancing_reach_the_sim(window: Any) -> None:
    view = make_view(window)
    tap(view, keys().F5)
    view.on_key_press(keys().J, 0)
    tap(view, keys().F6)
    ticks(view, 1)
    attacker = view.match.fighters[0]
    assert (attacker.state, attacker.move_id, attacker.state_frame) == (StateId.ATTACK, "jab1", 1)


# --- hits: HUD, sparks, flash, shake ------------------------------------------------------


def test_a_hit_updates_the_hud_and_spawns_feedback(window: Any) -> None:
    view = make_view(window)
    view.match.set_damage(1, 60.0)
    view.on_draw()
    assert view.hud._damage[1].text == "60%"
    quiet = len([sprite for sprite in view.effect_renderer.sprites if sprite.visible])
    assert quiet == 0

    view.on_key_press(keys().U, 0)  # forward smash
    ticks(view, 1)
    view.on_key_release(keys().U, 0)
    ticks(view, 13)
    target = view.match.fighters[1]
    assert target.damage == pytest.approx(76.8) and target.hitlag > 0
    assert view.effects.flash == {1: 3}
    assert view.effects.shake.offset != (0, 0)
    assert len(view.effects.sparks) == 1
    view.on_draw()
    assert view.hud._damage[1].text == "76%"
    assert view.hud._damage[1].color[:3] != (255, 255, 255)
    shown = [sprite for sprite in view.effect_renderer.sprites if sprite.visible]
    assert len(shown) == 1 + len(active_hitboxes(view.match.fighters[0])), "a spark and the swing"

    for _ in range(60):
        ticks(view, 1)
    view.on_draw()
    assert view.effects.sparks == [] and view.effects.shake.offset == (0, 0)
    assert not [sprite for sprite in view.effect_renderer.sprites if sprite.visible]


def test_screen_shake_moves_the_picture_but_not_the_sim_camera(window: Any) -> None:
    view = make_view(window)
    view.on_draw()
    still = frame_bytes(window)
    centre = view.camera.pixel_centre
    view.effects.shake.start(3)
    view.on_draw()
    assert frame_bytes(window) != still
    assert view.camera.pixel_centre == centre
    view.effects.clear()
    view.on_draw()
    assert frame_bytes(window) == still


def test_restart_clears_the_effects(window: Any) -> None:
    view = make_view(window)
    view.effects.shake.start(4)
    view.match.set_damage(1, 50.0)
    tap(view, keys().F8)
    assert view.effects.shake.offset == (0, 0) and view.match.fighters[1].damage == 0


# --- F1 hitbox overlay --------------------------------------------------------------------


def test_hitbox_overlay_draws_hurtboxes_and_active_hitboxes_where_they_are(window: Any) -> None:
    from isofightr.render.hitbox_overlay import HITBOX_LINE, HURTBOX_LINE

    view = make_view(window)
    view.match.fighters[1].pos = Vec3(9.5, 2.5, 0.0)  # out of reach
    view.on_draw()
    assert count_color(window, HURTBOX_LINE) == 0 and count_color(window, HITBOX_LINE) == 0
    tap(view, keys().F1)
    view.on_draw()
    assert count_color(window, HURTBOX_LINE) > 40
    assert count_color(window, HITBOX_LINE) == 0, "no attack is out"

    view.on_key_press(keys().U, 0)
    ticks(view, 1)
    view.on_key_release(keys().U, 0)
    ticks(view, 13)
    attacker = view.match.fighters[0]
    boxes = active_hitboxes(attacker)
    assert len(boxes) == 2
    view.camera.snap_to([P1_POS])
    view.on_draw()
    assert count_color(window, HITBOX_LINE) > 40
    # The overlay is drawn from the sim's own shapes: its fill covers each hitbox centre.
    for box in boxes:
        red, green, blue, _ = pixel_at(window, view, box.centre)
        assert red > 200 and green < 190 and blue < 190, (red, green, blue)

    tap(view, keys().F1)
    view.on_draw()
    assert count_color(window, HURTBOX_LINE) == 0 and count_color(window, HITBOX_LINE) == 0


def test_the_attack_swing_is_drawn_exactly_where_the_hitbox_is(window: Any) -> None:
    """M3 exit criterion: the hitbox overlay matches the visuals."""
    view = make_view(window)
    view.match.fighters[1].pos = Vec3(9.5, 2.5, 0.0)
    view.on_key_press(keys().U, 0)
    ticks(view, 1)
    view.on_key_release(keys().U, 0)
    ticks(view, 13)
    view.on_draw()
    boxes = active_hitboxes(view.match.fighters[0])
    shown = [sprite for sprite in view.effect_renderer.sprites if sprite.visible]
    assert len(shown) == len(boxes) == 2
    for sprite, box in zip(shown, boxes, strict=True):
        sx, sy = (snap(value) for value in project(box.centre.x, box.centre.y, box.centre.z))
        assert abs(sprite.center_x - sx) <= 0.5 and abs(sprite.center_y - sy) <= 0.5
        assert (sprite.width, sprite.height) == (
            pytest.approx(sprite.texture.width),
            pytest.approx(sprite.texture.height),
        )


# --- fighter looks ------------------------------------------------------------------------


def test_a_knocked_down_fighter_is_drawn_lying_down(window: Any) -> None:
    view = make_view(window)
    target = view.match.fighters[1]
    view.on_draw()
    head = Vec3(P2_POS.x, P2_POS.y, 2.2)
    standing = pixel_at(window, view, head)
    target.state, target.state_frame = StateId.KNOCKDOWN, 1
    view.on_draw()
    assert pixel_at(window, view, head) != standing, "nothing up at head height any more"
    assert target.vel == ZERO3


# --- F9 hot reload ------------------------------------------------------------------------


def test_reload_swaps_in_fresh_data_and_reports_it(window: Any) -> None:
    view = make_view(window)
    before = view.match.fighters[0].character
    tap(view, keys().F9)
    after = view.match.fighters[0].character
    assert after is not before and after.id == "rook"
    assert view.characters[0] is after
    assert view.status_line() == "reloaded rook"
    for _ in range(200):
        ticks(view, 1)
    assert view.status_line() == "", "the message goes away"


def test_a_failed_reload_keeps_the_match_and_shows_the_error(
    window: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import isofightr.scenes.battle as battle

    def broken(character_id: str) -> None:
        raise DataError("fsmash.toml: windows[0]: unknown key(s) 'kgb'")

    view = make_view(window)
    before = view.match.fighters[0].character
    monkeypatch.setattr(battle, "load_character", broken)
    tap(view, keys().F9)
    assert view.match.fighters[0].character is before
    assert view.status_line().startswith("reload FAILED: fsmash.toml")
    view.on_draw()
    ticks(view, 3)
    assert view.match.frame == 3


# --- debug text ---------------------------------------------------------------------------


def test_fighter_info_has_a_combat_line_and_help_can_be_hidden(window: Any) -> None:
    view = make_view(window)
    view.match.set_damage(1, 42.5)
    tap(view, keys().F2)
    view.on_draw()
    lines = [label.text for label in view._info_lines]
    assert lines[0].startswith("P1 idle") and lines[2].startswith("P2 idle")
    assert lines[1].startswith("   dmg 0.0 move - hitlag 0 hitstun 0 kb 0.0")
    assert lines[3].startswith("   dmg 42.5 move -")
    assert [label.text for label in view._help][-1].startswith("WASD move")
    assert view._help[0].text.startswith("TRAINING")
    tap(view, keys().H)
    view.on_draw()
    assert all(label.text == "" for label in view._help)
