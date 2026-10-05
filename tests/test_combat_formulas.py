"""Unit tests for the combat formulas (plan note 05, "Required unit tests")."""

import math

import pytest

from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.combat.hitbox import local_to_world
from isofightr.sim.combat.staling import push_stale, stale_multiplier
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.move_def import Effect

# --- knockback ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("percent", "damage", "weight", "bkb", "kbg", "expected"),
    [
        # (100/10 + 100*10/20) * 200/200 * 1.4 = 84; + 18 = 102; * 1.00 + 20 = 122
        (100, 10, 100, 20, 100, 122.0),
        # Rook's forward smash on a fresh Rook: (1.6 + 12.8) * 200/198 * 1.4 + 18, * 1.05 + 30
        (16, 16, 98, 30, 105, 70.28181818181818),
        # The same hit at 130% before the hit (146% after)
        (146, 16, 98, 30, 105, 244.00909090909087),
        # A weak jab with low growth barely moves anyone
        (50, 2.5, 98, 8, 30, 18.172727272727272),
        # A heavy target takes less: 200/(120+100)
        (200, 12, 120, 15, 100, 211.18181818181816),
        # No base knockback, almost no percent
        (10, 8, 98, 0, 100, 25.070707070707066),
    ],
)
def test_knockback_matches_hand_computed_values(
    percent: float, damage: float, weight: float, bkb: float, kbg: float, expected: float
) -> None:
    assert kb.knockback(percent, damage, weight, bkb, kbg) == pytest.approx(expected)


def test_knockback_grows_with_percent_and_damage_and_shrinks_with_weight() -> None:
    base = kb.knockback(80, 10, 100, 20, 100)
    assert kb.knockback(120, 10, 100, 20, 100) > base
    assert kb.knockback(80, 14, 100, 20, 100) > base
    assert kb.knockback(80, 10, 130, 20, 100) < base
    assert kb.knockback(80, 10, 100, 20, 100, ratio=0.5) == pytest.approx(base / 2)


def test_fixed_knockback_ignores_percent_and_damage() -> None:
    fixed = kb.knockback(150, 12, 98, 0, 100, fkb=30)
    assert fixed == kb.knockback(0, 3, 98, 0, 100, fkb=30)
    # p = 10, d = fkb: (1 + 15) * 200/198 * 1.4 + 18
    assert fixed == pytest.approx((1 + 15) * 200 / 198 * 1.4 + 18)


def test_hitstun_is_forty_percent_of_knockback_floored() -> None:
    assert kb.hitstun_frames(100.0) == 40
    assert kb.hitstun_frames(122.4) == 48
    assert kb.hitstun_frames(122.6) == 49
    assert kb.hitstun_frames(2.4) == 0


def test_tumble_threshold_is_exactly_eighty() -> None:
    assert not kb.is_tumble(79.999)
    assert kb.is_tumble(80.0)
    assert kb.is_tumble(200.0)


def test_hitlag_formula_and_cap() -> None:
    """Melee's ``floor(d / 3 + 3)`` (decision D-058), times the multipliers, capped at 30."""
    assert (c.HITLAG_DAMAGE_DIVISOR, c.HITLAG_BASE) == (3.0, 3.0)
    cases = {0: 3, 2.5: 3, 9: 6, 10: 6, 12: 7, 16.8: 8, 20: 9, 60: 23, 80: 29}
    for damage, frames in cases.items():
        assert kb.hitlag_frames(damage) == frames, damage
    for damage in range(0, 81, 3):
        assert kb.hitlag_frames(damage) == damage // 3 + 3, "a multiple of 3 never floors low"
    assert kb.hitlag_frames(81) == kb.hitlag_frames(200) == c.HITLAG_MAX == 30
    assert kb.hitlag_frames(10, multiplier=0.5) == math.floor((10 / 3 + 3) * 0.5) == 3
    assert kb.hitlag_frames(10, effect=Effect.ELECTRIC) == math.floor((10 / 3 + 3) * 1.5) == 9
    assert kb.hitlag_frames(10, full_charge=True) == math.floor((10 / 3 + 3) * 1.2) == 7


def test_launch_speed_scales_with_phys_scale() -> None:
    assert kb.launch_speed(100) == pytest.approx(100 * 0.03 * c.PHYS_SCALE)
    assert pytest.approx(0.051 * c.PHYS_SCALE) == c.KB_DECAY


# --- launch angle -------------------------------------------------------------------------


def test_plain_angles_pass_through() -> None:
    assert kb.resolve_elevation(38, 100, target_grounded=True) == 38
    assert kb.resolve_elevation(88, 10, target_grounded=False) == 88
    assert kb.resolve_elevation(-80, 100, target_grounded=False) == -80


def test_sakurai_angle_for_grounded_targets_rises_with_knockback() -> None:
    assert kb.resolve_elevation(361, 30, target_grounded=True) == 0
    assert kb.resolve_elevation(361, 59.9, target_grounded=True) == 0
    assert kb.resolve_elevation(361, 60, target_grounded=True) == 0
    assert kb.resolve_elevation(361, 74, target_grounded=True) == pytest.approx(20)
    assert kb.resolve_elevation(361, 88, target_grounded=True) == 40
    assert kb.resolve_elevation(361, 200, target_grounded=True) == 40


def test_sakurai_angle_for_airborne_targets_is_always_forty() -> None:
    for knockback in (10, 60, 74, 300):
        assert kb.resolve_elevation(361, knockback, target_grounded=False) == 40


def test_meteor_on_a_grounded_target_pops_up_and_bounces_into_tumble_when_strong() -> None:
    assert kb.resolve_elevation(-80, 40, target_grounded=True) == 80
    assert not kb.meteor_tumbles(-80, 59.9, target_grounded=True)
    assert kb.meteor_tumbles(-80, 60, target_grounded=True)
    assert not kb.meteor_tumbles(-80, 200, target_grounded=False)
    assert not kb.meteor_tumbles(38, 200, target_grounded=True)
    assert not kb.meteor_tumbles(361, 200, target_grounded=True)


def test_launch_vector_combines_heading_and_elevation() -> None:
    assert kb.launch_vector(Vec2(1, 0), 0) == Vec3(1.0, 0.0, 0.0)
    up = kb.launch_vector(Vec2(1, 0), 90)
    assert (up.x, up.y, up.z) == pytest.approx((0, 0, 1))
    slanted = kb.launch_vector(Vec2(0, 1), 30)
    assert (slanted.x, slanted.y, slanted.z) == pytest.approx((0, math.cos(math.pi / 6), 0.5))
    assert slanted.length() == pytest.approx(1.0)
    spike = kb.launch_vector(Vec2(1, 0), -90)
    assert spike.z == pytest.approx(-1)


# --- DI -----------------------------------------------------------------------------------


def angle_between(first: Vec2, second: Vec2) -> float:
    return math.degrees(math.atan2(first.cross(second), first.dot(second)))


def test_di_perpendicular_to_the_launch_rotates_by_the_maximum() -> None:
    heading = Vec2(1, 0)
    left, _ = kb.apply_di(heading, 40, Vec2(0, 1), 0)
    right, _ = kb.apply_di(heading, 40, Vec2(0, -1), 0)
    assert angle_between(heading, left) == pytest.approx(c.DI_MAX_DEGREES)
    assert angle_between(heading, right) == pytest.approx(-c.DI_MAX_DEGREES)
    assert left.length() == pytest.approx(1.0)


def test_di_along_or_against_the_launch_does_nothing() -> None:
    heading = Vec2(1, 0)
    for stick in (Vec2(1, 0), Vec2(-1, 0), Vec2()):
        turned, elevation = kb.apply_di(heading, 40, stick, 0)
        assert (turned.x, turned.y) == pytest.approx((1, 0))
        assert elevation == 40


def test_di_is_capped_and_scales_with_stick_tilt_and_angle() -> None:
    heading = Vec2(1, 0)
    half, _ = kb.apply_di(heading, 0, Vec2(0, 0.5), 0)
    assert angle_between(heading, half) == pytest.approx(c.DI_MAX_DEGREES / 2)
    diagonal, _ = kb.apply_di(heading, 0, Dir8.S.world, 0)  # 45 degrees off the launch
    assert angle_between(heading, diagonal) == pytest.approx(
        c.DI_MAX_DEGREES * math.sin(math.pi / 4)
    )
    for stick in (Vec2(0, 1), Vec2(0.6, 0.8), Vec2(-0.6, 0.8)):
        turned, _ = kb.apply_di(heading, 0, stick, 0)
        assert abs(angle_between(heading, turned)) <= c.DI_MAX_DEGREES + 1e-9


def test_vertical_di_shifts_the_elevation() -> None:
    _, up = kb.apply_di(Vec2(1, 0), 40, Vec2(), 1)
    _, down = kb.apply_di(Vec2(1, 0), 40, Vec2(), -1)
    assert (up, down) == (40 + c.DI_MAX_DEGREES, 40 - c.DI_MAX_DEGREES)
    _, capped = kb.apply_di(Vec2(1, 0), 85, Vec2(), 1)
    assert capped == 90


# --- staling ------------------------------------------------------------------------------


def test_a_move_not_in_the_queue_gets_the_fresh_bonus() -> None:
    assert stale_multiplier([], "jab1") == c.FRESH_BONUS == 1.05
    assert stale_multiplier(["ftilt", "nair"], "jab1") == 1.05


def test_each_queue_slot_has_its_own_penalty() -> None:
    assert stale_multiplier(["jab1"], "jab1") == pytest.approx(1 - 0.09)
    assert stale_multiplier(["x", "jab1"], "jab1") == pytest.approx(1 - 0.08)
    assert stale_multiplier(["jab1", "x", "jab1"], "jab1") == pytest.approx(1 - 0.09 - 0.07)
    full = ["jab1"] * 9
    assert stale_multiplier(full, "jab1") == pytest.approx(1 - 0.45)
    assert sum(c.STALE_PENALTIES) == pytest.approx(0.45)
    assert len(c.STALE_PENALTIES) == c.STALE_QUEUE_LENGTH == 9


def test_the_queue_keeps_the_last_nine_and_wraps_around() -> None:
    queue: list[str] = []
    for index in range(9):
        push_stale(queue, f"move{index}")
    assert queue == [f"move{index}" for index in range(8, -1, -1)]
    push_stale(queue, "jab1")
    assert len(queue) == 9
    assert queue[0] == "jab1" and "move0" not in queue and queue[-1] == "move1"
    # Using other moves pushes a stale move out again: it freshens.
    for index in range(9):
        push_stale(queue, f"other{index}")
    assert stale_multiplier(queue, "jab1") == 1.05


# --- local to world -----------------------------------------------------------------------


def test_hitbox_offsets_follow_the_facing() -> None:
    pos = Vec3(5.0, 5.0, 1.0)
    forward = local_to_world(pos, Dir8.SE.world, Vec3(1.0, 0.0, 1.2))
    assert forward == Vec3(6.0, 5.0, 2.2)
    behind = local_to_world(pos, Dir8.NW.world, Vec3(1.0, 0.0, 0.0))
    assert behind == Vec3(4.0, 5.0, 1.0)
    # "Left" of a fighter facing +x is +y in world space (the perpendicular (-fy, fx)).
    assert local_to_world(pos, Dir8.SE.world, Vec3(0.0, 1.0, 0.0)) == Vec3(5.0, 6.0, 1.0)
    diagonal = local_to_world(Vec3(), Dir8.S.world, Vec3(1.0, 0.0, 0.0))
    assert (diagonal.x, diagonal.y) == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
