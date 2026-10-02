"""Scenario tests for the combat core: scripted inputs against a real match.

Plan notes "05 - Combat Core" and "07 - Fighter State Machine and Move Data".
"""

import dataclasses
import math
from types import MappingProxyType

import pytest

from helpers import hold, make_match, neutral, place, run, run_until
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.events import ClankEvent, HitEvent, KoEvent
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, Dir8, InputFrame
from isofightr.sim.kill_calc import kill_percent, move_kills
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2
from isofightr.sim.move_def import MoveDef
from isofightr.sim.states.interrupts import start_move

ROOK = load_character("rook")
FRESH = c.FRESH_BONUS
ORIGIN_X = 4.0
ORIGIN_Y = 6.0

ATTACK = hold(buttons=Button.ATTACK, frames=1)
STRONG = hold(buttons=Button.STRONG, frames=1)


def duel(
    gap: float = 1.0, damage: float = 0.0, stage: str = "training_grid"
) -> tuple[Match, Fighter, Fighter]:
    """P1 faces P2 along +x, ``gap`` units apart, on open ground."""
    match = make_match(stage, stocks=None)
    attacker, target = match.fighters
    place(match, attacker, ORIGIN_X, ORIGIN_Y, facing=Dir8.SE)
    place(match, target, ORIGIN_X + gap, ORIGIN_Y, facing=Dir8.NW, damage=damage)
    return match, attacker, target


def run_collect(
    match: Match, p1: list[InputFrame], p2: list[InputFrame] | None = None
) -> list[tuple[int, object]]:
    """Run inputs one tick at a time and return ``(tick, event)`` for hits, clanks and KOs."""
    seen: list[tuple[int, object]] = []
    for index, frame in enumerate(p1):
        other = None if p2 is None or index >= len(p2) else [p2[index]]
        run(match, [frame], other)
        seen.extend(
            (index + 1, event)
            for event in match.events
            if isinstance(event, HitEvent | ClankEvent | KoEvent)
        )
    return seen


def hit_events(seen: list[tuple[int, object]]) -> list[tuple[int, HitEvent]]:
    return [(tick, event) for tick, event in seen if isinstance(event, HitEvent)]


def with_move(move: MoveDef) -> CharacterDef:
    """Return Rook with one move replaced (for mechanics no shipped move uses yet)."""
    moves = dict(ROOK.moves)
    moves[move.id] = move
    return dataclasses.replace(ROOK, moves=MappingProxyType(moves))


# --- a single hit -------------------------------------------------------------------------


def test_jab_hits_on_its_first_active_frame_and_stuns() -> None:
    match, attacker, target = duel()
    seen = hit_events(run_collect(match, ATTACK + neutral(2)))
    [(tick, hit)] = seen
    assert tick == ROOK.moves["jab1"].first_active_frame == 3
    assert (hit.attacker, hit.target, hit.move_id) == (0, 1, "jab1")
    assert hit.damage == pytest.approx(2.5 * FRESH)
    assert target.damage == pytest.approx(2.5 * FRESH)
    expected_kb = kb.knockback(target.damage, hit.damage, ROOK.weight, 8, 30)
    assert hit.knockback == pytest.approx(expected_kb)
    hitlag = kb.hitlag_frames(hit.damage)
    assert attacker.hitlag == target.hitlag == hit.hitlag == hitlag == 7

    # Both are frozen for the hitlag; then the target is launched into hitstun.
    run(match, neutral(hitlag - 1))
    assert attacker.state_frame == 3 and target.state is StateId.IDLE
    run(match, neutral(1))
    assert attacker.hitlag == target.hitlag == 0
    assert target.state is StateId.FLINCH
    assert target.hitstun == kb.hitstun_frames(expected_kb) == 5
    assert attacker.state_frame == 3, "the attacker resumes on the next tick"
    run(match, neutral(1))
    assert attacker.state_frame == 4
    assert run_until(match, target, StateId.IDLE) == 4


def test_a_move_out_of_range_whiffs_and_does_not_stale() -> None:
    match, attacker, target = duel(gap=3.0)
    assert not run_collect(match, ATTACK + neutral(30))
    assert target.damage == 0 and attacker.stale_queue == []
    assert attacker.state is StateId.IDLE


def test_a_move_ends_after_its_last_frame_and_cannot_be_interrupted_before() -> None:
    match, attacker, _ = duel(gap=3.0)
    total = ROOK.moves["ftilt"].total
    run(match, hold(Dir8.SE, Button.ATTACK, frames=1))
    assert (attacker.state, attacker.move_id, attacker.state_frame) == (StateId.ATTACK, "ftilt", 1)
    run(match, hold(Dir8.SE, frames=total - 1))
    assert attacker.state is StateId.ATTACK and attacker.state_frame == total
    assert attacker.pos.x == ORIGIN_X, "holding a direction does not move an attacking fighter"
    run(match, hold(Dir8.SE, frames=1))
    assert attacker.state is StateId.DASH, "held input acts on the first actionable frame"


def test_hits_do_not_connect_twice_with_the_same_move() -> None:
    match, _, target = duel()
    seen = hit_events(run_collect(match, STRONG + neutral(60)))
    assert len(seen) == 1, "three active frames, one hit"
    assert target.damage == pytest.approx(16 * FRESH)


def test_the_lowest_hitbox_id_wins() -> None:
    # At 0.9 units both of the forward smash's hitboxes overlap the target: the sweet spot
    # (id 0, 16%) wins. Point blank only the inner one (id 1, 13%) reaches.
    match, _, target = duel(gap=0.9)
    run(match, STRONG + neutral(20))
    assert target.damage == pytest.approx(16 * FRESH)

    match, attacker, target = duel(gap=5.0)
    run(match, STRONG + neutral(11))
    place(match, target, attacker.pos.x + 0.1, ORIGIN_Y)  # too close for the sweet spot
    run(match, neutral(8))
    assert target.damage == pytest.approx(13 * FRESH)


def test_an_invincible_target_takes_nothing_but_the_attacker_still_feels_the_hit() -> None:
    match, attacker, target = duel()
    target.invincible_frames = 60
    [(_, hit)] = hit_events(run_collect(match, ATTACK + neutral(2)))
    assert (hit.damage, hit.knockback) == (0.0, 0.0)
    assert target.damage == 0 and target.launch is None
    assert attacker.hitlag > 0
    run(match, neutral(10))
    assert target.state is StateId.IDLE


# --- move selection -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("buttons", "direction", "vertical", "move_id", "facing"),
    [
        (Button.ATTACK, None, 0, "jab1", Dir8.SE),
        (Button.ATTACK, Dir8.SE, 0, "ftilt", Dir8.SE),
        (Button.ATTACK, Dir8.NW, 0, "ftilt", Dir8.NW),
        (Button.ATTACK, Dir8.N, 0, "ftilt", Dir8.N),
        (Button.ATTACK, None, VERTICAL_UP, "utilt", Dir8.SE),
        (Button.ATTACK, None, VERTICAL_DOWN, "dtilt", Dir8.SE),
        (Button.ATTACK, Dir8.NW, VERTICAL_UP, "utilt", Dir8.SE),
        (Button.STRONG, None, 0, "fsmash", Dir8.SE),
        (Button.STRONG, Dir8.SW, 0, "fsmash", Dir8.SW),
        (Button.STRONG, None, VERTICAL_UP, "usmash", Dir8.SE),
        (Button.STRONG, None, VERTICAL_DOWN, "dsmash", Dir8.SE),
    ],
)
def test_ground_move_selection(
    buttons: int, direction: Dir8 | None, vertical: int, move_id: str, facing: Dir8
) -> None:
    match, attacker, _ = duel(gap=5.0)
    run(match, hold(direction, buttons, frames=1, vertical=vertical))
    assert (attacker.state, attacker.move_id) == (StateId.ATTACK, move_id)
    assert attacker.facing is facing


@pytest.mark.parametrize(
    ("buttons", "direction", "vertical", "move_id"),
    [
        (Button.ATTACK, None, 0, "nair"),
        (Button.ATTACK, Dir8.SE, 0, "fair"),
        (Button.ATTACK, Dir8.E, 0, "fair"),
        (Button.ATTACK, Dir8.NE, 0, "fair"),
        (Button.ATTACK, Dir8.NW, 0, "bair"),
        (Button.ATTACK, Dir8.W, 0, "bair"),
        (Button.ATTACK, Dir8.SE, VERTICAL_UP, "uair"),
        (Button.ATTACK, None, VERTICAL_DOWN, "dair"),
        (Button.STRONG, None, 0, "nair"),
        (Button.STRONG, Dir8.NW, 0, "bair"),
    ],
)
def test_air_move_selection(
    buttons: int, direction: Dir8 | None, vertical: int, move_id: str
) -> None:
    match, attacker, _ = duel(gap=5.0)
    place(match, attacker, ORIGIN_X, ORIGIN_Y, z=4.0, facing=Dir8.SE)
    run(match, hold(direction, buttons, frames=1, vertical=vertical))
    assert (attacker.state, attacker.move_id) == (StateId.ATTACK, move_id)
    assert attacker.facing is Dir8.SE, "facing never changes in the air"
    assert not attacker.fast_falling, "the down modifier picked the move, not a fast fall"


def test_attack_while_running_is_the_dash_attack_and_it_slides_forward() -> None:
    match, attacker, target = duel(gap=1.0)
    place(match, target, 2.0, 2.0)
    run(match, hold(Dir8.SE, frames=20))
    assert attacker.state is StateId.RUN
    start = attacker.pos.x
    run(match, hold(Dir8.SE, Button.ATTACK, frames=1))
    assert (attacker.state, attacker.move_id) == (StateId.ATTACK, "dash_attack")
    run(match, neutral(11))
    assert attacker.pos.x == pytest.approx(start + 12 * 0.09), "scripted velocity, frames 1-12"
    run(match, neutral(12))
    assert attacker.pos.x == pytest.approx(start + 12 * 0.09 + 12 * 0.03)
    run(match, neutral(14))
    assert attacker.state is StateId.ATTACK and attacker.vel.xy == Vec2()
    run(match, neutral(1))
    assert attacker.state is StateId.IDLE


def test_right_stick_flick_is_a_forward_smash_toward_the_stick() -> None:
    match, attacker, _ = duel(gap=5.0)
    run(match, [InputFrame(cstick=Dir8.NW.world)])
    assert (attacker.state, attacker.move_id, attacker.facing) == (
        StateId.ATTACK,
        "fsmash",
        Dir8.NW,
    )


def test_right_stick_in_the_air_picks_the_aerial_by_direction() -> None:
    match, attacker, _ = duel(gap=5.0)
    place(match, attacker, ORIGIN_X, ORIGIN_Y, z=4.0, facing=Dir8.SE)
    run(match, [InputFrame(cstick=Dir8.NW.world)])
    assert attacker.move_id == "bair"


def test_down_tilt_on_a_soft_platform_does_not_drop_through() -> None:
    match = make_match("sky_ruins", stocks=None)
    attacker = match.fighters[0]
    platform = match.stage.soft_platforms[0]
    place(match, attacker, (platform.x0 + platform.x1) / 2, (platform.y0 + platform.y1) / 2)
    assert attacker.platform == 0
    run(match, hold(buttons=Button.ATTACK, frames=1, vertical=VERTICAL_DOWN))
    run(match, hold(frames=3, vertical=VERTICAL_DOWN))
    assert (attacker.state, attacker.move_id) == (StateId.ATTACK, "dtilt")
    assert attacker.grounded


# --- jab chain ----------------------------------------------------------------------------


def test_pressing_attack_again_chains_the_three_jabs() -> None:
    match, attacker, target = duel()
    moves: list[str] = []
    for _ in range(3):
        run(match, ATTACK)
        moves.append(attacker.move_id)
        run(match, neutral(14))
    assert moves == ["jab1", "jab2", "jab3"]
    assert target.damage == pytest.approx((2.5 + 2.5 + 5.0) * FRESH)
    assert attacker.stale_queue == ["jab3", "jab2", "jab1"]


def test_without_a_second_press_the_jab_just_ends() -> None:
    match, attacker, _ = duel()
    run(match, ATTACK + neutral(40))
    assert attacker.state is StateId.IDLE and attacker.move_id == "jab1"


def test_a_jab_press_before_the_cancel_window_is_buffered_into_it() -> None:
    match, attacker, _ = duel(gap=5.0)
    run(match, ATTACK + neutral(2) + ATTACK + neutral(1))
    assert attacker.move_id == "jab1", "frame 5: the window opens on frame 6"
    run(match, neutral(1))
    assert (attacker.move_id, attacker.state_frame) == ("jab2", 1)


# --- smash charge -------------------------------------------------------------------------


def test_an_uncharged_smash_hits_on_its_normal_frame() -> None:
    match, attacker, _ = duel()
    [(tick, _)] = hit_events(run_collect(match, STRONG + neutral(20)))
    assert tick == 14 and attacker.charge_frames == 0


@pytest.mark.parametrize("held", [10, 30, 60, 90])
def test_holding_strong_charges_the_smash(held: int) -> None:
    match, attacker, target = duel()
    charge = ROOK.moves["fsmash"].charge
    assert charge is not None
    [(tick, hit)] = hit_events(
        run_collect(match, hold(buttons=Button.STRONG, frames=held) + neutral(80))
    )
    # Frames 1 to charge.frame play, the move then waits there while strong is held.
    charged = min(held - charge.frame, charge.max_frames)
    assert attacker.charge_frames == charged
    assert tick == 14 + charged
    multiplier = 1 + (charge.damage_mult - 1) * charged / charge.max_frames
    assert hit.damage == pytest.approx(16 * multiplier * FRESH)
    assert target.damage == pytest.approx(hit.damage)
    full = charged == charge.max_frames
    assert hit.hitlag == kb.hitlag_frames(hit.damage, full_charge=full)


# --- trades and clanks --------------------------------------------------------------------


def test_two_attacks_that_hit_on_the_same_frame_trade() -> None:
    match, first, second = duel(gap=1.6)
    seen = run_collect(
        match,
        hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(20),
        hold(Dir8.NW, Button.ATTACK, frames=1) + neutral(20),
    )
    hits = hit_events(seen)
    assert [(tick, hit.attacker) for tick, hit in hits] == [(7, 0), (7, 1)]
    assert first.damage == second.damage == pytest.approx(9 * FRESH)
    assert first.state is second.state is StateId.FLINCH
    assert first.pos.x < ORIGIN_X and second.pos.x > ORIGIN_X + 1.6, "both were knocked back"
    assert (first.pos.x - ORIGIN_X) == pytest.approx(-(second.pos.x - ORIGIN_X - 1.6))


def test_equal_attacks_that_only_touch_each_other_clank_and_both_rebound() -> None:
    match, first, second = duel(gap=2.6)
    seen = run_collect(
        match,
        hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(6),
        hold(Dir8.NW, Button.ATTACK, frames=1) + neutral(6),
    )
    assert [(tick, type(event), event.player) for tick, event in seen] == [  # type: ignore[attr-defined]
        (7, ClankEvent, 0),
        (7, ClankEvent, 1),
    ]
    assert first.damage == second.damage == 0
    assert first.state is second.state is StateId.REBOUND
    assert first.stale_queue == [], "a clank is not a hit"
    run(match, neutral(c.REBOUND_FRAMES - 1))
    assert first.state is StateId.REBOUND
    run(match, neutral(1))
    assert first.state is second.state is StateId.IDLE


def test_a_much_stronger_attack_beats_a_weak_one_in_a_clank() -> None:
    match, first, second = duel(gap=2.6)
    # P1's forward smash is active on frame 14; P2's jab on its frame 3.
    seen = run_collect(match, STRONG + neutral(40), neutral(11) + ATTACK + neutral(1))
    clanks = [(tick, event.player) for tick, event in seen if isinstance(event, ClankEvent)]
    assert clanks == [(14, 1)], "only the jab is stopped"
    assert second.state is not StateId.ATTACK
    assert first.state is StateId.ATTACK and first.move_id == "fsmash"
    assert first.damage == second.damage == 0


def test_aerials_do_not_clank() -> None:
    match, first, second = duel(gap=1.2)
    place(match, first, ORIGIN_X, ORIGIN_Y, z=1.0, facing=Dir8.SE)
    place(match, second, ORIGIN_X + 1.2, ORIGIN_Y, z=1.0, facing=Dir8.NW)
    seen = run_collect(match, ATTACK + neutral(6), ATTACK + neutral(6))
    assert not [event for _, event in seen if isinstance(event, ClankEvent)]
    assert len(hit_events(seen)) == 2, "the two neutral airs trade instead"


# --- groups and rehit ---------------------------------------------------------------------


def test_a_lingering_hitbox_in_the_same_group_hits_only_once() -> None:
    match, attacker, target = duel(gap=0.8)
    place(match, attacker, ORIGIN_X, ORIGIN_Y, z=0.6, facing=Dir8.SE)
    seen = hit_events(run_collect(match, ATTACK + neutral(12)))
    assert len(seen) == 1 and seen[0][1].move_id == "nair"
    assert target.damage == pytest.approx(8 * FRESH), "the strong early hit, not the late one"


def test_a_new_group_can_hit_the_same_target_again() -> None:
    # Down smash sweeps in front (group 0) and then behind (group 1). A target standing on
    # top of the attacker is in reach of both.
    match, attacker, target = duel(gap=0.5, damage=0)
    target.invincible_frames = 0
    seen = hit_events(
        run_collect(match, hold(buttons=Button.STRONG, frames=1, vertical=-1) + neutral(50))
    )
    front = [hit for _, hit in seen if hit.damage == pytest.approx(12 * FRESH)]
    assert len(front) == 1 and seen[0][0] == 9
    assert attacker.stale_queue == ["dsmash"], "one move, one stale entry, however many hits"


def test_rehit_lets_one_hitbox_hit_repeatedly() -> None:
    nair = ROOK.moves["nair"]
    box = dataclasses.replace(nair.windows[1].hitboxes[0], rehit=5, fkb=20, angle=90.0, damage=1.0)
    window = dataclasses.replace(nair.windows[1], hitboxes=(box,))
    drill = dataclasses.replace(nair, windows=(window,))
    character = with_move(drill)
    match = Match.create(
        load_stage("training_grid"), [character, ROOK], rules=MatchRules(stocks=None)
    )
    attacker, target = match.fighters
    place(match, attacker, ORIGIN_X, ORIGIN_Y, facing=Dir8.SE)
    place(match, target, ORIGIN_X + 0.6, ORIGIN_Y)
    start_move(match, attacker, "nair")
    seen = hit_events(run_collect(match, neutral(80)))
    assert len(seen) >= 2
    assert target.damage == pytest.approx(len(seen) * FRESH)
    assert attacker.stale_queue == ["nair"]
    assert seen[1][1].damage == seen[0][1].damage, "staling applies between uses, not hits"


# --- staling ------------------------------------------------------------------------------


def test_repeating_a_move_makes_it_weaker() -> None:
    match, attacker, target = duel()
    damages = []
    for _ in range(3):
        place(match, target, ORIGIN_X + 1.0, ORIGIN_Y, facing=Dir8.NW, damage=0.0)
        target.hitstun = 0
        [(_, hit)] = hit_events(run_collect(match, ATTACK + neutral(40)))
        damages.append(hit.damage)
    assert damages == pytest.approx([2.5 * 1.05, 2.5 * (1 - 0.09), 2.5 * (1 - 0.09 - 0.08)])
    assert attacker.stale_queue == ["jab1"] * 3


def test_whiffing_does_not_refresh_or_stale() -> None:
    match, attacker, target = duel()
    run(match, ATTACK + neutral(40))
    place(match, target, ORIGIN_X + 5.0, ORIGIN_Y)
    run(match, hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(40))
    assert attacker.stale_queue == ["jab1"]


# --- aerials and landing ------------------------------------------------------------------


def air_time_until_land(match: Match, fighter: Fighter) -> int:
    return run_until(match, fighter, StateId.LAND, limit=120)


def test_landing_during_an_aerial_gives_its_landing_lag() -> None:
    match, attacker, _ = duel(gap=6.0)
    # Short hop, forward air straight away: it lands long before the autocancel window.
    run(match, hold(buttons=Button.JUMP, frames=2) + neutral(3))
    assert attacker.state is StateId.JUMP
    run(match, hold(Dir8.SE, Button.ATTACK, frames=1))
    assert attacker.move_id == "fair"
    air_time_until_land(match, attacker)
    lag = ROOK.moves["fair"].landing_lag
    assert attacker.land_lag == lag == 12
    run(match, neutral(lag - 1))
    assert attacker.state is StateId.LAND
    run(match, neutral(1))
    assert attacker.state is StateId.IDLE


def test_landing_in_the_autocancel_window_gives_normal_landing_lag() -> None:
    match, attacker, _ = duel(gap=6.0)
    # Full hop, neutral air on the way up: by landing the move is past frame 32.
    run(match, hold(buttons=Button.JUMP, frames=8))
    assert attacker.state is StateId.JUMP
    run(match, ATTACK)
    assert attacker.move_id == "nair"
    air_time_until_land(match, attacker)
    assert attacker.land_lag == ROOK.movement.land_lag == 3


def test_an_aerial_that_finishes_in_the_air_returns_to_fall() -> None:
    match, attacker, _ = duel(gap=6.0)
    place(match, attacker, ORIGIN_X, ORIGIN_Y, z=9.0)
    run(match, ATTACK)
    total = ROOK.moves["nair"].total
    run(match, neutral(total - 1))
    assert attacker.state is StateId.ATTACK
    run(match, neutral(1))
    assert attacker.state is StateId.FALL


def test_back_air_launches_behind_the_attacker() -> None:
    match, attacker, target = duel(gap=1.0)
    place(match, attacker, ORIGIN_X + 2.0, ORIGIN_Y, z=0.5, facing=Dir8.SE)
    place(match, target, ORIGIN_X + 1.0, ORIGIN_Y, damage=60.0)
    run(match, hold(Dir8.NW, Button.ATTACK, frames=1) + neutral(40))
    assert target.damage > 60
    assert target.pos.x < ORIGIN_X + 1.0, "sent toward -x, behind the attacker"


def test_down_air_spikes_an_airborne_target_and_pops_up_a_grounded_one() -> None:
    def dair_on(target_z: float | None) -> tuple[Fighter, HitEvent]:
        match, attacker, target = duel(gap=0.2)
        height = (target_z or 0.0) + 2.4
        place(match, attacker, ORIGIN_X, ORIGIN_Y, z=height, facing=Dir8.SE)
        place(match, target, ORIGIN_X + 0.2, ORIGIN_Y, z=target_z, damage=50.0)
        attacker.vel = attacker.vel  # hangs for a moment, then falls onto the target
        start_move(match, attacker, "dair")
        attacker.state_frame = 12
        seen = hit_events(run_collect(match, neutral(8)))
        assert seen, "the down air connected"
        run(match, neutral(seen[0][1].hitlag + 3))
        return target, seen[0][1]

    grounded, hit = dair_on(None)
    assert grounded.kb_vel.z >= 0 and grounded.pos.z >= 0
    assert hit.knockback >= c.METEOR_BOUNCE_KB and grounded.state is StateId.TUMBLE

    airborne, _ = dair_on(5.0)
    assert airborne.kb_vel.z < 0, "meteor: straight down"
    assert airborne.state is StateId.TUMBLE


# --- hitstun, tumble, knockdown -----------------------------------------------------------


def test_a_weak_sakurai_hit_keeps_a_grounded_target_on_the_ground() -> None:
    match, attacker, target = duel(damage=0)
    start_move(match, attacker, "jab3")
    [(_, hit)] = hit_events(run_collect(match, neutral(8)))
    assert hit.knockback < c.SAKURAI_KB_LOW
    run(match, neutral(hit.hitlag + 5))
    assert target.state is StateId.FLINCH and target.grounded
    assert target.pos.x > ORIGIN_X + 1.0 and target.pos.z == 0
    assert target.kb_vel.z == 0


def test_a_strong_hit_tumbles_then_knocks_down_then_gets_up() -> None:
    match, _, target = duel(damage=40.0)
    [(_, hit)] = hit_events(run_collect(match, STRONG + neutral(13)))
    assert kb.is_tumble(hit.knockback)
    run(match, neutral(hit.hitlag))
    assert target.state is StateId.TUMBLE and not target.grounded
    assert target.hitstun == kb.hitstun_frames(hit.knockback)
    speed = target.kb_vel.length()
    assert speed == pytest.approx(kb.launch_speed(hit.knockback))
    assert math.degrees(math.asin(target.kb_vel.z / speed)) == pytest.approx(38)

    run_until(match, target, StateId.KNOCKDOWN, limit=200)
    assert target.grounded and target.hitstun == 0
    assert target.pos.x > ORIGIN_X + 3
    run(match, neutral(c.KNOCKDOWN_MAX_FRAMES - 1))
    assert target.state is StateId.KNOCKDOWN, "lies there without input"
    run(match, neutral(1))
    assert target.state is StateId.GETUP
    run(match, neutral(c.GETUP_FRAMES))
    assert target.state is StateId.IDLE


def test_any_input_gets_up_from_a_knockdown_after_the_lock() -> None:
    match, _, target = duel(damage=40.0)
    run(match, STRONG + neutral(40))
    run_until(match, target, StateId.KNOCKDOWN, limit=200)
    mash = hold(buttons=Button.ATTACK, frames=1)
    for _ in range(c.KNOCKDOWN_LOCK_FRAMES - 1):
        run(match, neutral(1), mash)
    assert target.state is StateId.KNOCKDOWN and target.state_frame == c.KNOCKDOWN_LOCK_FRAMES
    run(match, neutral(1), mash)
    assert target.state is StateId.GETUP


def test_hitstun_cannot_be_acted_out_of_but_tumble_after_hitstun_can() -> None:
    match, _, target = duel(damage=80.0, stage="sky_ruins")
    place(match, target, ORIGIN_X + 1.0, ORIGIN_Y, z=6.0, damage=80.0)
    place(match, match.fighters[0], ORIGIN_X, ORIGIN_Y, z=5.2)
    start_move(match, match.fighters[0], "nair")
    jump = hold(buttons=Button.JUMP, frames=1)
    seen = hit_events(run_collect(match, neutral(8)))
    assert seen
    run(match, neutral(seen[0][1].hitlag))
    assert target.state is StateId.TUMBLE
    stun = target.hitstun
    for _ in range(stun // 2):
        run(match, neutral(1), jump)
        run(match, neutral(1))
    assert target.state is StateId.TUMBLE, "mashing jump during hitstun does nothing"
    for _ in range(4):
        run(match, neutral(1), jump)
        run(match, neutral(1))
    assert target.state is StateId.DOUBLE_JUMP


def test_launched_fighters_fall_more_slowly_while_stunned() -> None:
    match, _, target = duel(damage=120.0)
    run(match, STRONG + neutral(40))
    assert target.state is StateId.TUMBLE and target.hitstun > 0
    assert target.vel.z >= -ROOK.movement.max_fall * c.HITSTUN_GRAVITY_MULT - 1e-9
    assert target.vel.z < 0


def test_a_ko_clears_the_hit_state() -> None:
    match, attacker, target = duel(stage="sky_ruins")
    place(match, attacker, 5.6, 4.5, z=match.stage.surface_top(5.6, 4.5))
    place(match, target, 6.5, 4.5, z=match.stage.surface_top(6.5, 4.5), damage=250.0)
    seen = run_collect(match, STRONG + neutral(200))
    assert any(isinstance(event, KoEvent) and event.player == 1 for _, event in seen)
    assert target.hitstun == 0 and target.hitlag == 0 and target.launch is None
    assert target.kb_vel.length() == 0


# --- SDI and DI ---------------------------------------------------------------------------


def launch_with(p2_during_hitlag: list[InputFrame]) -> tuple[Match, Fighter, HitEvent]:
    match, _, target = duel(damage=60.0)
    [(_, hit)] = hit_events(run_collect(match, STRONG + neutral(13)))
    run(match, neutral(hit.hitlag), p2_during_hitlag)
    return match, target, hit


def test_sdi_nudges_the_target_once_per_new_stick_input() -> None:
    _, still, hit = launch_with(neutral(1))
    flick = hold(Dir8.NE, frames=1) + neutral(1)
    # Two separate flicks toward +y... (NE on screen is -y in the world; see Dir8.world).
    _, nudged, _ = launch_with(neutral(2) + flick + flick + neutral(hit.hitlag))
    offset = Vec2(nudged.pos.x - still.pos.x, nudged.pos.y - still.pos.y)
    expected = Dir8.NE.world * (2 * c.SDI_DISTANCE)
    assert (offset.x, offset.y) == pytest.approx((expected.x, expected.y), abs=1e-9)

    _, held, _ = launch_with(neutral(2) + hold(Dir8.NE, frames=4) + neutral(hit.hitlag))
    offset = Vec2(held.pos.x - still.pos.x, held.pos.y - still.pos.y)
    assert offset.length() == pytest.approx(c.SDI_DISTANCE), "holding counts once"


def test_di_bends_the_launch_by_up_to_fifteen_degrees() -> None:
    _, plain, hit = launch_with(neutral(1))
    assert (plain.kb_vel.x > 0, plain.kb_vel.y) == (True, pytest.approx(0))
    # Launched along +x: holding +y (perpendicular) on the last hitlag frame bends it.
    perpendicular = Dir8.SW  # world +y
    assert (perpendicular.world.x, perpendicular.world.y) == pytest.approx((0, 1))
    _, bent, _ = launch_with(neutral(hit.hitlag - 1) + hold(perpendicular, frames=1))
    angle = math.degrees(math.atan2(bent.kb_vel.y, bent.kb_vel.x))
    assert angle == pytest.approx(c.DI_MAX_DEGREES)
    assert bent.kb_vel.length() == pytest.approx(plain.kb_vel.length()), "DI never adds speed"
    assert bent.kb_vel.z == pytest.approx(plain.kb_vel.z)

    _, parallel, _ = launch_with(neutral(hit.hitlag - 1) + hold(Dir8.SE, frames=1))
    assert parallel.kb_vel.y == pytest.approx(0)


def test_vertical_di_changes_the_elevation() -> None:
    _, plain, hit = launch_with(neutral(1))
    _, raised, _ = launch_with(neutral(hit.hitlag - 1) + hold(frames=1, vertical=VERTICAL_UP))
    _, lowered, _ = launch_with(neutral(hit.hitlag - 1) + hold(frames=1, vertical=VERTICAL_DOWN))

    def elevation(fighter: Fighter) -> float:
        return math.degrees(math.asin(fighter.kb_vel.z / fighter.kb_vel.length()))

    assert elevation(plain) == pytest.approx(38)
    assert elevation(raised) == pytest.approx(38 + c.DI_MAX_DEGREES)
    assert elevation(lowered) == pytest.approx(38 - c.DI_MAX_DEGREES)
    assert not lowered.fast_falling, "down held for DI is not a fast fall"


# --- knockback motion ---------------------------------------------------------------------


def test_knockback_velocity_decays_to_zero() -> None:
    match, _, target = duel(damage=30.0)
    [(_, hit)] = hit_events(run_collect(match, STRONG + neutral(13)))
    run(match, neutral(hit.hitlag))
    speed = target.kb_vel.length()
    run(match, neutral(1))
    assert target.kb_vel.length() == pytest.approx(speed - c.KB_DECAY)
    run(match, neutral(300))
    assert target.kb_vel.length() == 0 and target.state is StateId.IDLE


# --- KO percents --------------------------------------------------------------------------


def test_forward_smash_kills_rook_at_about_130_from_the_centre_of_sky_ruins() -> None:
    stage = load_stage("sky_ruins")
    percent = kill_percent(stage, ROOK, ROOK, "fsmash")
    assert percent is not None and 120 <= percent <= 140, percent
    assert not move_kills(stage, ROOK, ROOK, "fsmash", 80)
    assert move_kills(stage, ROOK, ROOK, "fsmash", 200)


def test_up_smash_can_kill_off_the_top_and_weak_moves_never_kill() -> None:
    stage = load_stage("sky_ruins")
    up = kill_percent(stage, ROOK, ROOK, "usmash")
    assert up is not None and 140 <= up <= 200, up
    assert kill_percent(stage, ROOK, ROOK, "jab1") is None
