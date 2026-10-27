"""Crouching, the low-profile hurtbox and crouching down tilts (decision D-069, M18).

Scenario tests: hold the down modifier on solid ground and the fighter crouches; it turns
without moving, stands when down is let go, and every down move, the grab, the jump and the
spot dodge come out of it. A crouching fighter, and one in a down tilt, is hit with a lower
capsule. Landings are Melee's: the landing lag plays standing, then a fighter still holding
down crouches.
"""

from dataclasses import replace

import pytest

from helpers import hold, make_match, make_stage, neutral, place, run
from isofightr.ai.view import view_fighter
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.sim.combat.hitbox import ActiveHitbox, hits, hurtbox, hurtbox_shape
from isofightr.sim.constants import CROUCH_HURTBOX_SHARE
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import Fighter, GroundKind, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, Dir8
from isofightr.sim.match import Match
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.move_def import Effect, FrameRange

DOWN = VERTICAL_DOWN
CHARACTERS = list_character_ids()
PLATFORM_STAGE = make_stage(["0000000"] * 7, platforms=[(2, 2, 5, 5, 2.5)])

DTILTS = {
    # character: total, faf, active frames, hitboxes (id, offset, radius, damage, angle, bkb,
    # kbg, effect) as they were before D-069
    "rook": (
        26,
        27,
        (5, 7),
        (
            (0, (1.0, 0.0, 0.4), 0.45, 6.0, 75.0, 25.0, 80.0, Effect.NORMAL),
            (1, (0.5, 0.0, 0.4), 0.4, 6.0, 75.0, 25.0, 80.0, Effect.NORMAL),
        ),
    ),
    "bramble": (
        32,
        33,
        (8, 10),
        ((0, (1.3, 0.0, 0.4), 0.55, 10.0, 30.0, 30.0, 70.0, Effect.NORMAL),),
    ),
    "zephyr": (18, 19, (4, 6), ((0, (0.9, 0.0, 0.3), 0.4, 5.0, 75.0, 30.0, 70.0, Effect.NORMAL),)),
    "mote": (24, 25, (7, 9), ((0, (1.3, 0.0, 0.3), 0.45, 7.0, 30.0, 25.0, 75.0, Effect.FIRE),)),
}


def crouch_down(match: Match, fighter: Fighter, frames: int = 2) -> None:
    run(match, hold(vertical=DOWN, frames=frames))


@pytest.fixture
def match() -> Match:
    match = make_match()
    place(match, match.fighters[0], 4.5, 6.0)
    place(match, match.fighters[1], 9.0, 6.0)
    return match


@pytest.fixture
def rook(match: Match) -> Fighter:
    return match.fighters[0]


# --- the state ----------------------------------------------------------------------------


def test_holding_down_on_solid_ground_crouches_at_once(match: Match, rook: Fighter) -> None:
    run(match, hold(vertical=DOWN, frames=1))
    assert rook.state is StateId.CROUCH
    start = rook.pos
    crouch_down(match, rook, 30)
    assert rook.state is StateId.CROUCH and rook.pos == start


def test_holding_down_on_a_soft_platform_still_drops_through() -> None:
    match = make_match(PLATFORM_STAGE)
    rook = match.fighters[0]
    place(match, rook, 3.5, 3.5)
    assert rook.ground is GroundKind.PLATFORM
    run(match, hold(vertical=DOWN, frames=1))
    assert rook.state is StateId.PLATFORM_DROP


def test_the_stick_turns_a_crouching_fighter_without_moving_it(match: Match, rook: Fighter) -> None:
    crouch_down(match, rook)
    start = rook.pos
    for direction in (Dir8.N, Dir8.W, Dir8.NE, Dir8.S):
        run(match, hold(direction, frames=3, vertical=DOWN))
        assert rook.state is StateId.CROUCH
        assert rook.facing is direction
    assert rook.pos == start


def test_a_dash_flick_is_ignored_while_crouching(match: Match, rook: Fighter) -> None:
    crouch_down(match, rook)
    run(match, hold(Dir8.SE, frames=1, vertical=DOWN, magnitude=1.0))
    run(match, hold(Dir8.SE, frames=3, vertical=DOWN))
    assert rook.state is StateId.CROUCH
    run(match, hold(frames=1))
    assert rook.state is StateId.IDLE, "the flick made while crouching is not kept for later"


def test_letting_go_of_down_or_pressing_up_stands(match: Match, rook: Fighter) -> None:
    crouch_down(match, rook)
    run(match, neutral(1))
    assert rook.state is StateId.IDLE
    crouch_down(match, rook)
    run(match, hold(vertical=VERTICAL_UP, frames=1))
    assert rook.state is not StateId.CROUCH


def test_letting_go_of_down_with_the_stick_held_walks(match: Match, rook: Fighter) -> None:
    crouch_down(match, rook)
    run(match, hold(Dir8.SE, frames=4, vertical=DOWN))
    run(match, hold(Dir8.SE, frames=1))
    assert rook.state is StateId.WALK, "a stick held from the crouch walks; a flick dashes"


def test_a_fresh_down_press_while_walking_crouches(match: Match, rook: Fighter) -> None:
    run(match, hold(Dir8.SE, Button.WALK, frames=5))
    assert rook.state is StateId.WALK
    run(match, hold(Dir8.SE, Button.WALK, frames=1, vertical=DOWN))
    assert rook.state is StateId.CROUCH


def test_dashing_and_running_ignore_down(match: Match, rook: Fighter) -> None:
    run(match, neutral(1))
    run(match, hold(Dir8.SE, frames=2))
    assert rook.state is StateId.DASH
    run(match, hold(Dir8.SE, frames=1, vertical=DOWN))
    assert rook.state is StateId.DASH
    run(match, hold(Dir8.SE, frames=20))
    assert rook.state is StateId.RUN
    run(match, hold(Dir8.SE, frames=3, vertical=DOWN))
    assert rook.state is StateId.RUN


def test_a_crouch_does_not_slide_off_an_edge(match: Match, rook: Fighter) -> None:
    place(match, rook, 11.6, 6.0)
    crouch_down(match, rook)
    rook.vel = Vec3(0.12, 0.0, 0.0)
    crouch_down(match, rook, 20)
    assert rook.state is StateId.CROUCH and rook.grounded


# --- actions out of the crouch ------------------------------------------------------------


@pytest.mark.parametrize(
    ("button", "state", "move_slot"),
    [
        (Button.ATTACK, StateId.ATTACK, "dtilt"),
        (Button.STRONG, StateId.ATTACK, "dsmash"),
        (Button.SPECIAL, StateId.ATTACK, "dspecial"),
        (Button.GRAB, StateId.GRAB, None),
        (Button.JUMP, StateId.JUMP_SQUAT, None),
        (Button.SHIELD, StateId.SPOT_DODGE, None),
    ],
)
def test_actions_out_of_the_crouch(
    match: Match, rook: Fighter, button: Button, state: StateId, move_slot: str | None
) -> None:
    crouch_down(match, rook)
    run(match, hold(buttons=button, frames=1, vertical=DOWN))
    assert rook.state is state
    if move_slot is not None:
        assert rook.move_id == getattr(rook.character.moveset, move_slot)


def test_a_down_tilt_with_down_held_goes_straight_back_into_the_crouch(
    match: Match, rook: Fighter
) -> None:
    crouch_down(match, rook)
    run(match, hold(buttons=Button.ATTACK, frames=1, vertical=DOWN))
    states = []
    for _ in range(rook.character.moves["dtilt"].total + 2):
        run(match, hold(vertical=DOWN, frames=1))
        states.append(rook.state)
    first_crouch = states.index(StateId.CROUCH)
    assert set(states[:first_crouch]) == {StateId.ATTACK}, "no standing frame in between"
    assert set(states[first_crouch:]) == {StateId.CROUCH}


def test_a_fast_fall_landing_with_down_held_lags_standing_then_crouches(
    match: Match, rook: Fighter
) -> None:
    """Melee's landing (D-069, agreed): the landing lag first, then the crouch."""
    place(match, rook, 4.5, 6.0, z=3.0)
    run(match, neutral(2))
    run(match, hold(vertical=DOWN, frames=1))
    assert rook.fast_falling
    states = []
    while len(states) < 60 and StateId.CROUCH not in states:
        run(match, hold(vertical=DOWN, frames=1))
        states.append(rook.state)
    landed = states.index(StateId.LAND)
    lag = rook.character.movement.land_lag
    assert states[landed : landed + lag] == [StateId.LAND] * lag
    assert states[landed + lag] is StateId.CROUCH


def test_letting_go_of_down_during_the_landing_lag_stands(match: Match, rook: Fighter) -> None:
    place(match, rook, 4.5, 6.0, z=3.0)
    run(match, neutral(2))
    run(match, hold(vertical=DOWN, frames=1))
    while rook.state is not StateId.LAND:
        run(match, hold(vertical=DOWN, frames=1))
    run(match, neutral(rook.character.movement.land_lag + 2))
    assert rook.state is StateId.IDLE


def test_a_landing_never_attacks_by_itself(match: Match, rook: Fighter) -> None:
    place(match, rook, 4.5, 6.0, z=3.0)
    run(match, neutral(2))
    for _ in range(80):
        run(match, hold(vertical=DOWN, frames=1))
        assert rook.state is not StateId.ATTACK


# --- the low-profile hurtbox --------------------------------------------------------------


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_the_crouch_capsule_is_lower_and_the_same_width(character_id: str) -> None:
    body = load_character(character_id).body
    standing, crouch = body.hurtbox, body.crouch_hurtbox
    assert crouch.radius == standing.radius and crouch.z0 == standing.z0
    assert crouch.z1 < standing.z1
    assert crouch.z1 >= crouch.z0 + 2 * crouch.radius


def test_the_default_crouch_capsule_is_d069s_share() -> None:
    body = load_character("rook").body
    expected = body.hurtbox.z0 + CROUCH_HURTBOX_SHARE * (body.hurtbox.z1 - body.hurtbox.z0)
    assert body.crouch_hurtbox == body.hurtbox.lowered(CROUCH_HURTBOX_SHARE)
    assert body.crouch_hurtbox.z1 == pytest.approx(expected)


def test_a_crouching_fighter_has_the_crouch_capsule(match: Match, rook: Fighter) -> None:
    assert hurtbox_shape(rook) == rook.character.body.hurtbox
    crouch_down(match, rook)
    assert hurtbox_shape(rook) == rook.character.body.crouch_hurtbox
    top = hurtbox(rook).end.z + hurtbox(rook).radius
    assert top == pytest.approx(rook.pos.z + rook.character.body.crouch_hurtbox.z1)
    run(match, neutral(1))
    assert hurtbox_shape(rook) == rook.character.body.hurtbox


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_a_down_tilt_is_low_for_its_whole_length(character_id: str) -> None:
    match = make_match(fighters=(character_id, character_id))
    fighter = match.fighters[0]
    place(match, fighter, 4.5, 6.0)
    place(match, match.fighters[1], 9.0, 6.0)
    move = fighter.character.moves[fighter.character.moveset.dtilt]
    assert move.low_profile == FrameRange(1, move.total)
    run(match, hold(buttons=Button.ATTACK, frames=1, vertical=DOWN))
    shapes = []
    while fighter.state is StateId.ATTACK:
        shapes.append(hurtbox_shape(fighter))
        run(match, neutral(1))
    assert len(shapes) == move.total
    assert set(shapes) == {fighter.character.body.crouch_hurtbox}
    assert hurtbox_shape(fighter) == fighter.character.body.hurtbox


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_the_down_tilts_frame_data_did_not_change(character_id: str) -> None:
    """D-069: the crouching down tilts keep the old timing, damage, angle and knockback."""
    character = load_character(character_id)
    move = character.moves[character.moveset.dtilt]
    total, faf, (first, last), boxes = DTILTS[character_id]
    assert (move.total, move.faf, move.landing_lag, move.motion) == (total, faf, 0, ())
    assert [(window.frames.first, window.frames.last) for window in move.windows] == [(first, last)]
    actual = [
        (
            box.id,
            (box.offset.x, box.offset.y, box.offset.z),
            box.radius,
            box.damage,
            box.angle,
            box.bkb,
            box.kbg,
            box.effect,
        )
        for box in sorted(move.windows[0].hitboxes, key=lambda hitbox: hitbox.id)
    ]
    assert actual == list(boxes)


def high_hitbox(in_front_of: Fighter, height: float) -> ActiveHitbox:
    """A small hitbox at ``height`` above the feet, centred on the fighter."""
    centre = in_front_of.pos + Vec3(0.0, 0.0, height)
    template = load_character("rook").moves["jab1"].windows[0].hitboxes[0]
    definition = replace(template, radius=0.2)
    return ActiveHitbox(definition, centre, centre)


def test_a_high_hitbox_passes_over_a_crouching_fighter(match: Match, rook: Fighter) -> None:
    box = high_hitbox(rook, 2.0)
    assert hits(box, rook)
    crouch_down(match, rook)
    box = high_hitbox(rook, 2.0)
    assert not hits(box, rook)
    assert hits(high_hitbox(rook, 1.0), rook), "a low one still hits"


def test_a_grab_still_takes_a_crouching_fighter() -> None:
    match = make_match()
    grabber, target = match.fighters
    place(match, grabber, 5.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0)
    ahead = Vec2(5.0, 6.0) + Dir8.SE.world * 1.0
    place(match, target, ahead.x, ahead.y)
    run(match, neutral(1), hold(vertical=DOWN, frames=1))
    assert target.state is StateId.CROUCH
    run(match, hold(buttons=Button.GRAB, frames=1), hold(vertical=DOWN, frames=1))
    for _ in range(12):
        run(match, neutral(1), hold(vertical=DOWN, frames=1))
    assert grabber.state is StateId.GRAB_HOLD and target.state is StateId.GRABBED


def test_a_hit_in_the_crouch_is_a_normal_hit() -> None:
    """No crouch cancel: a crouching target takes the same knockback as a standing one."""
    knockbacks = []
    for crouching in (False, True):
        match = make_match()
        attacker, target = match.fighters
        place(match, attacker, 5.0, 6.0, facing=Dir8.SE)
        ahead = Vec2(5.0, 6.0) + Dir8.SE.world * 1.0
        place(match, target, ahead.x, ahead.y)
        target.damage = 50.0
        target_input = hold(vertical=DOWN if crouching else 0, frames=1)
        run(match, neutral(1), target_input)
        assert (target.state is StateId.CROUCH) == crouching
        run(match, hold(buttons=Button.ATTACK, frames=1, vertical=DOWN), target_input)
        events: list[HitEvent] = []
        for _ in range(20):
            run(match, neutral(1), target_input)
            events += [event for event in match.events if isinstance(event, HitEvent)]
        assert events, "the down tilt hits"
        knockbacks.append(events[0].knockback)
        assert target.state in (StateId.FLINCH, StateId.TUMBLE)
    assert knockbacks[0] == knockbacks[1]


# --- who reads the crouch -----------------------------------------------------------------


def test_the_cpu_sees_a_crouch_as_free_and_its_low_capsule(match: Match, rook: Fighter) -> None:
    crouch_down(match, rook)
    view = view_fighter(rook)
    assert view.free
    assert view.hurtbox == rook.character.body.crouch_hurtbox


def test_shield_and_down_together_still_spot_dodge_through_the_shield(
    match: Match, rook: Fighter
) -> None:
    """The old path is untouched: the shield comes up, then the down press dodges."""
    run(match, hold(buttons=Button.SHIELD, frames=1, vertical=DOWN))
    assert rook.state is StateId.SHIELD
    run(match, hold(buttons=Button.SHIELD, frames=1, vertical=DOWN))
    assert rook.state is StateId.SPOT_DODGE


def test_a_shield_press_while_crouching_spot_dodges_at_once(match: Match, rook: Fighter) -> None:
    crouch_down(match, rook, 10)
    run(match, hold(buttons=Button.SHIELD, frames=1, vertical=DOWN))
    assert rook.state is StateId.SPOT_DODGE


def test_a_down_press_while_shielding_still_spot_dodges(match: Match, rook: Fighter) -> None:
    run(match, hold(buttons=Button.SHIELD, frames=12))
    assert rook.state is StateId.SHIELD
    run(match, hold(buttons=Button.SHIELD, frames=1, vertical=DOWN))
    assert rook.state is StateId.SPOT_DODGE, "a fresh down press while shielding, as before"


def test_no_crouch_on_the_revival_platform() -> None:
    match = make_match()
    rook = match.fighters[0]
    rook.ground = GroundKind.REVIVAL
    rook.state = StateId.REVIVAL
    run(match, hold(vertical=DOWN, frames=3))
    assert rook.state is not StateId.CROUCH
