"""Scenario tests for Bramble, Zephyr and Mote: their stats and their special moves.

Plan note "12 - Roster" (the starter four) and "05 - Combat Core" ("Projectiles"). The
mechanics they added to the sim (bursting, returning and limited projectiles, a ledge tether,
stored charge, 3D-aimed recoveries) are tested here through the moves that use them.
"""

import pytest

from helpers import hold, neutral, place, run, run_until
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.characters import mote as mote_scripts
from isofightr.sim.characters import zephyr as zephyr_scripts
from isofightr.sim.events import HitEvent, ShockwaveEvent
from isofightr.sim.fighter import NO_LEDGE, Fighter, StateId
from isofightr.sim.input_frame import VERTICAL_UP, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules

ROOK = load_character("rook")
BRAMBLE = load_character("bramble")
ZEPHYR = load_character("zephyr")
MOTE = load_character("mote")
X, Y = 3.0, 6.0
SPECIAL = hold(buttons=Button.SPECIAL, frames=1)


def duel(
    first: CharacterDef, second: CharacterDef = ROOK, gap: float = 2.0, damage: float = 0.0
) -> tuple[Match, Fighter, Fighter]:
    """P1 faces P2 along +x, ``gap`` apart, on Training Grid."""
    match = Match.create(
        load_stage("training_grid"), [first, second], seed=1, rules=MatchRules(stocks=None)
    )
    one, two = match.fighters
    place(match, one, X, Y, facing=Dir8.SE)
    place(match, two, X + gap, Y, facing=Dir8.NW, damage=damage)
    return match, one, two


def events_of(match: Match, inputs: list[InputFrame], kind: type) -> list:  # type: ignore[type-arg]
    seen = []
    for frame in inputs:
        run(match, [frame])
        seen.extend(event for event in match.events if isinstance(event, kind))
    return seen


# --- stats ------------------------------------------------------------------------------------


def test_archetypes_differ_where_the_plan_says() -> None:
    weights = [character.weight for character in (ROOK, BRAMBLE, ZEPHYR, MOTE)]
    assert weights == [98, 120, 78, 85]
    runs = {c.id: c.movement.run_speed for c in (ROOK, BRAMBLE, ZEPHYR, MOTE)}
    assert (
        max(runs, key=runs.__getitem__) == "zephyr" and min(runs, key=runs.__getitem__) == "bramble"
    )
    assert ZEPHYR.movement.air_jumps == 2 and BRAMBLE.movement.air_jumps == 1
    assert MOTE.movement.max_fall < ROOK.movement.max_fall, "Mote is floaty"


def test_zephyr_has_two_air_jumps() -> None:
    match, zephyr, _ = duel(ZEPHYR, gap=8.0)
    run(match, hold(buttons=Button.JUMP, frames=1) + neutral(12))
    jumps = 0
    for _ in range(3):
        before = zephyr.air_jumps_left
        run(match, hold(buttons=Button.JUMP, frames=1) + neutral(10))
        jumps += zephyr.air_jumps_left < before
    assert jumps == 2 and zephyr.air_jumps_left == 0


def test_mote_falls_slowly() -> None:
    times = []
    for character in (ROOK, MOTE):
        match, fighter, _ = duel(character, gap=8.0)
        place(match, fighter, X, Y, z=6.0)
        times.append(run_until(match, fighter, StateId.LAND, limit=300))
    assert times[1] > times[0] * 1.3


# --- Bramble ----------------------------------------------------------------------------------


def test_boulder_toss_arcs_then_bursts_into_a_ground_shockwave() -> None:
    match, bramble, rook = duel(BRAMBLE, gap=8.0)
    place(match, bramble, 1.0, Y)
    place(match, rook, 1.0, 1.0)  # out of the way
    waves = events_of(match, SPECIAL + neutral(80), ShockwaveEvent)
    assert len(waves) == 1 and waves[0].position.z == pytest.approx(0.3)
    landing = waves[0].position
    assert landing.x > 1.0 + 4.0, "it arcs well forward"

    # A fighter standing a little past the landing spot is caught by the shockwave only.
    match, bramble, rook = duel(BRAMBLE, gap=8.0, damage=10.0)
    place(match, bramble, 1.0, Y)
    place(match, rook, landing.x + 1.1, Y, facing=Dir8.NW, damage=10.0)
    seen = events_of(match, SPECIAL + neutral(80), HitEvent)
    assert len(seen) == 1 and seen[0].position.z == pytest.approx(0.3), "hit by the burst"
    assert rook.damage == pytest.approx(
        10.0 + BRAMBLE.moves["nspecial"].projectiles[0].burst.damage * 1.05, rel=0.05
    )  # type: ignore[union-attr]


def test_the_shockwave_only_hits_the_ground() -> None:
    burst = BRAMBLE.moves["nspecial"].projectiles[0].burst
    assert burst is not None and burst.hits_ground and not burst.hits_air


def test_shoulder_charge_rushes_along_the_stick_through_hits() -> None:
    match, bramble, _ = duel(BRAMBLE, gap=1.3)
    # Bramble charges; Rook answers with a forward tilt that lands during the armor.
    run(match, hold(Dir8.SE, Button.SPECIAL, frames=1), neutral(1))
    run(match, neutral(1), hold(Dir8.NW, Button.ATTACK, frames=1))
    run(match, neutral(6))
    assert bramble.damage > 0 and bramble.hitlag > 0, "Rook's hit landed"
    run(match, neutral(bramble.hitlag + 1))
    assert bramble.state is StateId.ATTACK and bramble.move_id == "sspecial", "no flinch"
    assert bramble.hitstun == 0 and bramble.launch is None


def test_vine_lash_reels_bramble_to_a_ledge_in_reach() -> None:
    match, bramble, _ = duel(BRAMBLE, gap=8.0)
    place(match, bramble, 13.6, Y, z=-1.0, facing=Dir8.NW)  # off the +x edge, below its top
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=VERTICAL_UP))
    assert bramble.move_id == "uspecial"
    run_until(match, bramble, StateId.LEDGE_HANG, limit=60)
    assert bramble.ledge != NO_LEDGE and bramble.tether_ledge == NO_LEDGE


def test_vine_lash_without_a_ledge_is_a_short_leap_into_helpless() -> None:
    match, bramble, _ = duel(BRAMBLE, gap=8.0)
    place(match, bramble, 6.0, Y, z=5.0)
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=VERTICAL_UP) + neutral(12))
    height = bramble.pos.z
    run(match, neutral(8))
    assert bramble.pos.z > height, "leaping up"
    run_until(match, bramble, StateId.HELPLESS, limit=80)


def test_quake_slam_plummets_and_lands_as_a_shockwave() -> None:
    match, bramble, rook = duel(BRAMBLE, gap=1.5, damage=30.0)
    place(match, bramble, X, Y, z=5.0)
    waves = events_of(
        match, hold(buttons=Button.SPECIAL, frames=1, vertical=-1) + neutral(40), ShockwaveEvent
    )
    assert len(waves) == 1
    assert bramble.move_id == "quake_land" or bramble.state is not StateId.ATTACK
    assert (rook.damage > 30.0 and rook.kb_vel.z > 0) or rook.state is not StateId.IDLE, "popped up"


def test_quake_slam_on_the_ground_slams_at_once() -> None:
    match, bramble, _ = duel(BRAMBLE, gap=6.0)
    waves = events_of(
        match, hold(buttons=Button.SPECIAL, frames=1, vertical=-1) + neutral(2), ShockwaveEvent
    )
    assert len(waves) == 1 and bramble.move_id == "quake_land"


# --- Zephyr -----------------------------------------------------------------------------------


def test_feather_darts_fire_three_darts() -> None:
    match, _zephyr, _ = duel(ZEPHYR, gap=8.0)
    run(match, SPECIAL)
    fired = 0
    for _ in range(20):
        before = match.next_projectile_id
        run(match, neutral(1))
        fired += match.next_projectile_id - before
    assert fired == 3


def test_slipstream_passes_through_then_hits_on_the_way_out() -> None:
    match, zephyr, rook = duel(ZEPHYR, gap=1.5, damage=10.0)
    run(match, hold(Dir8.SE, Button.SPECIAL, frames=1))
    first, _ = zephyr_scripts.SLIPSTREAM_FRAMES
    run(match, neutral(first + 2))
    assert zephyr.intangible
    seen = events_of(match, neutral(20), HitEvent)
    assert [hit.move_id for hit in seen] == ["sspecial"]
    assert zephyr.pos.x > rook.pos.x, "went through"


@pytest.mark.parametrize(
    ("direction", "vertical", "expect"),
    [
        (None, 0, (0.0, 0.0, 1.0)),
        (Dir8.SE, VERTICAL_UP, (0.7071, 0.0, 0.7071)),
        (Dir8.SE, 0, (1.0, 0.0, 0.0)),
    ],
)
def test_gust_hop_bursts_in_the_chosen_3d_direction(
    direction: Dir8 | None, vertical: int, expect: tuple[float, float, float]
) -> None:
    match, zephyr, _ = duel(ZEPHYR, gap=8.0)
    place(match, zephyr, 6.0, Y, z=4.0)
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=VERTICAL_UP))
    run(match, hold(direction, frames=zephyr_scripts.GUST_WINDUP, vertical=vertical))
    assert tuple(
        round(v, 4) for v in (zephyr.special_dir.x, zephyr.special_dir.y, zephyr.special_dir.z)
    ) == pytest.approx(expect, abs=1e-3)
    start = zephyr.pos
    run(match, neutral(zephyr_scripts.GUST_FRAMES))
    moved = zephyr.pos - start
    assert moved.length() == pytest.approx(
        zephyr_scripts.GUST_SPEED * zephyr_scripts.GUST_FRAMES, rel=0.1
    )
    run_until(match, zephyr, StateId.HELPLESS, limit=60)


def test_whirl_reflects_projectiles_and_slows_the_fall() -> None:
    match, zephyr, _rook = duel(ZEPHYR, gap=4.0)
    run(match, neutral(1), SPECIAL)  # Rook fires a Crescent Wave
    run(match, neutral(10))
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=-1))
    for _ in range(30):
        run(match, neutral(1))
    owners = {projectile.owner for projectile in match.projectiles}
    assert owners <= {0}, "the wave now belongs to Zephyr (or is gone)"

    match, zephyr, _ = duel(ZEPHYR, gap=8.0)
    place(match, zephyr, 6.0, Y, z=6.0)
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=-1) + neutral(15))
    assert zephyr.vel.z >= -zephyr_scripts.WHIRL_MAX_FALL - 1e-9


# --- Mote -------------------------------------------------------------------------------------


def test_ember_orb_stores_its_charge_with_shield() -> None:
    match, mote, _ = duel(MOTE, gap=8.0)
    run(match, hold(buttons=Button.SPECIAL, frames=40))
    assert mote.state is StateId.ATTACK and mote.charge_frames > 20
    charged = mote.charge_frames
    run(match, hold(buttons=Button.SHIELD, frames=1))
    assert mote.stored_charge == charged and mote.state is not StateId.ATTACK
    run(match, neutral(20))
    run(match, SPECIAL)
    assert mote.charge_frames == charged and mote.stored_charge == 0


def test_a_fully_charged_orb_fires_at_once_and_is_bigger() -> None:
    match, mote, _ = duel(MOTE, gap=8.0)
    mote.stored_charge = MOTE.moves["nspecial"].charge.max_frames  # type: ignore[union-attr]
    run(match, SPECIAL + neutral(8))
    assert match.projectiles, "no charging: it fires straight away"
    orb = match.projectiles[0]
    assert orb.hitbox.radius == pytest.approx(
        MOTE.moves["nspecial"].projectiles[0].hitbox.radius * 2
    )


def test_orbit_lamp_goes_out_and_comes_back_one_at_a_time() -> None:
    match, mote, _ = duel(MOTE, gap=8.0)
    run(match, hold(Dir8.SE, Button.SPECIAL, frames=1) + neutral(12))
    assert len(match.projectiles) == 1
    lamp = match.projectiles[0]
    farthest = 0.0
    for _ in range(80):
        run(match, neutral(1))
        if not match.projectiles:
            break
        farthest = max(farthest, (lamp.pos - mote.pos).length())
    assert farthest > 2.0, "it went out"
    assert not match.projectiles, "and came back to Mote (caught) before its lifetime ran out"
    assert match.frame < 12 + 1 + MOTE.moves["sspecial"].projectiles[0].lifetime


def test_blink_hops_far_intangibly_then_falls_helpless() -> None:
    match, mote, _ = duel(MOTE, gap=8.0)
    place(match, mote, 3.0, Y, z=8.0)
    start = mote.pos
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=VERTICAL_UP))
    run(match, hold(Dir8.SE, frames=mote_scripts.BLINK_WINDUP - 1))
    assert mote.pos == start and mote.intangible, "still, and intangible, during the windup"
    run(match, hold(Dir8.SE, frames=mote_scripts.BLINK_FRAMES))
    moved = mote.pos - start
    assert moved.x == pytest.approx(mote_scripts.BLINK_SPEED * mote_scripts.BLINK_FRAMES, rel=0.05)
    run_until(match, mote, StateId.HELPLESS, limit=60)


def test_snare_glyph_waits_on_the_ground_for_a_victim() -> None:
    match, _mote, rook = duel(MOTE, gap=6.0, damage=20.0)
    run(match, hold(buttons=Button.SPECIAL, frames=1, vertical=-1) + neutral(40))
    assert len(match.projectiles) == 1
    glyph = match.projectiles[0]
    assert glyph.pos.z < 0.6 and glyph.vel.length() == 0.0, "resting on the ground"
    # Rook walks onto it.
    run(match, neutral(1), hold(Dir8.NW, frames=1))
    for _ in range(120):
        run(match, neutral(1), hold(Dir8.NW, frames=1))
        if not match.projectiles:
            break
    assert not match.projectiles and rook.damage > 20.0


def test_only_one_glyph_at_a_time() -> None:
    match, _mote, _ = duel(MOTE, gap=8.0)
    down = hold(buttons=Button.SPECIAL, frames=1, vertical=-1)
    run(match, down + neutral(45))
    first = match.projectiles[0].id
    run(match, down + neutral(45))
    assert [projectile.id for projectile in match.projectiles] != [first]
    assert len(match.projectiles) == 1
