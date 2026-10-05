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


def make_view(
    window: Any, training: bool = True, players: int = 2, placeholder_art: bool = False
) -> Any:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    stage = load_stage("training_grid")
    view = BattleView(
        window.pixel_buffer,
        stage,
        [load_character("rook")] * players,
        training=training,
        placeholder_art=placeholder_art,
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
    view = make_view(window, placeholder_art=True)
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
    assert view.effects.flash == {1: 5}, "a third of the 15-frame hitlag"
    assert len(view.effects.streaks) == 1
    assert view.effects.shake.offset != (0, 0)
    assert len(view.effects.sparks) == 1
    view.on_draw()
    assert view.hud._damage[1].text == "76%"
    assert view.hud._damage[1].color[:3] != (255, 255, 255)
    shown = [sprite for sprite in view.effect_renderer.sprites if sprite.visible]
    swing = len(active_hitboxes(view.match.fighters[0]))
    assert len(shown) == 2 + swing, "a spark, the launch streak and the swing"

    for _ in range(60):
        ticks(view, 1)
    view.on_draw()
    assert view.effects.sparks == [] and view.effects.shake.offset == (0, 0)
    assert view.effects.streaks == []
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

    view = make_view(window, placeholder_art=True)
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
    view = make_view(window, placeholder_art=True)
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
    view = make_view(window, placeholder_art=True)
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


def test_f10_shows_what_each_player_sent_this_tick(window: Any) -> None:
    view = make_view(window)
    tap(view, keys().F10)
    view.on_key_press(keys().J, 0)
    ticks(view, 1)
    view.on_draw()
    lines = [label.text for label in view._info_lines if label.text]
    assert lines[0].startswith("P1 stick - mod - c - held ATK ")
    assert lines[0].endswith("> attack f1 move jab1")
    assert lines[1].startswith("P2 stick - mod - c - held - ")
    tap(view, keys().F10)
    view.on_draw()
    assert all(label.text == "" for label in view._info_lines)


def test_a_key_tapped_between_two_ticks_still_reaches_the_game(window: Any) -> None:
    """A press and release inside one 16 ms tick used to be lost (decision D-053)."""
    view = make_view(window)
    tap(view, keys().J)
    ticks(view, 1)
    assert (view.match.fighters[0].state, view.match.fighters[0].move_id) == (
        StateId.ATTACK,
        "jab1",
    )


# --- M11: audio ------------------------------------------------------------------------------


def test_a_battle_plays_its_stage_music_and_the_sounds_of_the_fight(window: Any) -> None:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    backend = window.audio.backend
    window.audio.stop_music()
    backend.played.clear()
    view = BattleView(
        window.pixel_buffer,
        load_stage("sky_ruins"),
        [load_character("rook")] * 2,
        seed=4,
        cpus=[9, 9],
    )
    window.show_view(view)
    assert window.audio.song == "sky_ruins"
    for _ in range(600):
        ticks(view, 1)
    heard = set(backend.names())
    assert "sky_ruins" in heard
    assert heard & {"hit_light", "hit_medium", "hit_light_slash", "hit_medium_slash"}
    assert heard & {"swing_light", "swing_medium", "swing_heavy", "special"}
    assert "jump" in heard or "dash" in heard
    pans = {played.pan for played in backend.played if played.name.startswith("swing")}
    assert len(pans) > 1, "sounds are panned by where they happen"
    tap(view, keys().ESCAPE)
    assert backend.names()[-1] == "ui_select"


# --- M10: CPU players ------------------------------------------------------------------------


def test_a_cpu_player_fights_and_its_inputs_are_recorded(window: Any, tmp_path: Any) -> None:
    from isofightr.data.replay_io import load_replay, match_for
    from isofightr.scenes.battle import BattleView
    from isofightr.sim.replay import play_back

    window.switch_to()
    path = tmp_path / "cpu.json"
    view = BattleView(
        window.pixel_buffer,
        load_stage("training_grid"),
        [load_character("rook")] * 2,
        seed=4,
        cpus=[0, 9],
        record=path,
    )
    window.show_view(view)
    assert [view.cpu_level_of(player) for player in (0, 1)] == [0, 9]
    for _ in range(600):
        ticks(view, 1)
    assert view.match.fighters[0].damage > 0.0, "the CPU attacked the idle player"
    view.save_recording()
    replay = load_replay(path)
    assert play_back(match_for(replay), replay), "a CPU's inputs replay exactly"


def test_the_training_dummy_can_act_like_a_cpu(window: Any) -> None:
    from isofightr.ai.dummy import DummyBehavior

    view = make_view(window)
    view.dummy = DummyBehavior.CPU
    view.dummy_level = 3
    start = view.match.fighters[1].pos
    for _ in range(240):
        ticks(view, 1)
    assert view.cpu_level_of(1) == 3 and view.cpu_level_of(0) == 0
    assert view.match.fighters[1].pos != start, "the dummy moves on its own"
    view.restart()
    ticks(view, 2)
    assert view._cpu_match is view.match, "a restarted match gets fresh CPUs"


# --- D-059: hit visuals and the combo counter ------------------------------------------------


def test_a_strong_hit_draws_its_streak_and_the_combo_counter_shows(window: Any) -> None:
    from isofightr.render.effects import ComboReadout

    view = make_view(window)
    view.match.set_damage(1, 80.0)
    view.on_key_press(keys().U, 0)  # forward smash at point-blank range
    ticks(view, 1)
    view.on_key_release(keys().U, 0)
    for _ in range(30):
        ticks(view, 1)
        view.on_draw()
        if view.effects.streaks:
            break
    assert view.effects.streaks, "a KO-strength launch throws speed lines"
    assert view.effects.hit_hitlag[1] >= 8, "and a long freeze"
    view.effects.combos[1] = ComboReadout(3, 21.5)
    view.on_draw()
    assert view.hud._combo[1].text == "3 HITS 21%" and view.hud._combo[0].text == ""


# --- D-060: projectile art, shadows and ground decals ------------------------------------------


@pytest.mark.parametrize(
    ("character", "move", "ground_key"),
    [
        ("rook", "nspecial", "projectile_shadow"),
        ("bramble", "nspecial", "projectile_shadow"),
        ("zephyr", "nspecial", "projectile_shadow"),
        ("mote", "sspecial", "projectile_shadow"),
        ("mote", "dspecial", "decal"),
    ],
)
def test_projectiles_draw_their_own_art_with_a_shadow_or_decal_in_the_world(
    window: Any, character: str, move: str, ground_key: str
) -> None:
    from isofightr.scenes.battle import BattleView
    from isofightr.sim.states.interrupts import start_move

    window.switch_to()
    view = BattleView(
        window.pixel_buffer,
        load_stage("training_grid"),
        [load_character(character), load_character("rook")],
    )
    window.show_view(view)
    start_move(view.match, view.match.fighters[0], move)
    for _ in range(60):
        ticks(view, 1)
        if view.match.projectiles:
            break
    assert view.match.projectiles
    ticks(view, 2)
    view.on_draw()
    assert view.renderer._ground, "a ground item is in the sorted world"
    keys_drawn = [key for key in view.renderer._textures if key[0] == "ground"]
    assert any(key[1][0] == ground_key for key in keys_drawn)
    styled = [key for key in view.effect_renderer._textures if key[0] == "styled"]
    assert bool(styled) == (ground_key != "decal"), "a decal has no sprite in the overlay layer"
    assert not [key for key in view.effect_renderer._textures if key[0] == "projectile"]
    for _ in range(700):
        ticks(view, 1)
        if not view.match.projectiles:
            break
    view.on_draw()
    assert view.match.projectiles or not view.renderer._ground, "gone with its projectile"


# --- M4: shield bubble and overlay ------------------------------------------------------------


def test_a_raised_shield_is_drawn_and_shown_in_the_overlay(window: Any) -> None:
    from isofightr.render.hitbox_overlay import GRAB_LINE, SHIELD_LINE

    view = make_view(window, training=False)
    view.match.fighters[1].pos = Vec3(9.5, 2.5, 0.0)
    view.on_draw()
    plain = frame_bytes(window)
    view.on_key_press(keys().LSHIFT, 0)
    ticks(view, 3)
    fighter = view.match.fighters[0]
    assert fighter.state is StateId.SHIELD
    view.on_draw()
    assert frame_bytes(window) != plain
    assert len([sprite for sprite in view.effect_renderer.sprites if sprite.visible]) == 1
    tap(view, keys().F1)
    view.on_draw()
    assert count_color(window, SHIELD_LINE) > 40

    view.on_key_release(keys().LSHIFT, 0)
    for _ in range(20):
        ticks(view, 1)
    view.on_key_press(keys().L, 0)
    ticks(view, 1)
    view.on_key_release(keys().L, 0)
    for _ in range(5):
        ticks(view, 1)
    assert fighter.state is StateId.GRAB
    view.on_draw()
    assert count_color(window, GRAB_LINE) > 20, "the grab box is out on frame 6"


def test_fighter_info_shows_shield_and_intangibility(window: Any) -> None:
    view = make_view(window)
    view.match.fighters[0].intangible_frames = 12
    tap(view, keys().F2)
    view.on_draw()
    assert view._info_lines[1].text.endswith("shield 50 intang 12")
    assert view._info_lines[3].text.endswith("shield 50")


# --- M5: projectiles ---------------------------------------------------------------------------


def test_a_projectile_is_drawn_and_outlined_in_the_overlay(window: Any) -> None:
    from isofightr.input.devices import ARROWS_NUMPAD, SOLO_KEYBOARD
    from isofightr.render.hitbox_overlay import HITBOX_LINE
    from isofightr.sim.input_frame import Button

    view = make_view(window, training=False)
    view.match.fighters[1].pos = Vec3(9.5, 2.5, 0.0)
    view.on_key_press(keys().K, 0)
    ticks(view, 1)
    view.on_key_release(keys().K, 0)
    for _ in range(18):
        ticks(view, 1)
    assert len(view.match.projectiles) == 1
    view.on_draw()
    shown = [sprite for sprite in view.effect_renderer.sprites if sprite.visible]
    assert len(shown) == 1
    projectile = view.match.projectiles[0]
    position = projectile.pos
    sx, sy = (snap(value) for value in project(position.x, position.y, position.z))
    assert abs(shown[0].center_x - sx) <= 0.5 and abs(shown[0].center_y - sy) <= 0.5
    tap(view, keys().F1)
    view.on_draw()
    assert count_color(window, HITBOX_LINE) > 20

    for bindings, key in ((SOLO_KEYBOARD, keys().T), (ARROWS_NUMPAD, keys().NUM_9)):
        assert (key, Button.TAUNT) in bindings.buttons


# --- packed sprites (M8) ------------------------------------------------------------------


def _costume_color(view: Any, player: int, material: str, slot: int) -> tuple[int, int, int, int]:
    from isofightr.art.palettes import load_palettes, ramp_index
    from isofightr.render.fighter_look import costume_for

    bank = view.renderer.banks["rook"]
    fighter = view.match.fighters[player]
    costume = costume_for(fighter, len(bank.sprite_set.costumes))
    names = [m.name for m in load_palettes("rook").materials]
    colors = bank.sprite_set.costumes[costume][1]
    return (*colors[ramp_index(names.index(material) + 1, slot)], 255)


def test_fighters_with_sprites_are_drawn_in_their_costumes(window: Any) -> None:
    view = make_view(window, training=False)
    assert "rook" in view.renderer.banks
    view.on_draw()
    first = [_costume_color(view, 0, "cloth", slot) for slot in range(4)]
    second = [_costume_color(view, 1, "cloth", slot) for slot in range(4)]
    assert not set(first) & set(second), "player 2 wears another costume"
    assert sum(count_color(window, color) for color in first) > 20
    assert sum(count_color(window, color) for color in second) > 20


def test_hit_flash_and_helpless_tint_the_sprite(window: Any) -> None:
    view = make_view(window, training=False)
    view.on_draw()
    white = count_color(window, (255, 255, 255, 255))
    view.effects.flash[1] = 3
    view.on_draw()
    assert count_color(window, (255, 255, 255, 255)) > white + 100, "a white silhouette"
    view.effects.flash.clear()
    view.on_draw()
    target = view.match.fighters[1]
    cloth = [_costume_color(view, 1, "cloth", slot) for slot in range(4)]
    before = sum(count_color(window, color) for color in cloth)
    target.state = StateId.HELPLESS
    view.on_draw()
    after = sum(count_color(window, color) for color in cloth)
    assert after < before - 20, "darkened (the ring and HUD tag keep the player colour)"


def test_placeholder_art_option_draws_capsules(window: Any) -> None:
    view = make_view(window, training=False, placeholder_art=True)
    assert view.renderer.banks == {}
    view.on_draw()
    assert count_color(window, (232, 59, 59, 255)) > 100


def test_an_animated_move_shows_its_smear_instead_of_a_swing_blob(window: Any) -> None:
    view = make_view(window, training=False)
    attacker = view.match.fighters[0]
    attacker.state, attacker.move_id, attacker.state_frame = StateId.ATTACK, "fsmash", 14
    assert active_hitboxes(attacker), "fsmash is active on frame 14"
    view.on_draw()
    assert len(view.effect_renderer.sprites) == 0, "no blob: the sprite has the smear"


def test_stock_icons_are_the_characters_head(window: Any) -> None:
    from isofightr.art.portraits import ICON_SIZE

    view = make_view(window, training=False)
    icon = view.hud._stock_icons[0][0].texture
    assert icon.size == (ICON_SIZE, ICON_SIZE)
    assert view.hud._stock_icons[1][0].texture is not icon, "player 2 wears another costume"
    placeholder = make_view(window, training=False, placeholder_art=True)
    assert placeholder.hud._stock_icons[0][0].texture.size != (ICON_SIZE, ICON_SIZE)


def test_stepped_zoom_draws_the_world_twice_as_big(window: Any) -> None:
    from isofightr.config import CAMERA_ZOOM_IN_TICKS

    view = make_view(window, training=False)
    first, second = view.match.fighters[:2]
    first.pos, second.pos = P1_POS, P1_POS + Vec3(1.0, 0.0, 0.0)
    view.camera.snap_to(view._camera_targets())
    view.on_draw()
    wide = view._screen_positions([first, second])
    gap = wide[1][0] - wide[0][0]
    tap(view, keys().Z)
    assert view.zoom.enabled and view.status_line() == "stepped zoom on"
    for _ in range(CAMERA_ZOOM_IN_TICKS + 2):
        ticks(view, 1)
    assert view.camera.zoom == 2
    view.on_draw()
    near = view._screen_positions([first, second])
    assert near[1][0] - near[0][0] == pytest.approx(gap * 2, abs=1.0), "markers follow the zoom"
    assert view.renderer.camera.zoom == 2
