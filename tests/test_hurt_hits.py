"""Tests for the hit data the hit poses read (decision D-067, M16 group 4b): where a hit landed
on the body, how hard it was, its effect, and the reeling roll's deterministic 30% chance.
Presentation state from the sim's events; nothing is written back."""

import pytest

from helpers import make_match, place
from isofightr.render.effects import BattleEffects
from isofightr.render.hurt_motion import (
    ROLL_CHANCE,
    ROLL_MAX_ELEVATION,
    ROLL_MIN_DAMAGE,
    ROLL_MIN_KB,
    DamageTier,
    HitHeight,
    HurtMotion,
    HurtTrack,
    damage_tier,
    hit_height,
    roll_value,
    rolls,
)
from isofightr.sim.events import HazardHitEvent, HitEvent
from isofightr.sim.fighter import GroundKind, Launch
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.states.interrupts import start_move


def struck(
    move: str, percent: float, lift: float | None = None, delay: int = 0
) -> tuple[Match, BattleEffects, HitEvent, int, list[HurtTrack]]:
    """Rook does ``move`` on Rook at ``percent`` (held ``lift`` units up until the hit), after
    ``delay`` idle ticks; the effects are fed as the battle feeds them. Return the match, the
    effects, the hit, the match frame it was seen on and a copy of the target's track each
    tick from the hit for 40 ticks."""
    match = make_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.E)
    place(match, target, 5.0, 6.0, facing=Dir8.W, damage=percent)
    floor = target.pos.z
    effects = BattleEffects()
    for _ in range(delay):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
    start_move(match, attacker, move)
    hit: HitEvent | None = None
    frame = 0
    tracks: list[HurtTrack] = []
    for _ in range(200):
        if hit is None and lift is not None:
            target.pos = Vec3(target.pos.x, target.pos.y, floor + lift)
            target.vel = ZERO3
            target.ground = GroundKind.NONE
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        effects.tick()
        effects.consume(match.events)
        effects.observe(match.fighters, match.stage, match.frame)
        for event in match.events:
            if isinstance(event, HitEvent) and event.target == 1 and hit is None:
                hit, frame = event, match.frame
        if hit is not None:
            track = effects.hurt.track(1)
            assert track is not None
            tracks.append(HurtTrack(**{k: getattr(track, k) for k in HurtTrack.__slots__}))
            if len(tracks) >= 40:
                break
    assert hit is not None, f"{move} never hit"
    return match, effects, hit, frame, tracks


def test_the_height_band_is_the_hit_points_share_of_the_hurtbox() -> None:
    match = make_match(fighters=("rook", "zephyr"), stocks=None)
    rook, zephyr = match.fighters
    for fighter in (rook, zephyr):
        for lift in (0.0, 3.0):
            fighter.pos = Vec3(5.0, 5.0, lift)
            assert hit_height(fighter, Vec3(5.0, 5.0, lift + 0.1)) is HitHeight.LOW
            assert hit_height(fighter, Vec3(5.0, 5.0, lift + 1.0)) is HitHeight.MID
            assert hit_height(fighter, Vec3(5.0, 5.0, lift + 9.0)) is HitHeight.HIGH, "clamped"
            assert hit_height(fighter, Vec3(5.0, 5.0, lift - 4.0)) is HitHeight.LOW, "clamped"
    # The same point is high on the short Zephyr and middling on Rook.
    rook.pos, zephyr.pos = Vec3(5.0, 5.0, 0.0), Vec3(5.0, 5.0, 0.0)
    assert hit_height(zephyr, Vec3(5.0, 5.0, 1.6)) is HitHeight.HIGH
    assert hit_height(rook, Vec3(5.0, 5.0, 1.6)) is HitHeight.MID


def test_the_damage_tiers() -> None:
    tiers = [damage_tier(d) for d in (0.0, 6.0, 6.01, 12.0, 12.01, 30.0)]
    assert tiers == [DamageTier.WEAK] * 2 + [DamageTier.MEDIUM] * 2 + [DamageTier.HEAVY] * 2


def test_the_roll_value_is_a_fixed_hash_of_frame_player_and_damage() -> None:
    assert roll_value(100, 1, 120.5) == pytest.approx(0.012165379493310898, abs=1e-15)
    assert roll_value(0, 0, 0.0) == pytest.approx(0.13870941014555435, abs=1e-15)
    base = roll_value(500, 2, 130.0)
    assert base == roll_value(500, 2, 130.0)
    assert len({base, roll_value(501, 2, 130.0), roll_value(500, 3, 130.0)}) == 3
    assert roll_value(500, 2, 130.01) != base, "damage counts to a hundredth"
    values = [
        roll_value(f, p, 100.0 + (f * 7 % 90) + 0.3 * p) for f in range(2000) for p in range(4)
    ]
    assert all(0.0 <= v < 1.0 for v in values)
    passed = sum(v < ROLL_CHANCE for v in values) / len(values)
    assert 0.27 <= passed <= 0.33, "about 30% of qualifying hits roll"


def test_every_condition_of_the_roll() -> None:
    good = {"airborne": True, "knockback": 120.0, "damage": 110.0, "elevation": 40.0}
    assert rolls(**good, chance=0.1)
    assert not rolls(**good, chance=ROLL_CHANCE)
    assert not rolls(**(good | {"airborne": False}), chance=0.1)
    assert not rolls(**(good | {"knockback": ROLL_MIN_KB - 1.0}), chance=0.1)
    assert not rolls(**(good | {"damage": ROLL_MIN_DAMAGE - 0.1}), chance=0.1)
    assert not rolls(**(good | {"elevation": ROLL_MAX_ELEVATION}), chance=0.1)
    assert not rolls(**(good | {"elevation": -ROLL_MAX_ELEVATION - 5.0}), chance=0.1)
    assert rolls(**(good | {"elevation": -60.0}), chance=0.1), "a low line down also rolls"


@pytest.mark.parametrize(
    ("move", "height", "tier"),
    [
        ("utilt", HitHeight.HIGH, DamageTier.MEDIUM),
        ("dtilt", HitHeight.LOW, DamageTier.MEDIUM),
        ("jab1", HitHeight.MID, DamageTier.WEAK),
        ("fsmash", HitHeight.MID, DamageTier.HEAVY),
    ],
)
def test_the_freeze_records_where_and_how_hard_the_hit_landed(
    move: str, height: HitHeight, tier: DamageTier
) -> None:
    """From the real sim, fed to the effects as the battle feeds them."""
    _, _, hit, _, tracks = struck(move, 0.0)
    first = tracks[0]
    assert (first.height, first.tier, first.effect) == (height, tier, hit.effect)
    assert not first.airborne_hit and first.percent == pytest.approx(hit.damage)
    assert not any(track.rolling for track in tracks), "a grounded hit never rolls"


def test_an_air_hit_at_high_percent_rolls_exactly_as_its_hash_says() -> None:
    """The hit lands on a different match frame for each delay, so the hash differs; every
    decision must be the rule applied to the launch's first tick, and both outcomes occur."""
    decisions = []
    for delay in range(24):
        _, _, hit, frame, tracks = struck("fsmash", 120.0, lift=0.6, delay=delay)
        first = tracks[0]
        assert first.airborne_hit and first.percent >= ROLL_MIN_DAMAGE
        assert first.chance == roll_value(frame, 1, first.percent)
        launched = next(t for t in tracks if t.launch_elevation is not None)
        expected = rolls(
            True, hit.knockback, first.percent, launched.launch_elevation, first.chance
        )
        assert launched.rolling is expected
        decisions.append(expected)
    assert True in decisions and False in decisions


def test_a_hit_below_100_percent_never_rolls() -> None:
    for delay in range(12):
        _, _, _, _, tracks = struck("fsmash", 60.0, lift=0.6, delay=delay)
        assert not any(track.rolling for track in tracks)


def freeze(match: Match, knockback: float = 120.0) -> None:
    """Put player 1 in a hit's freeze by hand (a test's shortcut; the sim does this on a hit)."""
    target = match.fighters[1]
    target.launch = Launch(knockback=knockback, heading=Vec2(1.0, 0.0), elevation=30.0, tumble=True)
    target.hitlag = 6


def test_a_hazard_hit_records_its_effect_and_a_blocked_one_is_ignored() -> None:
    match = make_match(stocks=None)
    target = match.fighters[1]
    freeze(match)
    middle = target.pos + Vec3(0.0, 0.0, 1.25)
    zap = HazardHitEvent(0, "lightning", 1, 9.0, 120.0, middle, Effect.ELECTRIC, 6, False)
    motion = HurtMotion()
    motion.step(match.fighters, [zap], frame=300)
    track = motion.track(1)
    assert track is not None
    assert (track.effect, track.height, track.tier) == (
        Effect.ELECTRIC,
        HitHeight.MID,
        DamageTier.MEDIUM,
    )
    other = HurtMotion()
    blocked = HazardHitEvent(0, "lightning", 1, 9.0, 0.0, middle, Effect.ELECTRIC, 6, True)
    other.step(match.fighters, [blocked], frame=300)
    assert other.track(1) is not None and other.track(1).effect is Effect.NORMAL


def test_a_freeze_no_event_explains_forgets_the_last_hit() -> None:
    match = make_match(stocks=None)
    freeze(match)
    motion = HurtMotion()
    motion.tracks[1] = HurtTrack(
        height=HitHeight.HIGH, tier=DamageTier.HEAVY, effect=Effect.FIRE, chance=0.0
    )
    motion.step(match.fighters)
    track = motion.track(1)
    assert track is not None
    assert (track.height, track.tier, track.effect, track.chance) == (
        HitHeight.MID,
        DamageTier.WEAK,
        Effect.NORMAL,
        1.0,
    )


def test_the_hit_data_never_changes_the_sim() -> None:
    match, effects, _, _, _ = struck("fsmash", 120.0, lift=0.6)
    before = match.state_hash()
    effects.consume(match.events)
    effects.observe(match.fighters, match.stage, match.frame)
    assert match.state_hash() == before
