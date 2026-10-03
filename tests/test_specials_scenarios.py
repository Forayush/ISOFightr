"""Scenario tests for special moves, projectiles, counters, armor and the script hooks.

Plan notes "05 - Combat Core" ("Projectiles", "Counters and armor"), "07 - Fighter State
Machine and Move Data" (special-move scripts) and "12 - Roster" (Rook's specials).
"""

import dataclasses
import math
import tomllib
from types import MappingProxyType

import pytest

from helpers import hold, make_match, neutral, place, run, run_until
from isofightr.data.character_loader import load_character
from isofightr.data.move_loader import parse_move
from isofightr.data.stage_loader import load_stage
from isofightr.data.validation import DataError
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.characters import SCRIPTS, MoveScript
from isofightr.sim.characters import rook as rook_scripts
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.combat.shield import shieldstun_frames
from isofightr.sim.events import (
    ClankEvent,
    CounterEvent,
    HitEvent,
    ProjectileEvent,
    ShieldHitEvent,
)
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, VERTICAL_UP, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import ArmorDef, FrameRange, GroundBehavior, MoveDef, MoveKind
from isofightr.sim.projectile import REFLECT_DAMAGE_MULT, reflect
from isofightr.sim.states.interrupts import start_move

ROOK = load_character("rook")
FRESH = c.FRESH_BONUS
X, Y = 3.0, 6.0
SPECIAL = hold(buttons=Button.SPECIAL, frames=1)
WAVE = ROOK.moves["nspecial"].projectiles[0]


def with_moves(*moves: MoveDef) -> CharacterDef:
    """Return Rook with some moves replaced or added."""
    table = dict(ROOK.moves)
    for move in moves:
        table[move.id] = move
    return dataclasses.replace(ROOK, moves=MappingProxyType(table))


def duel(
    gap: float = 1.0,
    damage: float = 0.0,
    first: CharacterDef = ROOK,
    second: CharacterDef = ROOK,
    players: int = 2,
) -> tuple[Match, Fighter, Fighter]:
    """P1 faces P2 along +x, ``gap`` apart, on open ground."""
    characters = [first, second, *[ROOK] * (players - 2)]
    stage = load_stage("training_grid")
    match = Match.create(stage, characters, seed=1, rules=MatchRules(stocks=None))
    one, two = match.fighters[:2]
    place(match, one, X, Y, facing=Dir8.SE)
    place(match, two, X + gap, Y, facing=Dir8.NW, damage=damage)
    return match, one, two


def collect(match: Match, p1: list[InputFrame], p2: list[InputFrame] | None, kind: type) -> list:  # type: ignore[type-arg]
    """Run tick by tick and collect ``(tick, event)`` of one event type."""
    seen = []
    for index, frame in enumerate(p1):
        run(match, [frame], None if p2 is None or index >= len(p2) else [p2[index]])
        seen.extend((index + 1, event) for event in match.events if isinstance(event, kind))
    return seen


# --- which special ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "vertical", "move_id"),
    [
        (None, 0, "nspecial"),
        (Dir8.NW, 0, "sspecial"),
        (None, VERTICAL_UP, "uspecial"),
        (Dir8.SE, VERTICAL_UP, "uspecial"),
        (None, VERTICAL_DOWN, "dspecial"),
    ],
)
@pytest.mark.parametrize("airborne", [False, True])
def test_special_selection(
    direction: Dir8 | None, vertical: int, move_id: str, airborne: bool
) -> None:
    match, fighter, _ = duel(gap=6.0)
    if airborne:
        place(match, fighter, X, Y, z=5.0)
    run(match, hold(direction, Button.SPECIAL, frames=1, vertical=vertical))
    assert (fighter.state, fighter.move_id) == (StateId.ATTACK, move_id)
    assert not fighter.fast_falling


def test_special_beats_attack_when_both_are_pressed() -> None:
    match, fighter, _ = duel(gap=6.0)
    run(match, hold(buttons=Button.SPECIAL | Button.ATTACK, frames=1))
    assert fighter.move_id == "nspecial"


def test_taunt_is_a_move_with_no_hitboxes() -> None:
    match, fighter, other = duel()
    run(match, hold(buttons=Button.TAUNT, frames=1))
    assert (fighter.state, fighter.move_id) == (StateId.ATTACK, "taunt")
    run(match, neutral(59))
    assert fighter.state is StateId.ATTACK and other.damage == 0
    run(match, neutral(1))
    assert fighter.state is StateId.IDLE


# --- Crescent Wave: projectiles -----------------------------------------------------------


def test_crescent_wave_fires_a_projectile_that_flies_and_fades() -> None:
    match, fighter, _ = duel(gap=8.5)
    seen = collect(match, SPECIAL + neutral(60), None, ProjectileEvent)
    assert [(tick, event.spawned, event.owner) for tick, event in seen] == [
        (WAVE.frame, True, 0),
        (WAVE.frame + WAVE.lifetime, False, 0),  # it already flies on the tick it is fired
    ]
    start, end = seen[0][1].position, seen[1][1].position
    assert start == Vec3(X + 0.9, Y, 1.2)
    assert end.x - start.x == pytest.approx(WAVE.speed * WAVE.lifetime)
    assert (end.y, end.z) == (start.y, start.z), "straight along the facing"
    assert match.projectiles == [] and fighter.state is StateId.IDLE


def test_a_projectile_moves_every_tick_and_is_part_of_the_state_hash() -> None:
    match, _, _ = duel(gap=8.5)
    run(match, SPECIAL + neutral(WAVE.frame - 1))
    [projectile] = match.projectiles
    assert (projectile.owner, projectile.move_id, projectile.age) == (0, "nspecial", 1)
    before = projectile.pos
    first_hash = match.state_hash()
    run(match, neutral(1))
    assert projectile.pos.x == pytest.approx(before.x + WAVE.speed) and projectile.age == 2
    assert projectile.previous == before
    assert match.state_hash() != first_hash
    projectile.damage += 1
    changed = match.state_hash()
    projectile.damage -= 1
    assert match.state_hash() != changed


def test_crescent_wave_hits_and_only_the_target_freezes() -> None:
    match, attacker, target = duel(gap=3.0, damage=30.0)
    seen = collect(match, SPECIAL + neutral(40), None, HitEvent)
    [(tick, hit)] = seen
    assert WAVE.frame < tick < WAVE.frame + 12
    assert (hit.attacker, hit.target, hit.move_id) == (0, 1, "nspecial")
    assert hit.damage == pytest.approx(7 * FRESH)
    assert target.damage == pytest.approx(30 + 7 * FRESH)
    assert hit.knockback == pytest.approx(kb.knockback(target.damage, hit.damage, 98, 25, 60))
    assert attacker.stale_queue == ["nspecial"]
    assert match.projectiles == [], "destroyed by the hit"
    assert target.pos.x > X + 3.0, "knocked along the wave's flight"


def test_the_owner_is_not_frozen_by_its_projectile_hitting() -> None:
    match, attacker, target = duel(gap=3.0)
    for _ in range(40):
        run(match, SPECIAL if match.frame == 0 else neutral(1))
        if target.hitlag > 0:
            break
    assert target.hitlag > 0 and attacker.hitlag == 0


@pytest.mark.parametrize(("held", "charged"), [(11, 1), (40, 30), (200, 60)])
def test_charging_crescent_wave_makes_it_stronger_and_longer_lived(held: int, charged: int) -> None:
    match, fighter, _ = duel(gap=8.5)
    charge = ROOK.moves["nspecial"].charge
    assert charge is not None
    for frame in hold(buttons=Button.SPECIAL, frames=held) + neutral(40):
        run(match, [frame])
        if match.projectiles:
            break
    [projectile] = match.projectiles
    fraction = charged / charge.max_frames
    assert fighter.charge_frames == charged
    assert projectile.damage == pytest.approx(7 * (1 + 0.5 * fraction) * FRESH)
    scale = 1 + (rook_scripts.WAVE_CHARGE_LIFETIME_MULT - 1) * fraction
    assert projectile.lifetime == round(WAVE.lifetime * scale)


def test_a_shield_blocks_a_projectile_with_little_shieldstun() -> None:
    match, attacker, target = duel(gap=3.0)
    seen = collect(
        match, SPECIAL + neutral(35), hold(buttons=Button.SHIELD, frames=36), ShieldHitEvent
    )
    assert len(seen) == 1 and not seen[0][1].parried
    assert target.damage == 0 and match.projectiles == []
    damage = 7 * FRESH
    assert target.shield_hp < c.SHIELD_MAX_HP - damage
    stun = math.floor(shieldstun_frames(damage) * c.PROJECTILE_SHIELDSTUN_MULT)
    assert stun == 1 < shieldstun_frames(damage)
    assert attacker.hitlag == 0 and attacker.stale_queue == []


def test_a_projectile_passes_through_an_intangible_fighter_and_its_owner() -> None:
    match, attacker, target = duel(gap=3.0)
    target.intangible_frames = 200
    run(match, SPECIAL + neutral(WAVE.frame + 20))
    [projectile] = match.projectiles
    assert projectile.pos.x > target.pos.x and target.damage == 0
    assert attacker.damage == 0


def test_a_piercing_projectile_hits_each_fighter_once() -> None:
    wave = dataclasses.replace(WAVE, pierce=1, lifetime=60)
    move = dataclasses.replace(ROOK.moves["nspecial"], projectiles=(wave,), script=None)
    match, attacker, target = duel(gap=2.5, first=with_moves(move), players=3)
    third = match.fighters[2]
    place(match, third, X + 4.5, Y)
    seen = collect(match, SPECIAL + neutral(60), None, HitEvent)
    assert [hit.target for _, hit in seen] == [1, 2]
    assert match.projectiles == [], "the second hit used up its last pierce"
    assert attacker.stale_queue == ["nspecial"], "one stale entry however many it hits"
    assert target.damage == pytest.approx(third.damage)


def test_an_attack_swats_a_projectile() -> None:
    match, attacker, target = duel(gap=3.0)
    # P2 swings a forward tilt (active 7-9) as the wave arrives.
    for tick in range(60):
        frame = SPECIAL if tick == 0 else neutral(1)
        swing = hold(Dir8.NW, Button.ATTACK, frames=1) if tick == WAVE.frame + 1 else neutral(1)
        run(match, frame, swing)
        if any(isinstance(event, ClankEvent) for event in match.events):
            break
    else:
        pytest.fail("the tilt never met the wave")
    assert match.projectiles == [] and target.damage == 0
    assert target.state is StateId.ATTACK, "a 9% tilt beats a 7% wave: no rebound"
    assert attacker.stale_queue == []


def test_two_projectiles_cancel_each_other() -> None:
    match, first, second = duel(gap=6.0)
    run(match, SPECIAL + neutral(60), SPECIAL + neutral(60))
    assert first.damage == second.damage == 0
    assert match.projectiles == []


def test_projectiles_end_on_the_ground_or_bounce_and_leave_through_the_blast_zone() -> None:
    def lob(ground: GroundBehavior) -> tuple[Match, list[float]]:
        ball = dataclasses.replace(WAVE, rise=0.05, gravity=0.01, lifetime=400, ground=ground)
        move = dataclasses.replace(ROOK.moves["nspecial"], projectiles=(ball,), script=None)
        match, _, target = duel(gap=1.0, first=with_moves(move))
        place(match, target, 1.0, 1.0)
        run(match, SPECIAL + neutral(WAVE.frame - 1))
        heights = []
        for _ in range(120):
            run(match, neutral(1))
            if not match.projectiles:
                break
            heights.append(match.projectiles[0].pos.z)
        return match, heights

    match, heights = lob(GroundBehavior.DESTROY)
    assert match.projectiles == [] and 10 < len(heights) < 60
    assert max(heights) > 1.25 and min(heights) >= WAVE.hitbox.radius - 0.2

    match, heights = lob(GroundBehavior.BOUNCE)
    low = [index for index, z in enumerate(heights) if z == pytest.approx(WAVE.hitbox.radius)]
    assert low, "it touched the ground"
    assert max(heights[low[0] :]) > WAVE.hitbox.radius + 0.2, "and came back up"
    assert match.projectiles == [], "it flew off the stage and out of the blast zone"

    match, heights = lob(GroundBehavior.SLIDE)
    assert heights.count(pytest.approx(WAVE.hitbox.radius)) > 10, "it stays on the ground"


def test_reflecting_a_projectile_sends_it_back_stronger() -> None:
    mirror = dataclasses.replace(ROOK.moves["taunt"], reflect=FrameRange(1, 60))
    match, attacker, target = duel(gap=3.0, damage=0.0, second=with_moves(mirror))
    start_move(match, target, "taunt")
    seen = collect(match, SPECIAL + neutral(50), None, HitEvent)
    [(_, hit)] = seen
    assert (hit.attacker, hit.target) == (1, 0), "it now belongs to the reflector"
    assert hit.damage == pytest.approx(7 * FRESH * REFLECT_DAMAGE_MULT)
    assert attacker.damage == pytest.approx(hit.damage) and target.damage == 0
    assert target.stale_queue == ["nspecial"]


def test_reflect_helper_and_unreflectable_projectiles() -> None:
    match, _, _ = duel(gap=8.0)
    run(match, SPECIAL + neutral(WAVE.frame))
    [projectile] = match.projectiles
    velocity, damage = projectile.vel, projectile.damage
    projectile.hit.append(1)
    reflect(projectile, 1)
    assert projectile.vel == Vec3(-velocity.x, -velocity.y, velocity.z)
    assert projectile.damage == damage * REFLECT_DAMAGE_MULT
    assert (projectile.owner, projectile.hit, projectile.age) == (1, [], 0)

    solid = dataclasses.replace(WAVE, reflectable=False)
    move = dataclasses.replace(ROOK.moves["nspecial"], projectiles=(solid,))
    mirror = dataclasses.replace(ROOK.moves["taunt"], reflect=FrameRange(1, 60))
    match, attacker, target = duel(gap=3.0, first=with_moves(move), second=with_moves(mirror))
    start_move(match, target, "taunt")
    run(match, SPECIAL + neutral(40))
    assert target.damage > 0 and attacker.damage == 0


# --- Lunge --------------------------------------------------------------------------------


@pytest.mark.parametrize("direction", [Dir8.SE, Dir8.NW, Dir8.N, Dir8.SW])
def test_lunge_dashes_where_the_stick_points(direction: Dir8) -> None:
    match, fighter, _ = duel(gap=1.0)
    place(match, fighter, 6.0, 6.0, facing=Dir8.SE)
    place(match, match.fighters[1], 1.0, 1.0)
    run(match, hold(direction, Button.SPECIAL, frames=1))
    assert fighter.move_id == "sspecial" and fighter.facing is direction
    first, last = rook_scripts.LUNGE_FRAMES
    run(match, neutral(first - 2))
    assert fighter.pos == Vec3(6.0, 6.0, 0.0), "no movement during the wind-up"
    run(match, neutral(last - first + 1))
    moved = fighter.pos - Vec3(6.0, 6.0, 0.0)
    expected = direction.world * (rook_scripts.LUNGE_SPEED * (last - first + 1))
    assert (moved.x, moved.y) == pytest.approx((expected.x, expected.y))
    run_until(match, fighter, StateId.IDLE, limit=60)
    assert match.frame == ROOK.moves["sspecial"].total + 1


def test_lunge_hits_on_the_way() -> None:
    match, _, target = duel(gap=2.5, damage=20.0)
    seen = collect(match, hold(Dir8.SE, Button.SPECIAL, frames=1) + neutral(30), None, HitEvent)
    assert [hit.move_id for _, hit in seen] == ["sspecial"]
    assert target.damage == pytest.approx(20 + 10 * FRESH)


def test_lunge_in_the_air_holds_its_height_and_works_once_per_airtime() -> None:
    match, fighter, _ = duel(gap=6.0)
    place(match, fighter, 9.0, Y, z=8.0, facing=Dir8.SE)
    lunge = hold(Dir8.NW, Button.SPECIAL, frames=1)
    run(match, lunge)
    assert fighter.move_id == "sspecial" and fighter.facing is Dir8.NW, "aims in the air too"
    first, last = rook_scripts.LUNGE_FRAMES
    run(match, neutral(first - 1))
    height = fighter.pos.z
    run(match, neutral(last - first))
    assert fighter.pos.z == height and fighter.pos.x < 9.0 - 1.5
    run_until(match, fighter, StateId.FALL, limit=60)
    assert fighter.air_moves_used == ["sspecial"]
    run(match, lunge + neutral(1))
    assert fighter.state is StateId.FALL, "already used this airtime"
    run(match, SPECIAL)
    assert fighter.move_id == "nspecial", "other specials still work"
    run_until(match, fighter, StateId.IDLE, limit=300)
    assert fighter.air_moves_used == []
    run(match, lunge)
    assert fighter.move_id == "sspecial"


def test_lunge_carries_on_off_an_edge_and_lands_with_its_own_lag() -> None:
    match, fighter, _ = duel(gap=6.0)
    place(match, fighter, 11.0, Y, facing=Dir8.SE)
    run(match, hold(Dir8.SE, Button.SPECIAL, frames=1) + neutral(16))
    assert fighter.state is StateId.ATTACK and not fighter.grounded and fighter.pos.x > 12.3

    match, fighter, _ = duel(gap=6.0)
    place(match, fighter, X, Y, z=0.6)
    run(match, hold(Dir8.SE, Button.SPECIAL, frames=1))
    run_until(match, fighter, StateId.LAND, limit=80)
    assert fighter.land_lag == ROOK.moves["sspecial"].landing_lag == 12


# --- Rising Spin --------------------------------------------------------------------------


def up_special() -> list[InputFrame]:
    return hold(buttons=Button.SPECIAL, frames=1, vertical=VERTICAL_UP)


def test_rising_spin_climbs_and_ends_helpless() -> None:
    match, fighter, _ = duel(gap=6.0)
    run(match, up_special())
    first, last = rook_scripts.RISING_SPIN_FRAMES
    run(match, neutral(last - 1))
    climb = rook_scripts.RISING_SPIN_RISE * (last - first + 1)
    assert fighter.pos.z == pytest.approx(climb) and climb > 4.0
    assert (fighter.pos.x, fighter.pos.y) == (X, Y), "straight up without the stick"
    run_until(match, fighter, StateId.HELPLESS, limit=60)
    assert match.frame == ROOK.moves["uspecial"].total + 1
    run(match, hold(buttons=Button.JUMP, frames=1) + neutral(1) + up_special())
    assert fighter.state is StateId.HELPLESS, "no jump, no second up special"
    run_until(match, fighter, StateId.LAND, limit=300)
    assert fighter.land_lag == c.HELPLESS_LAND_LAG


def test_rising_spin_can_be_steered() -> None:
    match, fighter, _ = duel(gap=6.0)
    first, last = rook_scripts.RISING_SPIN_FRAMES
    run(match, up_special() + hold(Dir8.SE, frames=last - 1))
    assert fighter.pos.x == pytest.approx(X + rook_scripts.RISING_SPIN_STEER * (last - first + 1))


def test_rising_spin_works_in_the_air_and_after_the_air_jump() -> None:
    match, fighter, _ = duel(gap=6.0)
    place(match, fighter, X, Y, z=2.0)
    fighter.air_jumps_left = 0
    run(match, up_special() + neutral(30))
    assert fighter.pos.z > 5.5


def test_rising_spin_drags_the_target_up_and_launches_it_at_the_end() -> None:
    match, attacker, target = duel(gap=0.4, damage=40.0)
    seen = collect(match, up_special() + neutral(60), None, HitEvent)
    hits = [hit for _, hit in seen]
    assert len(hits) >= 4 and {hit.move_id for hit in hits} == {"uspecial"}
    assert [hit.damage for hit in hits[:-1]] == pytest.approx([1.2 * FRESH] * (len(hits) - 1))
    assert hits[-1].damage == pytest.approx(5 * FRESH)
    assert hits[-1].knockback > hits[0].knockback
    assert attacker.stale_queue == ["uspecial"], "one move use, one stale entry"
    assert target.pos.z > 2.5 and target.state is StateId.TUMBLE


def test_rising_spin_catches_a_ledge_only_late_in_the_move() -> None:
    def near_ledge(frame: int) -> Fighter:
        match, fighter, _ = duel(gap=6.0)
        place(match, fighter, -0.4, Y, z=-1.0)
        start_move(match, fighter, "uspecial")
        fighter.state_frame = frame
        fighter.vel = Vec3(0.0, 0.0, -0.01)
        run(match, neutral(3))
        return fighter

    assert near_ledge(34).state is StateId.LEDGE_HANG
    assert near_ledge(30).state is StateId.LEDGE_HANG
    early = near_ledge(2)
    assert early.state is StateId.ATTACK


def test_rising_spin_recovers_from_far_below_the_stage() -> None:
    match, fighter, _ = duel(gap=6.0)
    place(match, fighter, -1.0, Y, z=-6.5)
    fighter.air_jumps_left = 0
    run(match, hold(Dir8.SE, Button.SPECIAL, frames=1, vertical=VERTICAL_UP))
    for _ in range(120):
        if fighter.state is StateId.LEDGE_HANG:
            break
        run(match, hold(Dir8.SE, frames=1))
    assert fighter.state is StateId.LEDGE_HANG


def test_up_special_out_of_shield() -> None:
    match, fighter, _ = duel(gap=6.0)
    shield = hold(buttons=Button.SHIELD, frames=5)
    oos = hold(buttons=Button.SHIELD | Button.SPECIAL, frames=1, vertical=VERTICAL_UP)
    run(match, shield + oos)
    assert (fighter.state, fighter.move_id) == (StateId.ATTACK, "uspecial")


# --- Riposte: counters --------------------------------------------------------------------


def down_special() -> list[InputFrame]:
    return hold(buttons=Button.SPECIAL, frames=1, vertical=VERTICAL_DOWN)


def test_riposte_whiffs_when_nothing_hits_it() -> None:
    match, fighter, other = duel()
    run(match, down_special() + neutral(49))
    assert fighter.state is StateId.ATTACK and fighter.move_id == "dspecial"
    run(match, neutral(1))
    assert fighter.state is StateId.IDLE and other.damage == 0


@pytest.mark.parametrize(
    ("attack", "delay", "reply_damage"),
    [
        (hold(buttons=Button.STRONG, frames=1), 0, 16 * FRESH * 1.2),  # smash lands on tick 14
        (hold(buttons=Button.ATTACK, frames=1), 8, 8.0),  # a weak jab: the reply's own 8%
    ],
)
def test_riposte_cancels_the_hit_and_strikes_back(
    attack: list[InputFrame], delay: int, reply_damage: float
) -> None:
    match, attacker, countering = duel()
    events: list[object] = []
    for tick in range(70):
        p1 = attack if tick == delay else neutral(1)
        p2 = down_special() if tick == 4 else neutral(1)
        run(match, p1, p2)
        events.extend(e for e in match.events if isinstance(e, HitEvent | CounterEvent))
    counters = [e for e in events if isinstance(e, CounterEvent)]
    hits = [e for e in events if isinstance(e, HitEvent)]
    assert len(counters) == 1 and counters[0].player == 1
    assert countering.damage == 0, "the countered hit does nothing"
    assert [(hit.attacker, hit.move_id) for hit in hits] == [(1, "riposte_hit")]
    assert hits[0].damage == pytest.approx(reply_damage * FRESH)
    assert attacker.damage == pytest.approx(reply_damage * FRESH)
    assert countering.stale_queue == ["riposte_hit"]


def test_riposte_only_counters_inside_its_window() -> None:
    counter = ROOK.moves["dspecial"].counter
    assert counter is not None and (counter.frames.first, counter.frames.last) == (5, 25)
    for frame, countered in ((3, False), (5, True), (25, True), (26, False)):
        match, attacker, countering = duel()
        start_move(match, countering, "dspecial")
        start_move(match, attacker, "jab1")
        # The jab lands on its frame 3, two ticks from now: set Riposte's frame to match.
        countering.state_frame = frame - 2
        run(match, neutral(3))
        assert (countering.damage == 0) is countered, frame


def test_riposte_turns_to_face_the_attacker() -> None:
    match, attacker, countering = duel()
    place(match, countering, X + 1.0, Y, facing=Dir8.SE)  # back turned
    jab = neutral(5) + hold(buttons=Button.ATTACK, frames=1) + neutral(30)
    run(match, jab, down_special() + neutral(30))
    assert countering.facing is Dir8.NW and attacker.damage > 0


def test_riposte_counters_a_projectile() -> None:
    match, attacker, countering = duel(gap=3.0)
    counters = []
    for tick in range(60):
        p2 = down_special() if tick == WAVE.frame else neutral(1)
        run(match, SPECIAL if tick == 0 else neutral(1), p2)
        counters.extend(e for e in match.events if isinstance(e, CounterEvent))
    assert len(counters) == 1 and countering.damage == 0
    assert match.projectiles == [] and attacker.hitlag == 0
    assert countering.move_id == "riposte_hit"


# --- armor --------------------------------------------------------------------------------


def armored(threshold: float) -> CharacterDef:
    armor = ArmorDef(FrameRange(1, 48), threshold)
    return with_moves(dataclasses.replace(ROOK.moves["fsmash"], armor=(armor,)))


def test_super_armor_takes_the_damage_but_not_the_launch() -> None:
    match, attacker, tank = duel(damage=80.0, second=armored(math.inf))
    start_move(match, tank, "fsmash")
    tank.state_frame = 2
    run(match, hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(40))
    assert tank.damage == pytest.approx(80 + 9 * FRESH)
    assert tank.last_knockback > 60
    assert tank.pos.x <= X + 1.0 + 0.5 and attacker.damage > 0, "it kept swinging and hit back"


def test_heavy_armor_breaks_at_its_threshold() -> None:
    for threshold, launched in ((500.0, False), (30.0, True)):
        match, _, tank = duel(damage=80.0, second=armored(threshold))
        start_move(match, tank, "fsmash")
        run(match, hold(Dir8.SE, Button.ATTACK, frames=1) + neutral(20))
        assert (tank.state is not StateId.ATTACK) is launched, threshold


# --- scripts and data validation ----------------------------------------------------------

BASE = """
id = "zap"
kind = "special"
total = 30
faf = 31
"""


def parse(text: str) -> MoveDef:
    return parse_move(tomllib.loads(text), source="zap.toml", expected_id="zap")


def test_rook_registers_three_scripts_and_the_moves_name_them() -> None:
    rook_scripts = sorted(name for name in SCRIPTS if name.startswith("rook."))
    assert rook_scripts == ["rook.neutral_special", "rook.side_special", "rook.up_special"]
    assert all(isinstance(script, MoveScript) for script in SCRIPTS.values())
    named = {move.id: move.script for move in ROOK.moves.values() if move.script}
    assert named == {
        "nspecial": "rook.neutral_special",
        "sspecial": "rook.side_special",
        "uspecial": "rook.up_special",
    }
    assert ROOK.moves["uspecial"].helpless and ROOK.moves["uspecial"].ledge_grab_from == 28
    assert ROOK.moves["sspecial"].once_per_airtime


def test_special_move_keys_parse() -> None:
    move = parse(
        BASE
        + 'script = "rook.up_special"\nhelpless = true\nledge_grab_from = 20\nlanding_lag = 9\n'
        + 'once_per_airtime = true\nreflect = "3-9"\n'
        + "charge = { frame = 4, max_frames = 30, damage_mult = 1.3 }\n"
        + '[counter]\nframes = "5-25"\ninto = "zap"\ndamage_mult = 1.5\n'
        + '[[armor]]\nframes = "1-4"\n[[armor]]\nframes = "5-9"\nthreshold = 70\n'
        + "[[projectiles]]\nframe = 12\nspeed = 0.2\nrise = 0.1\ngravity = 0.01\nlifetime = 40\n"
        + 'pierce = 2\nreflectable = false\nabsorbable = true\nground = "bounce"\n'
        + "  [projectiles.hitbox]\n  id = 0\n  offset = [1.0, 0.0, 1.0]\n  radius = 0.3\n"
        + "  damage = 4.0\n  angle = 30\n"
    )
    assert move.kind is MoveKind.SPECIAL and move.script == "rook.up_special"
    assert (move.helpless, move.ledge_grab_from, move.landing_lag) == (True, 20, 9)
    assert move.once_per_airtime and move.reflect == FrameRange(3, 9)
    assert move.charge is not None and move.counter is not None
    assert (move.counter.into, move.counter.damage_mult) == ("zap", 1.5)
    assert move.armor_threshold(2) == math.inf and move.armor_threshold(7) == 70
    assert move.armor_threshold(10) is None
    [ball] = move.projectiles
    assert (ball.frame, ball.speed, ball.rise, ball.gravity, ball.lifetime) == (
        12,
        0.2,
        0.1,
        0.01,
        40,
    )
    assert (ball.pierce, ball.reflectable, ball.absorbable) == (2, False, True)
    assert ball.ground is GroundBehavior.BOUNCE and ball.hitbox.damage == 4.0
    assert ball.hitbox.clank, "projectiles clank by default"


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            'script = "rook.nope"\n',
            r"script: no such move script 'rook.nope' \(registered: .*rook\.",
        ),
        ("ledge_grab_from = 40\n", r"ledge_grab_from: must be between 1 and total \(30\)"),
        ('[counter]\nframes = "5-45"\ninto = "zap"\n', "counter.frames: frames '5-45' must lie"),
        ('[counter]\nframes = "5-9"\ninto = "zap"\ndamage_mult = 0.5\n', "damage_mult: must be 1"),
        ('[[armor]]\nframes = "1-4"\nthreshold = 0\n', r"armor\[0\]\.threshold: must be greater"),
        ('[[armor]]\nframes = "1-4"\nstrength = 3\n', r"armor\[0\]: unknown key\(s\) 'strength'"),
        (
            "[[projectiles]]\nframe = 31\nspeed = 0.1\nlifetime = 5\n[projectiles.hitbox]\n"
            "id = 0\noffset = [0, 0, 0]\nradius = 0.3\ndamage = 1\nangle = 0\n",
            r"projectiles\[0\]\.frame: must be between 1 and total",
        ),
        (
            "[[projectiles]]\nframe = 3\nspeed = 0.1\nlifetime = 0\n[projectiles.hitbox]\n"
            "id = 0\noffset = [0, 0, 0]\nradius = 0.3\ndamage = 1\nangle = 0\n",
            r"projectiles\[0\]\.lifetime: must be 1 or greater",
        ),
        (
            "[[projectiles]]\nframe = 3\nspeed = 0.1\nlifetime = 9\n",
            r"projectiles\[0\]\.hitbox: missing required key",
        ),
        (
            '[[projectiles]]\nframe = 3\nspeed = 0.1\nlifetime = 9\nground = "stick"\n'
            "[projectiles.hitbox]\nid = 0\noffset = [0, 0, 0]\nradius = 0.3\ndamage = 1\n"
            "angle = 0\n",
            "ground: must be one of destroy, bounce, slide",
        ),
    ],
)
def test_special_move_mistakes_are_reported(extra: str, message: str) -> None:
    with pytest.raises(DataError, match=r"^zap\.toml: .*" + message):
        parse(BASE + extra)


def test_a_counter_must_reply_with_an_existing_move(tmp_path: object) -> None:
    import shutil
    from pathlib import Path

    from isofightr.data.paths import CHARACTERS_DIR

    target = Path(str(tmp_path)) / "characters"
    shutil.copytree(CHARACTERS_DIR, target)
    path = target / "rook" / "moves" / "dspecial.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("riposte_hit", "nope"), encoding="utf-8"
    )
    with pytest.raises(DataError, match="move 'dspecial' counters with unknown move 'nope'"):
        load_character("rook", target)


def test_every_rook_move_can_be_started_and_runs_to_its_end() -> None:
    """M5 exit criterion: every move is in data and exercised at least once."""
    for move_id, move in ROOK.moves.items():
        match = make_match(stocks=None)
        fighter = match.fighters[0]
        place(match, fighter, 6.0, 6.0)
        place(match, match.fighters[1], 1.0, 1.0)
        if move.kind is MoveKind.AERIAL:
            place(match, fighter, 6.0, 6.0, z=10.0)
        start_move(match, fighter, move_id)
        run(match, neutral(move.total + 40))
        assert fighter.state is not StateId.ATTACK or fighter.move_id != move_id, move_id
        assert fighter.in_play, move_id
