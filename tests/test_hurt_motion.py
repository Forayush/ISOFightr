"""Tests for the hit poses and the tumble's turn (decision D-066): presentation state derived
from the sim, never written back."""

from dataclasses import replace
from itertools import pairwise

import pytest

from helpers import hold, make_match, neutral, place, run
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.render.fighter_look import fighter_look
from isofightr.render.hurt_motion import (
    FLY_ANIM,
    IMPACT_ANIM,
    SETTLED_ANIM,
    TUMBLE_ANIM,
    TUMBLE_POSES,
    TUMBLE_STEP_DEGREES,
    TURN_FAST_DEGREES,
    TURN_SLOW_DEGREES,
    HurtMotion,
    flinch_anim,
    fly_pose,
    hurt_choice,
    tumble_pose,
    turn_rate,
)
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import Button, Dir8
from isofightr.sim.match import Match
from isofightr.sim.states.base import change_state

HIT_ANIMS_DONE = ("rook", "bramble")
"""Characters whose hit animations are built (D-066 group 2 does Rook first)."""
REQUIRED = (
    IMPACT_ANIM,
    FLY_ANIM,
    TUMBLE_ANIM,
    SETTLED_ANIM,
    "hurt_light_front",
    "hurt_light_back",
    "hurt_heavy_front",
    "hurt_heavy_back",
)


def smash(damage: float, behind: bool = False) -> tuple[Match, Fighter, HurtMotion, list]:
    """Rook forward-smashes Rook at ``damage``; return the match, the target, the track and
    what the target showed each tick (its state and hit choice)."""
    match = make_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.E)
    place(match, target, 5.0, 6.0, facing=Dir8.E if behind else Dir8.W, damage=damage)
    anims = load_sprite_set("rook").anims
    motion = HurtMotion()
    shown = []
    for frames in [hold(buttons=Button.STRONG, frames=1)] + [neutral(1)] * 120:
        run(match, frames)
        motion.step(match.fighters)
        track = motion.track(target.player_index)
        choice = hurt_choice(target, track, anims)
        shown.append((target.state, target.hitlag, choice, replace(track)))
    return match, target, motion, shown


def test_the_pose_tables() -> None:
    assert flinch_anim(10.0, behind=False) == "hurt_light_front"
    assert flinch_anim(60.0, behind=True) == "hurt_heavy_back"
    assert [fly_pose(e) for e in (90, 50, 10, -50, -80)] == [0, 1, 2, 3, 4]
    assert [tumble_pose(a) for a in (0, 29, 30, 345, 360 + 61)] == [0, 1, 1, 0, 2]


def test_a_tumble_turns_faster_the_faster_it_flies() -> None:
    rates = [turn_rate(speed, 0.4) for speed in (0.0, 0.1, 0.2, 0.4, 0.8)]
    assert rates == sorted(rates)
    assert rates[0] == TURN_SLOW_DEGREES and rates[-1] == TURN_FAST_DEGREES
    assert TURN_FAST_DEGREES < TUMBLE_STEP_DEGREES, "never more than one pose a tick"


@pytest.mark.parametrize("character", HIT_ANIMS_DONE)
def test_every_hit_animation_the_selector_asks_for_exists(character: str) -> None:
    anims = load_sprite_set(character).anims
    for name in REQUIRED:
        assert name in anims, name
    assert anims[TUMBLE_ANIM].poses == TUMBLE_POSES
    assert anims[FLY_ANIM].poses == 5
    assert anims[IMPACT_ANIM].poses == 1


def test_a_strong_hit_freezes_flies_then_tumbles_back_first() -> None:
    _, _, _, shown = smash(100.0)
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


def test_the_tumble_turns_smoothly_and_slows_as_the_knockback_runs_out() -> None:
    _, _, _, shown = smash(100.0)
    angles = [track.angle for state, _, c, track in shown if c and c.anim == TUMBLE_ANIM]
    steps = [later - earlier for earlier, later in pairwise(angles)]
    assert steps and all(0.0 < step <= TURN_FAST_DEGREES for step in steps)
    assert steps == sorted(steps, reverse=True), "never speeds up"
    poses = [c.pose for _, _, c, _ in shown if c and c.anim == TUMBLE_ANIM]
    jumps = [(later - earlier) % TUMBLE_POSES for earlier, later in pairwise(poses)]
    assert all(jump in (0, 1) for jump in jumps), "one pose at a time, always forward"


@pytest.mark.parametrize(("behind", "side"), [(False, "front"), (True, "back")])
def test_a_weak_hit_flinches_away_from_the_side_it_came_from(behind: bool, side: str) -> None:
    _, _, _, shown = smash(0.0, behind)
    flinches = [c for state, _, c, _ in shown if state is StateId.FLINCH and c]
    assert flinches and {c.anim for c in flinches} == {f"hurt_heavy_{side}"}
    assert all(c.direction is None for c in flinches), "a flinch keeps the facing"
    assert [c.pose for c in flinches[:10]] == [0, 0, 1, 1, 1, 2, 2, 2, 3, 3], "rock, then settle"


def test_after_hitstun_the_body_turns_upright_then_falls() -> None:
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
    assert seen[0] is not None and seen[0].anim == TUMBLE_ANIM
    assert seen[-1] is not None and seen[-1].anim == SETTLED_ANIM
    settled = next(i for i, choice in enumerate(seen) if choice and choice.anim == SETTLED_ANIM)
    assert seen[settled - 1] is not None and seen[settled - 1].pose == 0, "upright first"


def test_without_a_track_a_fighter_shows_its_states_own_animation() -> None:
    match = make_match(stocks=None)
    fighter = match.fighters[0]
    change_state(match, fighter, StateId.TUMBLE)
    anims = load_sprite_set("rook").anims
    assert hurt_choice(fighter, None, anims) is None
    look = fighter_look(fighter, 0, anims=anims)
    assert look.sprite is not None and look.sprite.anim == TUMBLE_ANIM and look.direction is None


def test_the_track_never_changes_the_sim() -> None:
    match, _, motion, _ = smash(100.0)
    before = match.state_hash()
    motion.step(match.fighters)
    assert match.state_hash() == before
