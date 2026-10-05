"""Tests for the final effect set: dust, launch trails, shockwave rings, KO blasts and the
palette-locked spark art.

Plan note "09 - Art Direction" ("VFX style") and note "03 - Isometric World and Rendering"
("VFX"). Presentation only: fed by sim events and fighter state, never read by the sim.
"""

from helpers import make_match
from isofightr.art.palettes import load_master
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render import effects as fx
from isofightr.render import vfx_art
from isofightr.render.effects import BattleEffects
from isofightr.render.iso import project
from isofightr.render.placeholder_art import player_color
from isofightr.sim.events import JumpEvent, JumpKind, KoEvent, LandEvent, TechEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.math3d import Vec3

MASTER = load_master("resurrect64")
FEET = Vec3(5.0, 5.0, 0.0)


def _palette_only(image: object) -> bool:
    return {pixel[:3] for pixel in image.getdata() if pixel[3]} <= MASTER  # type: ignore[attr-defined]


def test_landings_raise_dust_and_hard_ones_a_ring() -> None:
    effects = BattleEffects()
    effects.consume([LandEvent(0, FEET, 0.02)])
    assert not effects.puffs, "a gentle step makes no dust"
    effects.consume([LandEvent(0, FEET, 0.1)])
    assert [puff.size for puff in effects.puffs] == ["small"] and not effects.rings
    effects.consume([LandEvent(1, FEET, fx.LAND_RING_FALL_SPEED)])
    assert effects.puffs[-1].size == "big" and len(effects.rings) == 1


def test_ground_jumps_and_ground_techs() -> None:
    effects = BattleEffects()
    effects.consume([JumpEvent(0, JumpKind.FULL_HOP, FEET), JumpEvent(0, JumpKind.AIR, FEET)])
    assert len(effects.puffs) == 1, "only jumps off the ground kick up dust"
    effects.consume([TechEvent(0, FEET, wall=False), TechEvent(0, FEET, wall=True)])
    assert len(effects.rings) == 1


def test_a_ko_sends_a_blast() -> None:
    effects = BattleEffects()
    effects.consume([KoEvent(1, Vec3(30.0, 5.0, 3.0), Vec3(1.0, 0.0, 0.0), 2)])
    assert len(effects.blasts) == 1 and effects.blasts[0].player == 1
    for _ in range(fx.KO_BLAST_FRAMES * fx.KO_BLAST_FRAME_TICKS):
        effects.tick()
    assert not effects.blasts, "it fades"


def test_dash_and_skid_dust() -> None:
    match = make_match()
    fighter = match.fighters[0]
    effects = BattleEffects()
    fighter.state, fighter.state_frame = StateId.DASH, 1
    effects.observe([fighter])
    assert len(effects.puffs) == 1
    behind = fighter.pos - Vec3(fighter.facing.world.x, fighter.facing.world.y, 0.0) * 0.4
    assert (effects.puffs[0].position - behind).length() < 1e-9, "behind the feet"
    fighter.state_frame = 2
    effects.observe([fighter])
    assert len(effects.puffs) == 1, "only when the dash starts"


def test_launched_fighters_leave_a_trail_that_turns_fiery() -> None:
    match = make_match()
    fighter = match.fighters[0]
    effects = BattleEffects()
    fighter.hitstun, fighter.kb_vel, fighter.last_knockback = 30, Vec3(0.3, 0.0, 0.1), 90.0
    for _ in range(fx.TRAIL_EVERY * 3):
        effects.observe([fighter])
        effects.tick()
    assert len(effects.trails) == 3 and not any(puff.fiery for puff in effects.trails)
    fighter.last_knockback = fx.TRAIL_FIERY_KNOCKBACK
    effects.ticks = 0
    effects.observe([fighter])
    assert effects.trails[-1].fiery
    fighter.hitstun = 0
    count = len(effects.trails)
    effects.ticks = 0
    effects.observe([fighter])
    assert len(effects.trails) == count, "no trail out of hitstun"


def test_effects_expire_and_clear() -> None:
    effects = BattleEffects()
    effects.consume([LandEvent(0, FEET, 0.3)])
    for _ in range(fx.PUFF_FRAMES * fx.EFFECT_FRAME_TICKS):
        effects.tick()
    assert not effects.puffs and not effects.rings
    effects.consume([LandEvent(0, FEET, 0.3)])
    effects.clear()
    assert not effects.puffs and not effects.rings and not effects.blasts


# --- art --------------------------------------------------------------------------------------


def test_effect_art_uses_only_palette_colours() -> None:
    images = [
        vfx_art.build_spark(tier, effect, frame)
        for tier in range(4)
        for effect in ("normal", "slash", "fire", "electric", "ice", "darkness")
        for frame in range(3)
    ]
    images += [vfx_art.build_puff(size, frame) for size in ("small", "big") for frame in range(4)]
    images += [vfx_art.build_trail(fiery, frame) for fiery in (False, True) for frame in range(4)]
    images += [vfx_art.build_ring(frame) for frame in range(4)]
    images += [vfx_art.build_ko_beam(player_color(1), 3, frame) for frame in range(5)]
    assert all(_palette_only(image) for image in images)


def test_the_lightest_spark_is_nineteen_pixels() -> None:
    assert vfx_art.SPARK_SIZES == (19, 23, 31, 43)
    assert vfx_art.build_spark(0, "normal", 1).size == (19, 19)


def test_streaks_are_thin_palette_lines_pointing_along_their_angle() -> None:
    for angle in range(vfx_art.STREAK_ANGLES):
        for frame in (0, 1):
            image = vfx_art.build_streak(angle, frame)
            assert image.size == (vfx_art.STREAK_SIZE, vfx_art.STREAK_SIZE)
            pixels = [
                (x, y)
                for x in range(image.width)
                for y in range(image.height)
                if image.getpixel((x, y))[3]
            ]
            assert 0 < len(pixels) <= 30, "three short 1 px strokes: nothing is hidden"
            assert _palette_only(image)
    right = vfx_art.build_streak(0, 0)
    drawn = [
        x for x in range(right.width) for y in range(right.height) if right.getpixel((x, y))[3]
    ]
    assert min(drawn) > right.width // 2, "angle 0 points right of the centre"
    up = vfx_art.build_streak(4, 0)
    rows = [y for x in range(up.width) for y in range(up.height) if up.getpixel((x, y))[3]]
    assert max(rows) < up.height // 2, "angle 4 points up"


def test_sparks_climb_the_colour_tiers() -> None:
    edges = [vfx_art.spark_colors("normal", tier)[1] for tier in range(4)]
    assert len(set(edges)) == 4
    assert vfx_art.spark_colors("fire", 0) == vfx_art.spark_colors("fire", 3), "by element"
    assert vfx_art.build_spark(3, "normal", 0).width > vfx_art.build_spark(0, "normal", 0).width


def test_ring_and_puff_sizes() -> None:
    widths = [vfx_art.build_ring(frame).width for frame in range(4)]
    assert widths == sorted(widths), "the ring spreads"
    ring = vfx_art.build_ring(3)
    assert ring.height * 2 - 1 == ring.width, "a 2:1 ellipse on the iso ground"


def test_ko_beam_starts_inside_the_view_and_points_back() -> None:
    centre = (0, 0)
    far_right = Vec3(40.0, -40.0, 0.0)  # well off the right of the screen
    angle_index, (x, y) = vfx_art.ko_beam_placement(far_right, Vec3(1.0, -1.0, 0.0), centre)
    assert x == NATIVE_W / 2 - vfx_art.KO_BEAM_MARGIN
    assert -NATIVE_H / 2 <= y <= NATIVE_H / 2
    assert angle_index == vfx_art.KO_BEAM_ANGLES // 2, "points left, back at the stage"
    _, (_, top_y) = vfx_art.ko_beam_placement(Vec3(0.0, 0.0, 40.0), Vec3(0.0, 0.0, 1.0), centre)
    assert top_y == NATIVE_H / 2 - vfx_art.KO_BEAM_MARGIN
    near = Vec3(1.0, 1.0, 0.0)
    _, base = vfx_art.ko_beam_placement(near, Vec3(1.0, 0.0, 0.0), centre)
    assert base == project(near.x, near.y, near.z), "an exit inside the view stays put"


def test_a_shockwave_rings_and_raises_dust() -> None:
    from isofightr.sim.events import ShockwaveEvent

    effects = BattleEffects()
    effects.consume([ShockwaveEvent(0, FEET, 1.2)])
    assert len(effects.rings) == 1 and [puff.size for puff in effects.puffs] == ["big"]
    assert effects.shake.current() == fx.SHOCKWAVE_SHAKE_PIXELS


def test_move_effect_art_is_palette_locked_and_never_solid() -> None:
    for kind, (frames, ticks) in vfx_art.FX_KINDS.items():
        assert vfx_art.fx_lifetime(kind) == frames * ticks
        for family in vfx_art.FAMILIES:
            for variant in range(8 if kind == "glow" else 1):
                for frame in range(frames):
                    image = vfx_art.build_fx(kind, family, variant, frame)
                    assert _palette_only(image), (kind, family)
                    assert image.width % 2 == 1 and image.height % 2 == 1
                    if image.width <= 5:
                        continue  # a particle of a few pixels
                    solid = sum(1 for pixel in image.getdata() if pixel[3] == 255)
                    assert solid < image.width * image.height * 0.5, "it never hides what is behind"
    small = vfx_art.build_fx("glow", "fire", 0, 0)
    big = vfx_art.build_fx("glow", "fire", 6, 0)
    assert big.width > small.width, "a fuller charge glows bigger"


def test_the_ground_crack_is_palette_locked_and_fades() -> None:
    solid = []
    for fade in range(len(vfx_art.CRACK_ALPHAS)):
        image = vfx_art.build_crack(fade)
        assert image.size == vfx_art.CRACK_SIZE and _palette_only(image)
        solid.append(max(pixel[3] for pixel in image.getdata()))
    assert solid == list(vfx_art.CRACK_ALPHAS)


def test_the_shield_bubble_is_translucent_player_coloured_and_shimmers() -> None:
    red = player_color(0)
    frames = [vfx_art.build_shield(red, 41, 49, frame) for frame in (0, 1)]
    assert frames[0].size == (41, 49) and frames[0].tobytes() != frames[1].tobytes()
    for image in frames:
        assert _palette_only(image)
        assert image.getpixel((0, 0))[3] == 0, "outside the bubble"
        centre = image.getpixel((20, 24))
        assert centre[:3] == red[:3] and 0 < centre[3] < 128, "the fighter shows through"
    small = vfx_art.build_shield(red, 15, 19, 0)
    assert small.size == (15, 19), "a worn shield is a smaller bubble"
