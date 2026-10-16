"""Tests for the hit poses and the tumble's turn (decisions D-066, D-067): presentation state
derived from the sim, never written back."""

from dataclasses import dataclass, replace
from itertools import pairwise

import pytest

from helpers import hold, make_match, neutral, place, run
from isofightr.data.character_loader import list_character_ids
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.render.fighter_look import fighter_look
from isofightr.render.hurt_motion import (
    FLY_ANIM,
    FLY_ELEVATIONS,
    FLY_MIN_KB,
    GROUND_FLY_MIN_KB,
    HIT_STATES,
    IMPACT_ANIM,
    MELEE_HIT_ANIMS,
    ROLL_ANIM,
    ROLL_BODY_ANGLE,
    ROLL_POSES,
    TUMBLE_ANIM,
    TUMBLE_POSES,
    TUMBLE_STEP_DEGREES,
    TUMBLE_TURN_DEGREES,
    HurtChoice,
    HurtMotion,
    HurtTrack,
    body_angle,
    flinch_anim,
    fly_pose,
    hurt_choice,
    tumble_pose,
)
from isofightr.sim.combat.constants import TUMBLE_KB as TUMBLE_KB_THRESHOLD
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import Fighter, GroundKind, Launch, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8
from isofightr.sim.match import Match
from isofightr.sim.math3d import ZERO3, Vec2, Vec3
from isofightr.sim.states.base import change_state
from isofightr.sim.states.interrupts import start_move

ANIMATED = tuple(c for c in list_character_ids() if load_sprite_set(c) is not None)
"""Every character with packed sprites must have every hit animation (D-066)."""
FLINCHES = frozenset(
    name
    for name in MELEE_HIT_ANIMS
    if name.startswith("hurt_") and (name.endswith(("_front", "_back")))
)
"""D-067's ground and air flinches."""
REQUIRED = (
    IMPACT_ANIM,
    FLY_ANIM,
    TUMBLE_ANIM,
    "hurt_light_front",
    "hurt_light_back",
    "hurt_heavy_front",
    "hurt_heavy_back",
)


def smash(
    damage: float, behind: bool = False, buttons: int = Button.STRONG
) -> tuple[Match, Fighter, HurtMotion, list]:
    """Rook hits Rook at ``damage`` (a forward smash, or ``buttons``' move); return the match,
    the target, the track and what the target showed each tick (its state and hit choice)."""
    match = make_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.E)
    place(match, target, 5.0, 6.0, facing=Dir8.E if behind else Dir8.W, damage=damage)
    anims = load_sprite_set("rook").anims
    motion = HurtMotion()
    shown = []
    for frames in [hold(buttons=buttons, frames=1)] + [neutral(1)] * 180:
        run(match, frames)
        motion.step(match.fighters, match.events, match.frame)
        track = motion.track(target.player_index)
        choice = hurt_choice(target, track, anims)
        shown.append((target.state, target.hitlag, choice, replace(track)))
    return match, target, motion, shown


@dataclass(frozen=True, slots=True)
class Tick:
    """What a hit victim was doing and showing on one tick from the hit on."""

    state: StateId
    hitlag: int
    hitstun: int
    grounded: bool
    choice: HurtChoice | None
    track: HurtTrack


def timeline(
    move: str, percent: float, lift: float | None = None, x: float = 4.0, ticks: int = 160
) -> tuple[float, list[Tick]]:
    """Rook does ``move`` on Rook at ``percent`` (held ``lift`` units in the air until the hit
    when given) on Training Grid; return the hit's knockback and a :class:`Tick` per tick from
    the hit on, while the victim is in play. The real sim, stepped as the battle does."""
    match = make_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, x, 6.0, facing=Dir8.E)
    place(match, target, x + 1.0, 6.0, facing=Dir8.W, damage=percent)
    floor = target.pos.z
    anims = load_sprite_set("rook").anims
    motion = HurtMotion()
    start_move(match, attacker, move)
    knockback: float | None = None
    shown: list[Tick] = []
    for _ in range(240 + ticks):
        if knockback is None and lift is not None:
            target.pos = Vec3(target.pos.x, target.pos.y, floor + lift)
            target.vel = ZERO3
            target.ground = GroundKind.NONE
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        motion.step(match.fighters, match.events, match.frame)
        for event in match.events:
            if isinstance(event, HitEvent) and event.target == 1 and knockback is None:
                knockback = event.knockback
        if knockback is None:
            continue
        if not target.in_play or len(shown) >= ticks:
            break
        track = replace(motion.track(1))
        choice = hurt_choice(target, track, anims)
        shown.append(
            Tick(target.state, target.hitlag, target.hitstun, target.grounded, choice, track)
        )
    assert knockback is not None, f"{move} never hit"
    return knockback, shown


# (move, percent, lift, x, the knockback band it must fall in)
CASES = [
    ("jab1", 0.0, 0.6, 4.0, (0.0, FLY_MIN_KB)),
    ("jab1", 0.0, None, 4.0, (0.0, FLY_MIN_KB)),
    ("ftilt", 20.0, 0.6, 4.0, (FLY_MIN_KB, TUMBLE_KB_THRESHOLD)),
    ("fsmash", 0.0, None, 4.0, (FLY_MIN_KB, TUMBLE_KB_THRESHOLD)),
    ("fsmash", 40.0, None, 4.0, (TUMBLE_KB_THRESHOLD, 110.0)),
    ("fsmash", 40.0, None, 10.0, (TUMBLE_KB_THRESHOLD, 110.0)),
    ("fsmash", 60.0, None, 4.0, (110.0, 200.0)),
    ("fsmash", 120.0, 0.6, 4.0, (110.0, 200.0)),
    ("fsmash", 150.0, None, 4.0, (200.0, 999.0)),
]


@pytest.mark.parametrize(("move", "percent", "lift", "x", "band"), CASES)
def test_hitstun_shows_damage_fly_or_a_flinch_and_never_the_tumble(
    move: str, percent: float, lift: float | None, x: float, band: tuple[float, float]
) -> None:
    """Decision D-067, from the real sim: no tumble pose while hitstun runs; damage-fly on
    every tick of a launch's hitstun; a flinch otherwise; the tumble only for a tumble-strength
    launch, from the first tick after hitstun while it is still airborne."""
    knockback, shown = timeline(move, percent, lift, x)
    assert band[0] <= knockback < band[1], f"the case must test its band (KB {knockback:.0f})"
    assert shown[0].choice is not None and shown[0].choice.anim == IMPACT_ANIM
    stun = [t for t in shown if t.hitlag == 0 and t.hitstun > 0 and t.state in HIT_STATES]
    assert stun, "the hit must stun"
    for tick in stun:
        assert tick.choice is not None
        assert tick.choice.anim != TUMBLE_ANIM, "never the tumble while hitstun runs"
        least = GROUND_FLY_MIN_KB if tick.grounded else FLY_MIN_KB
        if tick.state is StateId.TUMBLE or knockback >= least:
            assert tick.choice.anim == (ROLL_ANIM if tick.track.rolling else FLY_ANIM)
        else:
            assert tick.choice.anim in FLINCHES
            in_air = tick.track.airborne_hit and not tick.grounded
            assert tick.choice.anim.startswith("hurt_air_") is in_air
    after = [t for t in shown if t.state is StateId.TUMBLE and t.hitstun == 0]
    if knockback < TUMBLE_KB_THRESHOLD:
        assert not after
        assert all(t.choice is None or t.choice.anim != TUMBLE_ANIM for t in shown)
    for tick in after:
        assert tick.choice is not None and tick.choice.anim == TUMBLE_ANIM
    first = next(
        (i for i, t in enumerate(shown) if t.state is StateId.TUMBLE and t.hitstun == 0), None
    )
    if first is not None:
        before = shown[first - 1]
        assert before.hitstun == 1 and before.choice is not None
        assert before.choice.anim in (FLY_ANIM, ROLL_ANIM), "the tumble follows hitstun"
        if before.choice.anim == ROLL_ANIM:
            fly_angle = ROLL_BODY_ANGLE
        else:
            fly_angle = body_angle(FLY_ELEVATIONS[before.choice.pose])
        tumble_angle = shown[first].choice.pose * TUMBLE_STEP_DEGREES
        gap = abs((tumble_angle - fly_angle + 180.0) % 360.0 - 180.0)
        assert gap <= TUMBLE_STEP_DEGREES, "the tumble starts within one step of the fly pose"


def test_some_launches_tumble_after_their_hitstun() -> None:
    """The cases above must reach the tumble (Melee's DamageFall) at least twice: a launch off
    the stage at KB 80 to 109 and one over 200."""
    for move, percent, lift, x, _ in (CASES[5], CASES[8]):
        _, shown = timeline(move, percent, lift, x)
        assert any(t.choice and t.choice.anim == TUMBLE_ANIM for t in shown), (percent, x)


def test_the_pose_tables() -> None:
    assert flinch_anim(10.0, behind=False) == "hurt_light_front"
    assert flinch_anim(60.0, behind=True) == "hurt_heavy_back"
    assert [fly_pose(e) for e in (90, 50, 10, -50, -80)] == [0, 1, 2, 3, 4]
    assert [tumble_pose(a) for a in (0, 29, 30, 345, 360 + 61)] == [0, 1, 1, 0, 2]


def test_the_tumble_turns_at_a_fixed_rate_under_one_pose_a_tick() -> None:
    assert 0.0 < TUMBLE_TURN_DEGREES < TUMBLE_STEP_DEGREES, "never more than one pose a tick"


@pytest.mark.parametrize("character", ANIMATED)
def test_every_hit_animation_the_selector_asks_for_exists(character: str) -> None:
    anims = load_sprite_set(character).anims
    for name in REQUIRED:
        assert name in anims, name
    assert anims[TUMBLE_ANIM].poses == TUMBLE_POSES
    assert anims[FLY_ANIM].poses == 5
    assert anims[IMPACT_ANIM].poses == 1
    # D-067's set: every character with sprites has all of it (the selector still falls back
    # to the flinches above for a character that does not, such as a new one mid-build).
    missing = [name for name in MELEE_HIT_ANIMS if name not in anims]
    assert not missing, missing
    assert anims[ROLL_ANIM].poses == ROLL_POSES
    assert anims["hurt_electric"].poses == 2
    assert all(anims[name].poses == 4 for name in FLINCHES)


def test_a_strong_hit_freezes_flies_then_tumbles_back_first() -> None:
    _, _, _, shown = smash(150.0)
    frozen = [choice for state, hitlag, choice, _ in shown if hitlag > 0]
    assert frozen and all(c is not None and c.anim == IMPACT_ANIM for c in frozen)
    assert all(c.direction is None for c in frozen), "the freeze keeps the facing"
    flying = [c for _, hitlag, c, _ in shown if hitlag == 0 and c and c.anim == FLY_ANIM]
    tumbling = [c for _, hitlag, c, _ in shown if hitlag == 0 and c and c.anim == TUMBLE_ANIM]
    assert flying and tumbling
    # Launched east (screen right and down): drawn back first, facing west.
    assert {c.direction for c in flying} == {Dir8.W}
    first_tumble = next(i for i, (_, _, c, _) in enumerate(shown) if c and c.anim == TUMBLE_ANIM)
    assert all(c.anim != FLY_ANIM for _, _, c, _ in shown[first_tumble:] if c), "fly, then tumble"


def test_the_tumble_turns_smoothly_at_a_fixed_rate() -> None:
    _, _, _, shown = smash(150.0)
    angles = [track.angle for state, _, c, track in shown if c and c.anim == TUMBLE_ANIM]
    steps = [later - earlier for earlier, later in pairwise(angles)]
    assert steps and all(step == pytest.approx(TUMBLE_TURN_DEGREES) for step in steps)
    poses = [c.pose for _, _, c, _ in shown if c and c.anim == TUMBLE_ANIM]
    jumps = [(later - earlier) % TUMBLE_POSES for earlier, later in pairwise(poses)]
    assert all(jump in (0, 1) for jump in jumps), "one pose at a time, always forward"


def test_damage_fly_follows_the_arc_but_never_dives_head_first() -> None:
    """D-067: the fly pose follows the current travel as gravity bends it; a launch that did
    not start as a spike is drawn no steeper than down and forward (pose 3)."""
    _, _, _, shown = smash(150.0)
    poses = [c.pose for _, hitlag, c, _ in shown if hitlag == 0 and c and c.anim == FLY_ANIM]
    assert poses == sorted(poses), "up, level, then down, in order"
    assert len(set(poses)) >= 3 and max(poses) == 3


def test_a_launch_that_lands_on_its_feet_is_never_drawn_diving() -> None:
    """A launch under the tumble threshold lands into a flinch: its fly pose stays level or
    above while it falls (pose 2 at most), then the flinch shows on the ground."""
    knockback, shown = timeline("fsmash", 0.0)
    assert FLY_MIN_KB <= knockback < TUMBLE_KB_THRESHOLD
    poses = [t.choice.pose for t in shown if t.choice and t.choice.anim == FLY_ANIM]
    assert poses and max(poses) <= 2
    landed = [t for t in shown if t.state is StateId.FLINCH and t.grounded and t.hitstun > 0]
    assert landed and all(t.choice and t.choice.anim == "hurt_mid_heavy_front" for t in landed)


@pytest.mark.parametrize(("behind", "side"), [(False, "front"), (True, "back")])
def test_a_weak_hit_flinches_away_from_the_side_it_came_from(behind: bool, side: str) -> None:
    _, _, _, shown = smash(0.0, behind, buttons=Button.ATTACK)
    flinches = [c for state, _, c, _ in shown if state is StateId.FLINCH and c]
    assert flinches and {c.anim for c in flinches} == {f"hurt_mid_weak_{side}"}
    assert all(c.direction is None for c in flinches), "a flinch keeps the facing"
    assert [c.pose for c in flinches[:9]] == [0, 0, 1, 1, 1, 2, 2, 2, 3], "rock, then settle"


def test_after_hitstun_the_tumble_turns_on_until_the_fighter_acts_or_lands() -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, 6.0, 6.0, z=8.0)
    change_state(match, fighter, StateId.TUMBLE)
    fighter.hitstun = 0
    motion = HurtMotion()
    anims = load_sprite_set("rook").anims
    seen = []
    for _ in range(40):
        motion.step(match.fighters)
        seen.append(hurt_choice(fighter, motion.track(0), anims))
    assert all(c is not None and c.anim == TUMBLE_ANIM for c in seen)
    assert len({c.pose for c in seen if c}) >= 8, "it keeps turning"


def test_a_second_hit_during_hitstun_starts_the_track_over() -> None:
    _, target, motion, shown = smash(150.0)
    assert any(c and c.anim == FLY_ANIM for _, _, c, _ in shown)
    target.launch = Launch(knockback=20.0, heading=Vec2(1.0, 0.0), elevation=0.0, tumble=False)
    target.hitlag = 5
    motion.step([target])
    track = motion.track(target.player_index)
    assert track is not None and not track.flying and not track.tumbling
    assert track.knockback == 20.0 and track.launch_elevation is None
    choice = hurt_choice(target, track, load_sprite_set("rook").anims)
    assert choice is not None and choice.anim == IMPACT_ANIM


@pytest.mark.parametrize("state", [s for s in StateId if s not in HIT_STATES])
def test_every_other_state_takes_over_from_the_hit_poses(state: StateId) -> None:
    """Tech, wall tech, knockdown, rebound, a getup...: once the sim leaves the hit states the
    fighter shows that state's own animation, however the track was left."""
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    fighter.state = state
    track = HurtTrack(knockback=150.0, flying=True, tumbling=True, heading=Dir8.E)
    assert hurt_choice(fighter, track, load_sprite_set("rook").anims) is None


@pytest.mark.parametrize("teched", [False, True])
def test_landing_in_hitstun_hands_over_to_knockdown_or_the_tech(teched: bool) -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    place(match, fighter, 6.0, 6.0, z=3.0)
    change_state(match, fighter, StateId.TUMBLE)
    fighter.hitstun = 60
    motion = HurtMotion()
    anims = load_sprite_set("rook").anims
    for _ in range(80):
        if fighter.state is not StateId.TUMBLE:
            break
        fighter.tech_window = 20 if teched else 0  # a shield press always in time
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        motion.step(match.fighters)
        if fighter.state is StateId.TUMBLE:
            choice = hurt_choice(fighter, motion.track(0), anims)
            assert choice is not None and choice.anim == FLY_ANIM
    assert fighter.state is (StateId.TECH if teched else StateId.KNOCKDOWN)
    assert hurt_choice(fighter, motion.track(0), anims) is None


def test_without_a_track_a_fighter_shows_its_states_own_animation() -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    change_state(match, fighter, StateId.TUMBLE)
    anims = load_sprite_set("rook").anims
    assert hurt_choice(fighter, None, anims) is None
    look = fighter_look(fighter, 0, anims=anims)
    assert look.sprite is not None and look.sprite.anim == TUMBLE_ANIM and look.direction is None


def test_the_track_never_changes_the_sim() -> None:
    """Two matches on the same inputs, one with the hit poses followed and drawn every tick,
    hash alike on every tick (so no golden can change)."""
    watched, plain = make_match(stocks=None), make_match(stocks=None)
    anims = load_sprite_set("rook").anims
    motion = HurtMotion()
    for match in (watched, plain):
        place(match, match.fighters[0], 4.0, 6.0, facing=Dir8.E)
        place(match, match.fighters[1], 5.0, 6.0, facing=Dir8.W, damage=150.0)
    for frames in [hold(buttons=Button.STRONG, frames=1)] + [neutral(1)] * 150:
        run(watched, frames)
        run(plain, frames)
        motion.step(watched.fighters)
        for fighter in watched.fighters:
            hurt_choice(fighter, motion.track(fighter.player_index), anims)
            fighter_look(fighter, watched.frame, anims=anims, hurt=motion.track(0))
        assert watched.state_hash() == plain.state_hash()
