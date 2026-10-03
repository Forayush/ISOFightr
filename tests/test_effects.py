"""Tests for hit feedback state, fighter looks, the damage HUD colors and the hitbox overlay
geometry: the parts of M3's presentation that need no window.

Plan notes "03 - Isometric World and Rendering" (screen shake, hit sparks, hit flash, hitlag
shake) and "13 - Game Modes UI and Flow" (HUD damage %, F1 hitboxes).
"""

import itertools
import math

import pytest

from helpers import hold, make_match, neutral, place, run
from isofightr.config import NATIVE_W, TILE_W, Z_PX
from isofightr.render import effects as fx
from isofightr.render import placeholder_art as art
from isofightr.render.effects import BattleEffects, ScreenShake, Spark
from isofightr.render.fighter_look import DEFAULT_LOOK, FighterLook, Pose, fighter_look
from isofightr.render.iso import project
from isofightr.sim.combat.hitbox import hurtbox
from isofightr.sim.events import ClankEvent, HitEvent, JumpEvent, JumpKind, KoEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Button, Dir8
from isofightr.sim.match import Match
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect

ORIGIN = Vec3(4.0, 6.0, 1.2)


def hit(knockback: float, damage: float = 10.0, target: int = 1) -> HitEvent:
    return HitEvent(
        attacker=0,
        target=target,
        move_id="ftilt",
        damage=damage,
        knockback=knockback,
        position=ORIGIN,
        effect=Effect.SLASH,
        hitlag=10,
    )


def duel(damage: float = 0.0) -> tuple[Match, Fighter, Fighter]:
    match = make_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0, facing=Dir8.NW, damage=damage)
    return match, attacker, target


# --- sparks -------------------------------------------------------------------------------


def test_spark_tier_grows_with_knockback() -> None:
    assert [fx.spark_tier(kb) for kb in (0, 39.9, 40, 79, 80, 149, 150, 400)] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
    ]


def test_a_hit_spawns_a_spark_at_the_hit_point_that_plays_and_goes_away() -> None:
    effects = BattleEffects()
    effects.consume([hit(100.0)])
    [spark] = effects.sparks
    assert (spark.position, spark.tier, spark.effect, spark.frame) == (ORIGIN, 2, Effect.SLASH, 0)
    frames = []
    for _ in range(fx.SPARK_LIFETIME - 1):
        effects.tick()
        frames.append(effects.sparks[0].frame)
    assert frames == [0, 0, 1, 1, 1, 2, 2, 2]
    effects.tick()
    assert effects.sparks == []


def test_clanks_spark_too_and_other_events_do_not() -> None:
    effects = BattleEffects()
    effects.consume([ClankEvent(0, ORIGIN), JumpEvent(0, next(iter(JumpKind)), ORIGIN)])
    assert effects.sparks == [Spark(ORIGIN, fx.CLANK_SPARK_TIER, Effect.NORMAL)]
    assert effects.shake.current() == 0 and effects.flash == {}


# --- screen shake -------------------------------------------------------------------------


def test_weak_hits_do_not_shake_and_strong_hits_shake_more() -> None:
    assert fx.shake_pixels(39.0) == 0
    assert fx.shake_pixels(40.0) == 1
    assert fx.shake_pixels(100.0) == 2
    assert fx.shake_pixels(1000.0) == fx.SHAKE_MAX_PIXELS == 4


def test_shake_alternates_fades_out_and_ends() -> None:
    shake = ScreenShake()
    assert shake.offset == (0, 0)
    shake.start(4)
    offsets = []
    for _ in range(shake.frames + 2):
        offsets.append(shake.offset)
        shake.tick()
    assert offsets[0] == (0, 4) and offsets[2] == (0, -4), "flips every two ticks"
    assert all(x == 0 for x, _ in offsets), "vertical only"
    sizes = [abs(y) for _, y in offsets]
    assert sizes == sorted(sizes, reverse=True) and sizes[-1] == 0
    assert sizes[shake.frames - 1] == 1, "still visible on its last frame"


def test_a_weaker_hit_does_not_cut_a_strong_shake_short() -> None:
    shake = ScreenShake()
    shake.start(4)
    shake.tick()
    shake.start(1)
    assert shake.amplitude == 4 and shake.age == 1
    shake.start(4)
    assert shake.age == 0, "an equal or stronger one restarts it"


def test_hits_and_kos_shake_the_screen() -> None:
    effects = BattleEffects()
    effects.consume([hit(30.0)])
    assert effects.shake.current() == 0
    effects.consume([hit(120.0)])
    assert effects.shake.current() == 2
    effects.consume([KoEvent(1, ORIGIN, Vec3(1.0, 0.0, 0.0), None)])
    assert effects.shake.current() == fx.KO_SHAKE_PIXELS


# --- flash and HUD pop --------------------------------------------------------------------


def test_the_target_flashes_for_three_ticks() -> None:
    effects = BattleEffects()
    effects.consume([hit(50.0, target=1)])
    assert effects.flash == {1: 3}
    for left in (2, 1):
        effects.tick()
        assert effects.flash == {1: left}
    effects.tick()
    assert effects.flash == {}


def test_a_hit_on_an_invincible_target_does_not_flash_or_pop() -> None:
    effects = BattleEffects()
    effects.consume([hit(0.0, damage=0.0)])
    assert effects.flash == {} and effects.hud_pop == {}
    assert len(effects.sparks) == 1


def test_the_damage_number_pops_more_for_bigger_hits() -> None:
    effects = BattleEffects()
    effects.consume([hit(50.0, damage=2.0, target=0), hit(50.0, damage=16.0, target=1)])
    assert effects.hud_pop[0][1] < effects.hud_pop[1][1] <= fx.HUD_POP_MAX_PIXELS
    offsets = set()
    for _ in range(fx.HUD_POP_FRAMES + 1):
        offsets.add(effects.hud_offset(1))
        effects.tick()
    assert offsets == {0, effects_pixels(16.0)}
    assert effects.hud_offset(1) == 0 and effects.hud_offset(3) == 0


def effects_pixels(damage: float) -> int:
    return min(1 + round(damage / fx.HUD_POP_DAMAGE_PER_PIXEL), fx.HUD_POP_MAX_PIXELS)


def test_clear_drops_everything() -> None:
    effects = BattleEffects()
    effects.consume([hit(200.0)])
    effects.clear()
    assert (effects.sparks, effects.flash, effects.hud_pop) == ([], {}, {})
    assert effects.shake.offset == (0, 0)


def test_effects_follow_a_real_match() -> None:
    match, _, target = duel(damage=100.0)
    effects = BattleEffects()
    seen_spark = False
    for frame in hold(buttons=Button.STRONG, frames=1) + neutral(20):
        run(match, [frame])
        effects.tick()
        effects.consume(match.events)
        seen_spark = seen_spark or bool(effects.sparks)
    assert seen_spark and effects.shake.amplitude == fx.SHAKE_MAX_PIXELS
    assert target.damage > 100


# --- fighter look -------------------------------------------------------------------------


def test_a_fighter_normally_just_stands() -> None:
    match, attacker, _ = duel()
    assert (
        fighter_look(attacker, match.frame) == DEFAULT_LOOK == FighterLook(Pose.STAND, 0, False, 0)
    )


def test_the_victim_shakes_during_hitlag_and_the_attacker_does_not() -> None:
    match, attacker, target = duel()
    run(match, hold(buttons=Button.ATTACK, frames=1) + neutral(2))
    assert attacker.hitlag > 0 and target.hitlag > 0
    offsets = [fighter_look(target, frame).offset_x for frame in range(8)]
    assert offsets == [-1, -1, 1, 1, -1, -1, 1, 1]
    assert fighter_look(attacker, match.frame).offset_x == 0


def test_flash_frames_and_charging_make_the_sprite_white() -> None:
    match, attacker, target = duel()
    assert fighter_look(target, 0, flash_frames=2).flash
    run(match, hold(buttons=Button.STRONG, frames=20))
    assert attacker.charge_frames > 0
    blinks = [fighter_look(attacker, frame).flash for frame in range(6)]
    assert blinks == [True, True, True, False, False, False]


def test_tumble_spins_and_knockdown_lies_down() -> None:
    match, _, target = duel(damage=60.0)
    run(match, hold(buttons=Button.STRONG, frames=1) + neutral(30))
    assert target.state is StateId.TUMBLE
    look = fighter_look(target, match.frame)
    assert look.pose is Pose.TUMBLE
    turns = set()
    for _ in range(20):
        run(match, neutral(1))
        if target.state is StateId.TUMBLE:
            turns.add(fighter_look(target, match.frame).quarter_turns)
    assert len(turns) >= 3 and turns <= {0, 1, 2, 3}
    for _ in range(200):
        if target.state is StateId.KNOCKDOWN:
            break
        run(match, neutral(1))
    assert fighter_look(target, match.frame).pose is Pose.DOWN
    for _ in range(100):
        if target.state is StateId.GETUP:
            break
        run(match, neutral(1))
    assert fighter_look(target, match.frame).pose is Pose.DOWN, "still down as getup starts"
    run(match, neutral(15))
    assert target.state is StateId.GETUP
    assert fighter_look(target, match.frame).pose is Pose.STAND


# --- placeholder art for M3 ---------------------------------------------------------------


def opaque_box(image) -> tuple[int, int, int, int]:  # type: ignore[no-untyped-def]
    box = image.getchannel("A").getbbox()
    assert box is not None
    return box


def test_flash_keeps_the_silhouette_and_paints_it_white() -> None:
    normal = art.build_fighter(0, Dir8.SE)
    flashed = art.build_fighter(0, Dir8.SE, flash=True)
    assert flashed.getchannel("A").tobytes() == normal.getchannel("A").tobytes()
    colors = {pixel[:3] for pixel in flashed.getdata() if pixel[3]}
    assert colors == {(255, 255, 255)}


def test_lying_pose_is_low_and_wide_on_the_same_feet_row() -> None:
    standing = opaque_box(art.build_fighter(1, Dir8.SE))
    lying = opaque_box(art.build_fighter(1, Dir8.SE, lying=True))
    feet_row = art.FIGHTER_CANVAS - art.FIGHTER_PIVOT_FROM_BOTTOM
    assert lying[3] == standing[3] == feet_row
    assert lying[2] - lying[0] == art.BODY_HEIGHT
    assert lying[3] - lying[1] == art.BODY_HALF_WIDTH * 2


def test_quarter_turns_rotate_the_sprite_about_its_middle() -> None:
    upright = art.build_fighter(0, Dir8.SE)
    sideways = art.build_fighter(0, Dir8.SE, quarter_turns=1)
    flipped = art.build_fighter(0, Dir8.SE, quarter_turns=2)
    left, top, right, bottom = opaque_box(upright)
    side_box = opaque_box(sideways)
    assert side_box[2] - side_box[0] >= art.BODY_HEIGHT - 1, "the long axis is now horizontal"
    assert opaque_box(flipped) == (left, top, right, bottom), "half a turn: same outline box"
    assert flipped.tobytes() != upright.tobytes()
    assert art.build_fighter(0, Dir8.SE, quarter_turns=4).tobytes() == upright.tobytes()


@pytest.mark.parametrize("tier", range(4))
def test_sparks_are_centred_and_grow_with_tier_and_frame(tier: int) -> None:
    size = art.SPARK_SIZES[tier]
    first, second, last = (art.build_spark(tier, "slash", frame) for frame in range(3))
    assert first.size == second.size == last.size == (size, size) and size % 2 == 1
    small, big = opaque_box(first), opaque_box(second)
    assert big[2] - big[0] > small[2] - small[0]
    centre = size // 2
    assert second.getpixel((centre, centre))[3] == 255
    assert last.getpixel((centre, centre))[3] == 0, "the last frame is only an outline"
    for image in (first, second, last):
        box = opaque_box(image)
        assert box[0] == size - box[2] and box[1] == size - box[3], "symmetric about the centre"


def test_spark_colors_depend_on_the_effect_and_unknown_effects_fall_back() -> None:
    assert art.build_spark(1, "slash", 1).tobytes() != art.build_spark(1, "fire", 1).tobytes()
    assert art.build_spark(1, "mystery", 1).tobytes() == art.build_spark(1, "normal", 1).tobytes()
    assert {effect.value for effect in Effect} == set(art.SPARK_COLORS)


def test_a_world_sphere_is_an_ellipse_on_screen() -> None:
    # Widest along x - y (16 px per unit each), tallest along the view-plane's up axis.
    assert pytest.approx(TILE_W / 2 * math.sqrt(2)) == art.SPHERE_WIDTH_PER_UNIT
    assert pytest.approx(math.sqrt(8**2 + 8**2 + Z_PX**2)) == art.SPHERE_HEIGHT_PER_UNIT
    assert art.sphere_screen_size(1.0) == (45, 39)
    assert art.sphere_screen_size(0.5) == (23, 20)
    # Check against the projection itself: the extreme points of a unit sphere.
    diagonal = math.sqrt(0.5)
    assert project(diagonal, -diagonal, 0.0)[0] == pytest.approx(art.SPHERE_WIDTH_PER_UNIT)
    norm = art.SPHERE_HEIGHT_PER_UNIT
    top = project(-8 / norm, -8 / norm, Z_PX / norm)
    assert top[1] == pytest.approx(norm) and top[0] == pytest.approx(0)


def test_swing_blob_is_hitbox_sized_and_player_colored() -> None:
    swing = art.build_swing(1, 0.55)
    assert swing.size == art.sphere_screen_size(0.55)
    red, green, blue, _ = art.player_color(1)
    assert swing.getpixel((swing.width // 2, 0)) == (red, green, blue, art.SWING_RIM_ALPHA)
    assert swing.getpixel((swing.width // 2, swing.height // 2)) == (255, 255, 255, art.SWING_ALPHA)
    assert swing.getpixel((0, 0))[3] == 0


# --- HUD colors and layout ----------------------------------------------------------------


def test_damage_color_ramp_matches_the_art_direction_note() -> None:
    from isofightr.ui.hud_layout import DAMAGE_RAMP, damage_color

    for stop, color in DAMAGE_RAMP:
        assert damage_color(stop) == color
    assert damage_color(0) == (255, 255, 255)
    assert damage_color(30) == (255, 244, 176), "half way from white to yellow"
    assert damage_color(999) == damage_color(200) == DAMAGE_RAMP[-1][1]
    reds = [damage_color(percent)[1] for percent in range(0, 220, 10)]
    assert reds == sorted(reds, reverse=True), "green falls steadily: the text gets redder"


def test_damage_text_rounds_down() -> None:
    from isofightr.ui.hud_layout import damage_text

    assert [damage_text(value) for value in (0, 2.625, 99.99, 100.0)] == ["0%", "2%", "99%", "100%"]


@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_hud_panels_are_spread_evenly_and_stay_on_screen(players: int) -> None:
    from isofightr.ui.hud_layout import PANEL_WIDTH, panel_lefts

    lefts = panel_lefts(players)
    assert len(lefts) == players and lefts == sorted(lefts)
    assert lefts[0] >= 0 and lefts[-1] + PANEL_WIDTH <= NATIVE_W
    centres = [left + PANEL_WIDTH / 2 for left in lefts]
    assert centres[0] == pytest.approx(NATIVE_W - centres[-1], abs=1)
    gaps = {round(b - a) for a, b in itertools.pairwise(lefts)}
    assert len(gaps) <= 1 and all(gap >= PANEL_WIDTH for gap in gaps)


# --- hitbox overlay geometry --------------------------------------------------------------


def test_overlay_ellipses_sit_on_the_projected_shapes() -> None:
    from isofightr.render.hitbox_shapes import capsule_ellipses, sphere_ellipse

    shape = sphere_ellipse(Vec3(2.0, 1.0, 3.0), 0.5)
    assert (shape.x, shape.y) == project(2.0, 1.0, 3.0)
    assert (shape.width, shape.height) == pytest.approx(
        (art.SPHERE_WIDTH_PER_UNIT, art.SPHERE_HEIGHT_PER_UNIT)
    )

    match, attacker, _ = duel()
    capsule = hurtbox(attacker)
    low, high = capsule_ellipses(capsule)
    shape_def = attacker.character.body.hurtbox
    assert low.x == high.x and low.width == high.width
    span = (shape_def.z1 - shape_def.z0 - 2 * shape_def.radius) * Z_PX
    assert high.y - low.y == pytest.approx(span, abs=1), "whole pixels"
    feet_y = project(attacker.pos.x, attacker.pos.y, attacker.pos.z)[1]
    assert low.y - low.height / 2 < feet_y + Z_PX, "the capsule starts near the feet"
    assert match.frame == 0


# --- M4: shields, intangibility, helpless ----------------------------------------------------


def test_reduce_flashing_swaps_flashes_and_blinks_for_a_steady_dim() -> None:
    """The accessibility setting (plan note 13, "Settings": flash reduction)."""
    _, attacker, _ = duel()
    assert fighter_look(attacker, 0, flash_frames=3).flash
    assert not fighter_look(attacker, 0, flash_frames=3, reduce_flashing=True).flash
    attacker.intangible_frames = 10
    looks = [fighter_look(attacker, frame, reduce_flashing=True) for frame in range(8)]
    assert not any(look.hidden for look in looks), "no blinking"
    assert all(look.dim for look in looks), "dimmed instead"


def test_intangible_fighters_blink_and_helpless_ones_are_dim() -> None:
    match, attacker, _ = duel()
    attacker.intangible_frames = 10
    hidden = [fighter_look(attacker, frame).hidden for frame in range(8)]
    assert hidden == [False, False, True, True, False, False, True, True]
    attacker.intangible_frames = 0
    assert not fighter_look(attacker, 2).hidden
    attacker.state = StateId.HELPLESS
    assert fighter_look(attacker, match.frame).dim
    attacker.state = StateId.DIZZY
    wobble = {fighter_look(attacker, frame).offset_x for frame in range(24)}
    assert wobble == {-1, 0, 1}
    attacker.state = StateId.ROLL
    assert fighter_look(attacker, 0).pose is Pose.TUMBLE


def test_dim_sprite_is_darker_with_the_same_outline() -> None:
    normal = art.build_fighter(0, Dir8.SE)
    dim = art.build_fighter(0, Dir8.SE, dim=True)
    assert dim.getchannel("A").tobytes() == normal.getchannel("A").tobytes()
    body = (art.FIGHTER_PIVOT_X - 3, art.FIGHTER_CANVAS - art.FIGHTER_PIVOT_FROM_BOTTOM - 4)
    assert sum(dim.getpixel(body)[:3]) < sum(normal.getpixel(body)[:3])


def test_shield_bubble_is_shield_sized_and_player_colored() -> None:
    bubble = art.build_shield(1, 1.2)
    assert bubble.size == art.sphere_screen_size(1.2)
    red, green, blue, _ = art.player_color(1)
    centre = (bubble.width // 2, bubble.height // 2)
    assert bubble.getpixel(centre) == (red, green, blue, art.SHIELD_ALPHA)
    assert bubble.getpixel((0, 0))[3] == 0
    assert art.build_shield(1, 0.5).size < bubble.size


def test_blocks_parries_breaks_and_techs_give_feedback() -> None:
    from isofightr.sim.events import (
        GrabEvent,
        LedgeGrabEvent,
        ShieldBreakEvent,
        ShieldHitEvent,
        TechEvent,
    )

    effects = BattleEffects()
    effects.consume([ShieldHitEvent(0, 1, 11.0, ORIGIN, 12, False)])
    assert [spark.tier for spark in effects.sparks] == [fx.SHIELD_SPARK_TIER]
    assert effects.shake.current() == 0 and effects.flash == {}
    effects.consume([ShieldHitEvent(0, 1, 0.0, ORIGIN, 12, True)])
    assert effects.sparks[-1].tier == fx.PARRY_SPARK_TIER
    assert effects.shake.current() == fx.PARRY_SHAKE_PIXELS
    effects.consume([ShieldBreakEvent(1, ORIGIN)])
    assert effects.sparks[-1].tier == fx.SHIELD_BREAK_SPARK_TIER
    assert effects.shake.current() == fx.SHIELD_BREAK_SHAKE_PIXELS
    count = len(effects.sparks)
    effects.consume(
        [
            TechEvent(0, ORIGIN, wall=False),
            LedgeGrabEvent(0, ORIGIN, None),
            GrabEvent(0, 1, ORIGIN, clash=True),
            GrabEvent(0, 1, ORIGIN, clash=False),
        ]
    )
    assert len(effects.sparks) == count + 3, "an ordinary grab has no spark"


# --- M5: projectiles and counters -----------------------------------------------------------


def test_projectile_ball_is_hitbox_sized_and_player_colored() -> None:
    ball = art.build_projectile(0, 0.4)
    assert ball.size == art.sphere_screen_size(0.4)
    assert ball.getpixel((ball.width // 2, ball.height // 2)) == art.WHITE
    assert ball.getpixel((ball.width // 2, 1)) == art.player_color(0)
    assert ball.getpixel((0, 0))[3] == 0


def test_counters_flash_and_projectiles_puff_when_they_end() -> None:
    from isofightr.sim.events import CounterEvent, ProjectileEvent

    effects = BattleEffects()
    effects.consume([ProjectileEvent(0, ORIGIN, spawned=True)])
    assert effects.sparks == []
    effects.consume([ProjectileEvent(0, ORIGIN, spawned=False)])
    assert [spark.tier for spark in effects.sparks] == [fx.SMALL_SPARK_TIER]
    effects.consume([CounterEvent(1, ORIGIN)])
    assert effects.flash == {1: fx.COUNTER_FLASH_FRAMES}
    assert effects.shake.current() == fx.PARRY_SHAKE_PIXELS
