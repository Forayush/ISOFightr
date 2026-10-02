"""Scenario tests for shields, dodges, grabs and throws.

Plan note "06 - Shield Dodge Grab and Ledge" ("Shield", "Dodges", "Grabs and throws").
"""

import math

import pytest

from helpers import hold, make_match, make_stage, neutral, place, run, run_until
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.combat.grab import hold_frames
from isofightr.sim.combat.shield import (
    dizzy_frames,
    shield_damage,
    shield_radius,
    shieldstun_frames,
)
from isofightr.sim.events import (
    GrabEvent,
    HitEvent,
    ShieldBreakEvent,
    ShieldHitEvent,
)
from isofightr.sim.fighter import NO_PARTNER, Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.states.interrupts import start_move

ROOK = load_character("rook")
FRESH = c.FRESH_BONUS
X, Y = 4.0, 6.0

SHIELD = hold(buttons=Button.SHIELD, frames=1)
GRAB = hold(buttons=Button.GRAB, frames=1)
ATTACK = hold(buttons=Button.ATTACK, frames=1)


def duel(
    gap: float = 1.0, damage: float = 0.0, rules: MatchRules | None = None
) -> tuple[Match, Fighter, Fighter]:
    """P1 faces P2 along +x, ``gap`` apart, on open ground. Returns ``(match, p1, p2)``."""
    stage = load_stage("training_grid")
    match = Match.create(stage, [ROOK, ROOK], seed=1, rules=rules or MatchRules(stocks=None))
    first, second = match.fighters
    place(match, first, X, Y, facing=Dir8.SE)
    place(match, second, X + gap, Y, facing=Dir8.NW, damage=damage)
    return match, first, second


def events_of(match: Match, kind: type) -> list:  # type: ignore[type-arg]
    return [event for event in match.events if isinstance(event, kind)]


def run_events(match: Match, p1: list[InputFrame], p2: list[InputFrame] | None, kind: type) -> list:  # type: ignore[type-arg]
    """Run tick by tick and collect ``(tick, event)`` of one event type."""
    seen = []
    for index, frame in enumerate(p1):
        run(match, [frame], None if p2 is None or index >= len(p2) else [p2[index]])
        seen.extend((index + 1, event) for event in events_of(match, kind))
    return seen


def shielding(frames: int) -> list[InputFrame]:
    return hold(buttons=Button.SHIELD, frames=frames)


# --- shield -------------------------------------------------------------------------------


def test_holding_shield_raises_it_and_it_drains() -> None:
    match, fighter, _ = duel(gap=5.0)
    run(match, shielding(1))
    assert fighter.state is StateId.SHIELD and fighter.shield_hp == c.SHIELD_MAX_HP
    run(match, shielding(10))
    assert fighter.shield_hp == pytest.approx(c.SHIELD_MAX_HP - 10 * c.SHIELD_DECAY)
    assert shield_radius(fighter) < ROOK.body.shield_radius_max


def test_releasing_shield_costs_eleven_frames_and_then_it_regenerates() -> None:
    match, fighter, _ = duel(gap=5.0)
    run(match, shielding(20) + neutral(1))
    assert fighter.state is StateId.SHIELD_DROP
    run(match, neutral(c.SHIELD_DROP_FRAMES - 1))
    assert fighter.state is StateId.SHIELD_DROP
    run(match, neutral(1))
    assert fighter.state is StateId.IDLE
    low = fighter.shield_hp
    run(match, neutral(10))
    assert fighter.shield_hp == pytest.approx(low + 10 * c.SHIELD_REGEN)
    run(match, neutral(2000))
    assert fighter.shield_hp == c.SHIELD_MAX_HP


def test_a_tapped_shield_stays_up_for_its_minimum() -> None:
    match, fighter, _ = duel(gap=5.0)
    run(match, shielding(1) + neutral(c.SHIELD_MIN_FRAMES - 2))
    assert fighter.state is StateId.SHIELD
    run(match, neutral(2))
    assert fighter.state is StateId.SHIELD_DROP


def test_a_shield_blocks_a_hit() -> None:
    match, attacker, defender = duel()
    seen = run_events(
        match, hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(8), shielding(30), ShieldHitEvent
    )
    [(tick, event)] = seen
    damage = 9 * FRESH
    assert tick == 7 and not event.parried
    assert defender.damage == 0 and defender.launch is None
    assert not [e for e in match.events if isinstance(e, HitEvent)]
    assert event.damage == pytest.approx(shield_damage(damage))
    drained = 6 * c.SHIELD_DECAY  # shield up since tick 1; the hit lands on tick 7
    assert defender.shield_hp == pytest.approx(c.SHIELD_MAX_HP - drained - shield_damage(damage))
    assert attacker.hitlag == defender.hitlag == kb.hitlag_frames(damage) - 2
    assert defender.state is StateId.SHIELD_STUN
    assert attacker.stale_queue == [], "a blocked move does not stale"


def test_shieldstun_and_pushback() -> None:
    match, attacker, defender = duel()
    run(match, hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(6), shielding(7))
    damage = 9 * FRESH
    stun = shieldstun_frames(damage)
    assert stun == math.floor(damage * 0.8 * 0.725 + 2) == 7
    hitlag = kb.hitlag_frames(damage)
    jump = hold(buttons=Button.SHIELD | Button.JUMP, frames=1)
    # Frozen for the hitlag, then stunned: jumping out of shield does nothing yet.
    run(match, neutral(hitlag + stun - 1), [*jump, *shielding(1)] * 20)
    assert defender.state is StateId.SHIELD_STUN
    assert defender.pos.x > X + 1.0, "pushed away from the attacker"
    assert attacker.pos.x < X, "the attacker slides back a little too"
    run(match, neutral(1), shielding(1))
    assert defender.state is StateId.SHIELD
    run(match, neutral(1), jump)
    assert defender.state is StateId.JUMP_SQUAT


def test_a_small_shield_can_be_poked() -> None:
    # Down tilt reaches the legs. At 1.6 units it misses a nearly spent shield's small
    # bubble but touches the hurtbox; a full shield covers the legs.
    for hp, blocked in ((c.SHIELD_MAX_HP, True), (3.0, False)):
        match, attacker, defender = duel(gap=1.6)
        defender.shield_hp = hp
        run(
            match,
            hold(buttons=Button.ATTACK, frames=1, vertical=VERTICAL_DOWN) + neutral(7),
            shielding(8),
        )
        assert attacker.move_id == "dtilt"
        assert (defender.damage == 0) is blocked, hp


def test_a_shield_breaks_and_the_fighter_lands_dizzy() -> None:
    match, _, defender = duel()
    defender.shield_hp = 8.0
    defender.damage = 40.0
    seen = run_events(
        match, hold(buttons=Button.STRONG, frames=1) + neutral(40), shielding(60), ShieldBreakEvent
    )
    assert len(seen) == 1 and seen[0][1].player == 1
    assert defender.state is StateId.SHIELD_BREAK and not defender.grounded
    assert defender.shield_hp == pytest.approx(c.SHIELD_BREAK_HP) and defender.damage == 40.0
    run_until(match, defender, StateId.DIZZY, limit=200)
    assert defender.stun_frames == dizzy_frames(40.0) == 360
    run(match, neutral(359), hold(Dir8.SE, Button.JUMP, frames=359))
    assert defender.state is StateId.DIZZY, "no escape"
    run(match, neutral(1))
    assert defender.state is StateId.IDLE


def test_dizzy_is_shorter_at_high_damage() -> None:
    assert dizzy_frames(0) == 400 and dizzy_frames(200) == 200
    assert dizzy_frames(350) == dizzy_frames(999) == c.DIZZY_MIN_FRAMES == 90


def test_holding_shield_too_long_breaks_it() -> None:
    match, fighter, _ = duel(gap=5.0)
    frames = math.ceil(c.SHIELD_MAX_HP / c.SHIELD_DECAY)
    run(match, shielding(frames))
    assert fighter.state is StateId.SHIELD
    run(match, shielding(3))
    assert fighter.state is StateId.SHIELD_BREAK


@pytest.mark.parametrize(
    ("frame", "state", "move_id"),
    [
        (hold(buttons=Button.SHIELD | Button.JUMP, frames=1), StateId.JUMP_SQUAT, None),
        (hold(buttons=Button.SHIELD | Button.GRAB, frames=1), StateId.GRAB, None),
        (hold(buttons=Button.SHIELD | Button.ATTACK, frames=1), StateId.GRAB, None),
        (
            hold(buttons=Button.SHIELD | Button.STRONG, frames=1, vertical=VERTICAL_UP),
            StateId.ATTACK,
            "usmash",
        ),
        (hold(buttons=Button.SHIELD, frames=1, vertical=VERTICAL_DOWN), StateId.SPOT_DODGE, None),
        (hold(Dir8.NE, Button.SHIELD, frames=1), StateId.ROLL, None),
    ],
)
def test_out_of_shield_options(
    frame: list[InputFrame], state: StateId, move_id: str | None
) -> None:
    match, fighter, _ = duel(gap=5.0)
    run(match, shielding(5) + frame)
    assert fighter.state is state
    if move_id is not None:
        assert fighter.move_id == move_id


def test_shield_pushback_never_pushes_off_the_edge() -> None:
    match, attacker, defender = duel()
    place(match, attacker, 10.9, Y, facing=Dir8.SE)
    place(match, defender, 11.9, Y, facing=Dir8.NW)
    run(match, hold(buttons=Button.STRONG, frames=1) + neutral(60), shielding(61))
    # The feet point may hang half a body radius past the edge, as when standing there.
    assert defender.grounded and defender.pos.x <= 12.0 + ROOK.body.radius / 2 + 1e-9
    assert defender.state in (StateId.SHIELD, StateId.SHIELD_STUN)


def test_shield_is_also_available_out_of_a_run() -> None:
    match, fighter, _ = duel(gap=5.0)
    run(match, hold(Dir8.SE, frames=20) + hold(Dir8.SE, Button.SHIELD, frames=1))
    assert fighter.state is StateId.SHIELD


def test_parry_rule() -> None:
    def clash(rules: MatchRules) -> tuple[Match, Fighter, Fighter]:
        match, attacker, defender = duel(rules=rules)
        # The forward tilt lands on tick 7. Shield from tick 1, release so that the drop
        # starts on tick 5: the hit arrives on frame 3 of the drop.
        run(match, hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(6), shielding(3) + neutral(4))
        return match, attacker, defender

    match, attacker, defender = clash(MatchRules(stocks=None))
    assert defender.damage > 0, "without the rule a dropped shield is just hit"

    match, attacker, defender = clash(MatchRules(stocks=None, parry=True))
    [event] = events_of(match, ShieldHitEvent)
    assert event.parried and event.damage == 0
    assert defender.damage == 0 and defender.shield_hp > 49
    assert attacker.hitlag == defender.hitlag + c.PARRY_EXTRA_HITLAG
    run(match, neutral(defender.hitlag + 1), neutral(defender.hitlag) + ATTACK)
    assert defender.state is StateId.ATTACK and attacker.hitlag > 0, "the parrier acts first"


# --- dodges -------------------------------------------------------------------------------


def intangible_frames_of(
    match: Match, fighter: Fighter, state: StateId, limit: int = 80
) -> list[int]:
    """Run until the state ends; return the state frames on which the fighter was intangible."""
    frames = []
    for _ in range(limit):
        if fighter.state is not state:
            break
        if fighter.intangible:
            frames.append(fighter.state_frame)
        run(match, neutral(1))
    return frames


def test_spot_dodge_frames() -> None:
    match, fighter, _ = duel(gap=5.0)
    run(match, shielding(2) + hold(buttons=Button.SHIELD, frames=1, vertical=VERTICAL_DOWN))
    assert fighter.state is StateId.SPOT_DODGE and fighter.state_frame == 1
    first, last = c.SPOT_DODGE_INTANGIBLE
    assert intangible_frames_of(match, fighter, StateId.SPOT_DODGE) == list(range(first, last + 1))
    assert fighter.state is StateId.IDLE and match.frame == 3 + c.SPOT_DODGE_FRAMES
    assert fighter.pos.x == X


def test_a_spot_dodge_avoids_an_attack() -> None:
    match, attacker, defender = duel()
    dodge = shielding(1) + hold(buttons=Button.SHIELD, frames=1, vertical=VERTICAL_DOWN)
    # The forward smash is active on ticks 14 to 16; the dodge is intangible from its frame 3.
    run(match, hold(buttons=Button.STRONG, frames=1) + neutral(30), neutral(9) + dodge)
    assert defender.damage == 0 and attacker.hitlag == 0 and attacker.stale_queue == []


@pytest.mark.parametrize("direction", [Dir8.SE, Dir8.NW, Dir8.N, Dir8.SW, Dir8.E])
def test_roll_goes_any_of_eight_ways_and_keeps_the_facing(direction: Dir8) -> None:
    match, fighter, _ = duel(gap=5.0)
    place(match, fighter, 6.0, 6.0, facing=Dir8.SE)
    run(match, shielding(2) + hold(direction, Button.SHIELD, frames=1))
    assert fighter.state is StateId.ROLL
    first, last = c.ROLL_INTANGIBLE
    assert intangible_frames_of(match, fighter, StateId.ROLL) == list(range(first, last + 1))
    assert match.frame == 3 + c.ROLL_FRAMES
    moved = fighter.pos - type(fighter.pos)(6.0, 6.0, 0.0)
    expected = direction.world * c.ROLL_DISTANCE
    assert (moved.x, moved.y) == pytest.approx((expected.x, expected.y))
    assert fighter.facing is Dir8.SE


def test_a_roll_stops_at_the_edge() -> None:
    match, fighter, _ = duel(gap=5.0)
    place(match, fighter, 11.5, 6.0, facing=Dir8.NW)
    run(match, shielding(2) + hold(Dir8.SE, Button.SHIELD, frames=1) + neutral(40))
    assert fighter.grounded and fighter.state is StateId.IDLE
    assert 11.5 < fighter.pos.x <= 12.0 + ROOK.body.radius


def test_repeated_dodges_get_slower_and_recover() -> None:
    match, fighter, _ = duel(gap=5.0)
    place(match, fighter, 6.0, 6.0)
    lengths = []
    for index in range(8):
        direction = Dir8.SE if index % 2 == 0 else Dir8.NW
        run(match, shielding(2) + hold(direction, Button.SHIELD, frames=1))
        start = match.frame
        run_until(match, fighter, StateId.IDLE, limit=80)
        lengths.append(match.frame - start)
    assert lengths == [c.ROLL_FRAMES + lag for lag in (0, 2, 4, 6, 8, 10, 12, 12)]
    run(match, neutral(c.DODGE_STALE_RESET_FRAMES))
    assert fighter.dodge_stale == 0


def test_landing_a_hit_resets_dodge_staling() -> None:
    match, attacker, _ = duel()
    attacker.dodge_stale = 4
    attacker.dodge_stale_timer = 100
    run(match, ATTACK + neutral(3))
    assert attacker.dodge_stale == 0


def test_neutral_air_dodge() -> None:
    match, fighter, _ = duel(gap=5.0)
    place(match, fighter, X, Y, z=9.0)
    run(match, SHIELD)
    assert fighter.state is StateId.AIR_DODGE
    first, last = c.AIR_DODGE_INTANGIBLE
    assert intangible_frames_of(match, fighter, StateId.AIR_DODGE) == list(range(first, last + 1))
    assert fighter.state is StateId.FALL and fighter.pos.x == X and fighter.pos.z < 9.0
    run(match, SHIELD + neutral(1))
    assert fighter.state is StateId.FALL, "one air dodge per airtime"
    run_until(match, fighter, StateId.IDLE, limit=200)
    assert not fighter.air_dodge_used


def test_landing_during_an_air_dodge_has_its_own_lag() -> None:
    for direction, lag in (
        (None, c.AIR_DODGE_LAND_LAG),
        (Dir8.SE, c.AIR_DODGE_DIRECTIONAL_LAND_LAG),
    ):
        match, fighter, _ = duel(gap=6.0)
        place(match, fighter, X, Y, z=0.4)
        run(match, hold(direction, Button.SHIELD, frames=1))
        run_until(match, fighter, StateId.LAND, limit=60)
        assert fighter.land_lag == lag


@pytest.mark.parametrize(
    ("direction", "vertical"),
    [
        (Dir8.SE, 0),
        (Dir8.NW, 0),
        (None, VERTICAL_UP),
        (Dir8.N, VERTICAL_UP),
        (Dir8.SW, VERTICAL_DOWN),
    ],
)
def test_directional_air_dodge_bursts_in_3d(direction: Dir8 | None, vertical: int) -> None:
    match, fighter, _ = duel(gap=5.0)
    place(match, fighter, 6.0, 6.0, z=7.0)
    start = fighter.pos
    run(match, hold(direction, Button.SHIELD, frames=1, vertical=vertical))
    assert fighter.state is StateId.AIR_DODGE
    aim = fighter.dodge_dir
    assert aim.length() == pytest.approx(1.0)
    run(match, neutral(c.AIR_DODGE_BURST_FRAMES - 1))
    moved = fighter.pos - start
    travelled = sum(
        c.AIR_DODGE_SPEED * (1 - index / c.AIR_DODGE_BURST_FRAMES)
        for index in range(c.AIR_DODGE_BURST_FRAMES)
    )
    assert moved.length() == pytest.approx(travelled)
    assert (moved.normalized() - aim).length() < 1e-6, "a straight line, no gravity yet"
    first, last = c.AIR_DODGE_DIRECTIONAL_INTANGIBLE
    assert fighter.intangible == (first <= fighter.state_frame <= last)


def test_helpless_rule_after_a_directional_air_dodge() -> None:
    match, fighter, _ = duel(gap=5.0, rules=MatchRules(stocks=None, air_dodge_helpless=True))
    place(match, fighter, 6.0, 6.0, z=11.5)  # high up: the dodge must end in the air
    run(match, hold(Dir8.SE, Button.SHIELD, frames=1) + neutral(c.AIR_DODGE_FRAMES))
    assert fighter.state is StateId.HELPLESS
    jump = hold(buttons=Button.JUMP, frames=1)
    run(match, jump + neutral(1) + ATTACK + neutral(1))
    assert fighter.state is StateId.HELPLESS and fighter.air_jumps_left == 1
    run_until(match, fighter, StateId.LAND, limit=300)
    assert fighter.land_lag == c.HELPLESS_LAND_LAG


# --- grabs --------------------------------------------------------------------------------


def grabbed(damage: float = 0.0, gap: float = 1.0) -> tuple[Match, Fighter, Fighter]:
    """Return a match in which P1 has just grabbed P2."""
    match, grabber, victim = duel(gap=gap, damage=damage)
    run(match, GRAB + neutral(5))
    assert grabber.state is StateId.GRAB_HOLD and victim.state is StateId.GRABBED
    return match, grabber, victim


def test_grab_connects_on_its_first_active_frame_and_holds_the_victim_in_front() -> None:
    match, grabber, victim = duel()
    seen = run_events(match, GRAB + neutral(6), None, GrabEvent)
    assert [(tick, event.grabber, event.target, event.clash) for tick, event in seen] == [
        (6, 0, 1, False)
    ]
    assert ROOK.grabs.standing.frames.first == 6
    assert grabber.state is StateId.GRAB_HOLD and victim.state is StateId.GRABBED
    assert (grabber.grab_partner, victim.grab_partner) == (1, 0)
    assert victim.pos.x == pytest.approx(grabber.pos.x + c.GRAB_HOLD_DISTANCE)
    assert victim.damage == 0


def test_a_whiffed_grab_leaves_the_grabber_open() -> None:
    match, grabber, _ = duel(gap=4.0)
    total = ROOK.grabs.standing.total
    run(match, GRAB + hold(Dir8.SE, Button.JUMP, frames=total - 1))
    assert grabber.state is StateId.GRAB and grabber.state_frame == total
    run(match, neutral(1))
    assert grabber.state is not StateId.GRAB


def test_grab_beats_shield() -> None:
    match, grabber, victim = duel()
    run(match, GRAB + neutral(6), shielding(7))
    assert victim.state is StateId.GRABBED and grabber.state is StateId.GRAB_HOLD


@pytest.mark.parametrize("case", ["airborne", "intangible", "invincible", "hanging"])
def test_grabs_miss_what_they_cannot_take(case: str) -> None:
    match, grabber, victim = duel()
    if case == "airborne":
        place(match, victim, X + 1.0, Y, z=0.4)
        victim.vel = type(victim.vel)(0.0, 0.0, 0.2)
    elif case == "intangible":
        victim.intangible_frames = 30
    elif case == "invincible":
        victim.invincible_frames = 30
    else:
        place(match, grabber, 0.9, Y, facing=Dir8.NW)
        place(match, victim, -0.4, Y, z=-1.0)
        run_until(match, victim, StateId.LEDGE_HANG, limit=30)
        victim.intangible_frames = 0
    run(match, GRAB + neutral(8))
    assert grabber.state is StateId.GRAB and victim.state is not StateId.GRABBED


def test_attack_beats_grab() -> None:
    match, grabber, attacker = duel()
    # P2's jab lands on tick 3, well before the grab box comes out on tick 6.
    run(match, GRAB + neutral(8), ATTACK + neutral(8))
    assert grabber.damage > 0 and grabber.state is not StateId.GRAB_HOLD
    assert attacker.state is StateId.ATTACK

    # Same tick: the hit is resolved first, and a grabber that was just hit does not grab.
    match, grabber, attacker = duel()
    run(match, GRAB + neutral(5), neutral(3) + ATTACK + neutral(2))
    assert grabber.launch is not None or grabber.damage > 0
    assert attacker.state is not StateId.GRABBED


def test_simultaneous_grabs_clash() -> None:
    match, first, second = duel()
    seen = run_events(match, GRAB + neutral(5), GRAB + neutral(5), GrabEvent)
    assert len(seen) == 1 and seen[0][1].clash
    assert first.state is second.state is StateId.GRAB_RELEASE
    assert first.grab_partner == second.grab_partner == NO_PARTNER
    run(match, neutral(5))
    assert first.pos.x < X and second.pos.x > X + 1.0, "pushed apart"
    run(match, neutral(c.GRAB_RELEASE_FRAMES))
    assert first.state is second.state is StateId.IDLE


def test_dash_grab_slides_forward_and_reaches_further() -> None:
    match, grabber, victim = duel(gap=4.0)
    place(match, grabber, 1.0, Y, facing=Dir8.SE)
    place(match, victim, 4.2, Y)
    run(match, hold(Dir8.SE, frames=14) + hold(Dir8.SE, Button.GRAB, frames=1))
    assert grabber.state is StateId.DASH_GRAB
    start = grabber.pos.x
    run(match, neutral(12))
    assert grabber.pos.x > start + 0.5
    assert grabber.state is StateId.GRAB_HOLD and victim.state is StateId.GRABBED
    assert ROOK.grabs.dash.total > ROOK.grabs.standing.total


def test_the_hold_runs_out_and_releases_both() -> None:
    match, grabber, victim = grabbed(damage=20.0)
    assert grabber.grab_timer == hold_frames(20.0) == 124
    run(match, neutral(122))
    assert grabber.state is StateId.GRAB_HOLD
    run(match, neutral(2))
    assert grabber.state is victim.state is StateId.GRAB_RELEASE
    assert victim.damage == 20.0
    run(match, neutral(c.GRAB_RELEASE_FRAMES + 1))
    assert grabber.state is victim.state is StateId.IDLE
    assert victim.pos.x - grabber.pos.x > c.GRAB_HOLD_DISTANCE


def test_mashing_breaks_out_sooner() -> None:
    match, grabber, victim = grabbed()
    mash = [*hold(buttons=Button.JUMP, frames=1), *neutral(1)] * 40
    ticks = 0
    while grabber.state is StateId.GRAB_HOLD:
        run(match, neutral(1), [mash[ticks]])
        ticks += 1
    assert ticks < hold_frames(0.0) / 2
    assert victim.state is StateId.GRAB_RELEASE


def test_pummel_damages_with_a_cooldown() -> None:
    match, grabber, victim = grabbed()
    pummel = ROOK.grabs.pummel
    run(match, ATTACK)
    assert victim.damage == pummel.damage and grabber.hitlag == c.PUMMEL_HITLAG
    run(match, neutral(c.PUMMEL_HITLAG) + ATTACK + neutral(1))
    assert victim.damage == pummel.damage, "still cooling down, and the press is too early"
    run(match, neutral(pummel.cooldown) + ATTACK)
    assert victim.damage == 2 * pummel.damage
    assert victim.state is StateId.GRABBED


@pytest.mark.parametrize(
    ("frame", "throw_id", "facing", "heading"),
    [
        (hold(Dir8.SE, frames=1), "fthrow", Dir8.SE, Dir8.SE),
        (hold(Dir8.SW, frames=1), "fthrow", Dir8.SW, Dir8.SW),
        (hold(Dir8.S, frames=1), "fthrow", Dir8.S, Dir8.S),
        (hold(Dir8.NW, frames=1), "bthrow", Dir8.SE, Dir8.NW),
        (hold(Dir8.N, frames=1), "bthrow", Dir8.SE, Dir8.N),
        (hold(frames=1, vertical=VERTICAL_UP), "uthrow", Dir8.SE, Dir8.SE),
        (hold(frames=1, vertical=VERTICAL_DOWN), "dthrow", Dir8.SE, Dir8.SE),
    ],
)
def test_throws_go_where_the_stick_points(
    frame: list[InputFrame], throw_id: str, facing: Dir8, heading: Dir8
) -> None:
    match, grabber, victim = grabbed(damage=50.0)
    throws = {
        t.id: t for t in (ROOK.grabs.forward, ROOK.grabs.back, ROOK.grabs.up, ROOK.grabs.down)
    }
    throw = throws[throw_id]
    hits, peak, launch = [], 0.0, None
    for tick, tick_input in enumerate(frame + neutral(40), start=1):
        run(match, [tick_input])
        hits.extend((tick, event) for event in events_of(match, HitEvent))
        launch = launch or victim.launch
        peak = max(peak, victim.pos.z)
    [(tick, hit)] = hits
    assert hit.move_id == throw_id and tick == throw.release
    assert hit.damage == pytest.approx(throw.damage * FRESH)
    assert victim.damage == pytest.approx(50 + throw.damage * FRESH)
    assert grabber.facing is facing
    assert grabber.stale_queue == [throw_id]
    assert launch is not None and launch.elevation == throw.angle
    assert (launch.heading.x, launch.heading.y) == pytest.approx((heading.world.x, heading.world.y))
    assert launch.knockback == pytest.approx(
        kb.knockback(victim.damage, hit.damage, ROOK.weight, throw.bkb, throw.kbg)
    )
    assert victim.state in (StateId.TUMBLE, StateId.FLINCH, StateId.KNOCKDOWN, StateId.FALL)
    assert victim.grab_partner == grabber.grab_partner == NO_PARTNER
    assert peak > 0.2, "thrown into the air"
    if throw_id in ("fthrow", "bthrow"):
        away = victim.pos - grabber.pos
        assert away.xy.dot(heading.world) > 1.0, "and away along the throw's heading"
    run_until(match, grabber, StateId.IDLE, limit=60)


def test_a_throw_can_be_di_ed() -> None:
    def thrown(p2: list[InputFrame]) -> Fighter:
        match, _, victim = grabbed(damage=80.0)
        run(match, hold(Dir8.SE, frames=1) + neutral(20), p2)
        return victim

    plain = thrown(neutral(21))
    bent = thrown(neutral(12) + hold(Dir8.SW, frames=9))
    assert plain.pos.y == pytest.approx(Y)
    assert bent.pos.y > Y + 0.05


def test_hitting_the_grabber_frees_the_victim() -> None:
    stage = load_stage("training_grid")
    match = Match.create(stage, [ROOK, ROOK, ROOK], seed=1, rules=MatchRules(stocks=None))
    grabber, victim, third = match.fighters
    place(match, grabber, X, Y, facing=Dir8.SE)
    place(match, victim, X + 1.0, Y)
    place(match, third, X - 1.0, Y, facing=Dir8.SE)
    run(match, GRAB + neutral(5))
    assert victim.state is StateId.GRABBED
    start_move(match, third, "ftilt")
    for _ in range(40):
        match.tick([InputFrame()] * 3)
    assert grabber.damage > 0
    assert victim.state is StateId.IDLE and victim.grab_partner == NO_PARTNER
    assert grabber.state is not StateId.GRAB_HOLD


def test_a_victim_held_past_an_edge_falls_when_released() -> None:
    match, grabber, victim = duel()
    place(match, grabber, 11.8, Y, facing=Dir8.SE)
    place(match, victim, 11.9, Y)
    run(match, GRAB + neutral(5))
    assert victim.state is StateId.GRABBED and victim.pos.x > 12.0 + ROOK.body.radius
    run(match, neutral(hold_frames(0.0) + 2))
    assert victim.state is StateId.GRAB_RELEASE and not victim.grounded
    assert grabber.grounded


def test_make_stage_is_available_for_wall_tests() -> None:
    assert make_stage(["00"]).size_x == 2
    assert make_match().fighters[0].shield_hp == c.SHIELD_MAX_HP
