"""How a crouch is drawn (decision D-069, M18 group 2): the drop, the hold, the rise, the
crouching down tilt and the placeholder, and a crouch capsule that matches the drawing."""

from statistics import mean

import pytest

from helpers import hold, make_match, make_stage, neutral, place, run
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.sprite_sheet import AnimInfo, load_sprite_set
from isofightr.render.anim_select import select_anim
from isofightr.render.crouch_motion import (
    CROUCH_ANIMS,
    ENTER_ANIM,
    EXIT_ANIM,
    EXIT_TICKS,
    HOLD_ANIM,
    CrouchMotion,
    enter_frames,
)
from isofightr.render.fighter_look import Pose, fighter_look
from isofightr.render.placeholder_art import BODY_HEIGHT, CROUCH_BODY_HEIGHT, build_fighter
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, Button, Dir8, InputFrame
from isofightr.sim.match import Match

DRAWN = tuple(c for c in list_character_ids() if load_sprite_set(c) is not None)
"""Every character with sprites: each needs its crouch drawn and its capsule measured."""
DIRECTIONS = [direction.name for direction in Dir8]
AGREEMENT = 0.03
"""How far the crouch capsule's share of the standing one may be from the drawing's."""


def shown(match: Match, inputs: list[InputFrame]) -> list[tuple[StateId, str, int]]:
    """Run player 1's inputs; return its state and the pose it shows on every tick."""
    sprites = load_sprite_set("rook")
    assert sprites is not None
    motion = CrouchMotion()
    rook = match.fighters[0]
    seen = []
    for frame in inputs:
        run(match, [frame])
        motion.step(match.fighters)
        look = fighter_look(rook, match.frame, anims=sprites.anims, crouch=motion.track(0))
        assert look.sprite is not None
        seen.append((rook.state, look.sprite.anim, look.sprite.pose))
    return seen


@pytest.fixture
def match() -> Match:
    match = make_match()
    place(match, match.fighters[0], 4.5, 6.0)
    place(match, match.fighters[1], 9.0, 6.0)
    return match


DOWN = hold(vertical=VERTICAL_DOWN, frames=1)[0]
STAND = neutral(1)[0]


def test_a_crouch_drops_in_then_holds_then_rises(match: Match) -> None:
    sprites = load_sprite_set("rook")
    assert sprites is not None
    enter = enter_frames(sprites.anims)
    assert enter == 3
    seen = shown(match, [DOWN] * 20 + [STAND] * 6)
    assert seen[:enter] == [(StateId.CROUCH, ENTER_ANIM, pose) for pose in range(enter)]
    assert {anim for _, anim, _ in seen[enter:20]} == {HOLD_ANIM}
    assert seen[enter][2] == 0, "the hold starts on its first pose"
    rise = seen[20 : 20 + EXIT_TICKS]
    assert rise == [(StateId.IDLE, EXIT_ANIM, pose) for pose in range(EXIT_TICKS)]
    assert seen[20 + EXIT_TICKS][1] == "idle"


def test_a_down_tilt_out_of_the_crouch_goes_back_to_the_hold_without_dropping_again(
    match: Match,
) -> None:
    attack = hold(buttons=Button.ATTACK, frames=1, vertical=VERTICAL_DOWN)[0]
    seen = shown(match, [DOWN] * 8 + [attack] + [DOWN] * 30)
    tilt = [anim for state, anim, _ in seen if state is StateId.ATTACK]
    assert tilt and set(tilt) == {"dtilt"}
    after = [(anim, pose) for state, anim, pose in seen[9:] if state is StateId.CROUCH]
    assert after and after[0] == (HOLD_ANIM, 0), "no second drop after the tilt"
    assert ENTER_ANIM not in {anim for anim, _ in after}


def test_a_down_tilt_let_go_into_standing_rises(match: Match) -> None:
    attack = hold(buttons=Button.ATTACK, frames=1, vertical=VERTICAL_DOWN)[0]
    total = load_character("rook").moves["dtilt"].total
    seen = shown(match, [attack] + [STAND] * (total + 4))
    first_idle = next(i for i, (state, _, _) in enumerate(seen) if state is StateId.IDLE)
    assert [anim for _, anim, _ in seen[first_idle : first_idle + EXIT_TICKS]] == [EXIT_ANIM] * 3


def test_jumping_out_of_the_crouch_does_not_rise_first(match: Match) -> None:
    jump = hold(buttons=Button.JUMP, frames=1, vertical=VERTICAL_DOWN)[0]
    seen = shown(match, [DOWN] * 8 + [jump] + [STAND] * 3)
    assert EXIT_ANIM not in {anim for _, anim, _ in seen[8:]}


def test_the_platform_drop_wind_up_is_the_crouch_drop() -> None:
    stage = make_stage(["0000000"] * 7, platforms=[(2, 2, 5, 5, 2.5)])
    match = make_match(stage)
    rook = match.fighters[0]
    place(match, rook, 3.5, 3.5)
    sprites = load_sprite_set("rook")
    assert sprites is not None
    poses = []
    for _ in range(3):
        run(match, [DOWN])
        assert rook.state is StateId.PLATFORM_DROP
        choice = select_anim(rook, sprites.anims)
        assert choice is not None
        poses.append((choice.anim, choice.pose))
    assert poses == [(ENTER_ANIM, 0), (ENTER_ANIM, 1), (ENTER_ANIM, 2)]


def test_without_the_crouch_animations_the_crouch_falls_back_to_the_land_squat(
    match: Match,
) -> None:
    anims = {
        "idle": AnimInfo(poses=1, loop=True, fps=1),
        "land": AnimInfo(poses=2, loop=False, starts=(1, 3)),
    }
    run(match, [DOWN] * 5)
    rook = match.fighters[0]
    look = fighter_look(rook, match.frame, anims=anims, crouch=None)
    assert look.sprite is not None and look.sprite.anim == "land"


def test_the_placeholder_is_shorter_while_low(match: Match) -> None:
    rook = match.fighters[0]
    assert fighter_look(rook, match.frame).pose is Pose.STAND
    run(match, [DOWN] * 2)
    assert fighter_look(rook, match.frame).pose is Pose.CROUCH
    standing = build_fighter(0, Dir8.SE).getbbox()
    crouching = build_fighter(0, Dir8.SE, crouching=True).getbbox()
    assert standing is not None and crouching is not None
    assert crouching[1] - standing[1] == BODY_HEIGHT - CROUCH_BODY_HEIGHT
    assert crouching[3] == standing[3], "the feet stay where they were"


# --- the art ------------------------------------------------------------------------------


@pytest.mark.parametrize("character_id", DRAWN)
def test_the_crouch_animations_exist(character_id: str) -> None:
    sprites = load_sprite_set(character_id)
    assert sprites is not None
    anims = sprites.anims
    assert all(name in anims for name in CROUCH_ANIMS)
    assert anims[HOLD_ANIM].loop and anims[HOLD_ANIM].poses == 2
    assert not anims[ENTER_ANIM].loop and 3 <= enter_frames(anims) <= 4
    assert not anims[EXIT_ANIM].loop and max(anims[EXIT_ANIM].starts) == EXIT_TICKS


@pytest.mark.parametrize("character_id", DRAWN)
def test_the_down_tilt_starts_and_ends_on_the_crouch(character_id: str) -> None:
    """No pop: the down tilt's first and last poses are drawn exactly as the hold's first."""
    sprites = load_sprite_set(character_id)
    assert sprites is not None
    last = sprites.anims["dtilt"].poses - 1
    for direction in DIRECTIONS:
        hold_rect = sprites.frame(HOLD_ANIM, 0, direction)
        for pose in (0, last):
            rect = sprites.frame("dtilt", pose, direction)
            same = (rect.width, rect.height, rect.pivot_x, rect.pivot_y)
            assert same == (
                hold_rect.width,
                hold_rect.height,
                hold_rect.pivot_x,
                hold_rect.pivot_y,
            ), (direction, pose)


def drawn_height(character_id: str, anim: str) -> float:
    sprites = load_sprite_set(character_id)
    assert sprites is not None
    return mean(
        sprites.frame(anim, pose, direction).pivot_y
        for pose in range(sprites.anims[anim].poses)
        for direction in DIRECTIONS
    )


@pytest.mark.parametrize("character_id", DRAWN)
def test_the_crouch_capsule_matches_the_drawn_crouch(character_id: str) -> None:
    """D-069 (agreed): the crouch hurtbox is set from the drawing. Its top, as a share of the
    standing hurtbox's, is the crouch hold's drawn height as a share of the idle stance's."""
    body = load_character(character_id).body
    drawn = drawn_height(character_id, HOLD_ANIM) / drawn_height(character_id, "idle")
    capsule = body.crouch_hurtbox.z1 / body.hurtbox.z1
    assert capsule == pytest.approx(drawn, abs=AGREEMENT)
    share = (body.crouch_hurtbox.z1 - body.hurtbox.z0) / (body.hurtbox.z1 - body.hurtbox.z0)
    assert 0.6 <= share <= 0.75, "a crouch, not a stance or a lying pose"
