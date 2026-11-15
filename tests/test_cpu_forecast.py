"""Tests for the CPU's forecast (plan note "15 - CPU AI", decision D-071): what a hit leads
to, held to the real sim. Flights are compared frame by frame, KO percents with
``sim/kill_calc.py``, and advantage on hit with ``sim/combo_scan.py``.
"""

import pytest

from isofightr.ai import forecast
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim import combo_scan
from isofightr.sim.combat import constants as combat
from isofightr.sim.combat.knockback import hitstun_frames
from isofightr.sim.combat.shield import shieldstun_frames
from isofightr.sim.events import HitEvent, KoEvent, LaunchEvent
from isofightr.sim.fighter import Fighter, Launch, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.kill_calc import DEFAULT_GAP, kill_percent
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.move_def import HitboxDef
from isofightr.sim.states.interrupts import start_move

SKY = load_stage("sky_ruins")


def struck(
    attacker: str, target: str, move: str, percent: float
) -> tuple[Match, Fighter, Fighter, HitEvent]:
    """Set up as ``kill_calc`` does and tick until the move hits: the victim is then frozen
    in hitlag with its launch pending."""
    match = Match.create(
        SKY, [load_character(attacker), load_character(target)], rules=MatchRules(stocks=None)
    )
    striker, victim = match.fighters
    spot = SKY.respawn
    top = SKY.surface_top(spot.x, spot.y)
    assert top is not None
    victim.pos = Vec3(spot.x, spot.y, top)
    victim.damage = percent
    behind = spot - Dir8.SE.world * DEFAULT_GAP
    striker.pos = Vec3(behind.x, behind.y, top)
    striker.facing = Dir8.SE
    start_move(match, striker, move)
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        for event in match.events:
            if isinstance(event, HitEvent) and event.target == 1:
                return match, striker, victim, event
    raise AssertionError(f"{attacker}'s {move} never hit")


def flown_in_the_sim(match: Match, victim: Fighter, frames: int) -> list[Vec3]:
    """Tick until the launch, then return where the victim is after each following frame
    while it is stunned and still there."""
    for _ in range(40):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if any(isinstance(event, LaunchEvent) for event in match.events):
            break
    path = []
    for _ in range(frames):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if victim.hitstun <= 0 or any(isinstance(e, KoEvent) for e in match.events):
            break
        path.append(victim.pos)
    return path


@pytest.mark.parametrize(
    ("attacker", "target", "move", "percent", "tolerance"),
    [
        ("rook", "rook", "fsmash", 100.0, 0.02),
        ("rook", "rook", "usmash", 60.0, 0.02),
        ("rook", "rook", "dtilt", 20.0, 0.02),
        ("rook", "rook", "jab1", 10.0, 0.02),
        ("bramble", "zephyr", "dsmash", 80.0, 0.02),
        ("zephyr", "bramble", "utilt", 30.0, 0.02),
        ("mote", "rook", "fsmash", 120.0, 0.02),
        # A low launch lands and slides on while still stunned: the forecast stops where it
        # lands, so it is a tenth of a unit short by the end.
        ("rook", "rook", "ftilt", 40.0, 0.15),
    ],
)
def test_a_flight_is_where_the_sim_puts_the_victim_frame_by_frame(
    attacker: str, target: str, move: str, percent: float, tolerance: float
) -> None:
    match, _striker, victim, _event = struck(attacker, target, move, percent)
    launch = victim.launch
    assert launch is not None
    before = match.state_hash()
    flown = forecast.flight(match.stage, launch, victim.pos, victim.grounded, victim.character)
    assert match.state_hash() == before, "it only reads"
    assert flown.hitstun == hitstun_frames(launch.knockback)
    real = flown_in_the_sim(match, victim, 60)
    assert len(real) >= 3
    for index, position in enumerate(real):
        assert (position - flown.at(index + 1)).length() <= tolerance, f"frame {index + 1}"


@pytest.mark.parametrize(
    ("attacker", "move"),
    [("rook", "fsmash"), ("rook", "usmash"), ("bramble", "dsmash"), ("zephyr", "usmash")],
)
def test_a_launch_kos_exactly_where_the_sim_says(attacker: str, move: str) -> None:
    percent = kill_percent(SKY, load_character(attacker), load_character("rook"), move)
    assert percent is not None
    for at, expected in ((percent, True), (percent - 1, False)):
        match, _striker, victim, _event = struck(attacker, "rook", move, float(at))
        assert victim.launch is not None
        killed = forecast.kills(
            match.stage, victim.launch, victim.pos, victim.grounded, victim.character
        )
        assert killed is expected, f"{move} at {at}%"


def hitting_box(striker: Fighter, event: HitEvent) -> HitboxDef:
    """The hitbox of the striker's move that dealt the hit (by its damage)."""
    move = striker.character.moves[event.move_id]
    boxes = [box for window in move.windows for box in window.hitboxes]
    return min(boxes, key=lambda box: abs(box.damage * forecast.FRESH - event.damage))


@pytest.mark.parametrize(
    ("attacker", "move"),
    [(who, move) for who in list_character_ids() for move in ("fsmash", "usmash", "dsmash")],
)
def test_the_kill_percent_of_a_hitbox_is_the_sims_within_five(attacker: str, move: str) -> None:
    """From the hitbox, the facing and the place alone: no match, no rollout."""
    target = load_character("rook")
    real = kill_percent(SKY, load_character(attacker), target, move)
    assert real is not None
    _match, striker, victim, event = struck(attacker, "rook", move, 50.0)
    box = hitting_box(striker, event)
    heading = forecast.hit_heading(box, striker.facing.world, event.position, victim.pos)
    guess = forecast.kill_percent(SKY, box, heading, victim.pos, target)
    assert guess is not None and abs(guess - real) <= 5, (guess, real)


def test_a_move_that_never_kos_has_no_kill_percent() -> None:
    _match, striker, victim, event = struck("rook", "rook", "dtilt", 50.0)
    box = hitting_box(striker, event)
    heading = forecast.hit_heading(box, striker.facing.world, event.position, victim.pos)
    assert forecast.kill_percent(SKY, box, heading, victim.pos, victim.character) is None
    weak = Launch(combat.TUMBLE_KB - 1.0, Vec2(1.0, 0.0), 90.0, False)
    assert not forecast.kills(SKY, weak, victim.pos, True, victim.character)


def test_the_queued_launch_is_the_one_the_sim_queues() -> None:
    for attacker, move, percent in (("rook", "fsmash", 90.0), ("mote", "dtilt", 30.0)):
        _match, striker, victim, event = struck(attacker, "rook", move, percent)
        real = victim.launch
        assert real is not None
        box = hitting_box(striker, event)
        heading = forecast.hit_heading(box, striker.facing.world, event.position, victim.pos)
        guess = forecast.hit_launch(
            box, event.damage, percent, victim.character.weight, True, heading
        )
        assert guess.knockback == pytest.approx(real.knockback)
        assert guess.elevation == pytest.approx(real.elevation)
        assert guess.tumble is real.tumble
        assert (guess.heading - real.heading).length() < 1e-9
        assert forecast.hit_knockback(
            box, event.damage, percent, victim.character.weight
        ) == pytest.approx(event.knockback)


@pytest.mark.parametrize("character_id", list_character_ids())
def test_advantage_on_hit_is_combo_scans(character_id: str) -> None:
    character = load_character(character_id)
    rows = combo_scan.scan(character, character)
    assert rows
    for row in rows:
        move = character.moves[row.move_id]
        window = move.windows[0]
        box = min(window.hitboxes, key=lambda hitbox: hitbox.id)
        damage = box.damage * forecast.FRESH
        remaining = move.faf - window.frames.first
        for percent, expected in zip(combo_scan.DEFAULT_PERCENTS, row.advantage, strict=True):
            kb = forecast.hit_knockback(box, damage, float(percent), character.weight)
            assert forecast.advantage_on_hit(kb, remaining) == expected, row.move_id


def test_advantage_on_shield_is_shieldstun_against_what_is_left_of_the_move() -> None:
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, blocker = match.fighters
    striker.pos, striker.facing = Vec3(5.0, 6.0, 0.0), Dir8.SE
    ahead = Dir8.SE.world * DEFAULT_GAP
    blocker.pos = Vec3(5.0 + ahead.x, 6.0 + ahead.y, 0.0)
    shield = InputFrame(held=int(Button.SHIELD))
    for _ in range(5):
        match.tick([NEUTRAL_INPUT, shield])
    start_move(match, striker, "fsmash")
    stunned = 0
    for _ in range(90):
        match.tick([NEUTRAL_INPUT, shield])
        stunned += int(blocker.state is StateId.SHIELD_STUN and blocker.hitlag == 0)
    damage = 14.0 * forecast.FRESH
    assert abs(stunned - shieldstun_frames(damage)) <= 1
    assert forecast.advantage_on_shield(damage, 30) == shieldstun_frames(damage) - 30
    assert forecast.advantage_on_shield(damage, 0, projectile=True) < shieldstun_frames(damage)


def test_di_bends_a_flight_and_can_save_a_stock() -> None:
    match, _striker, victim, _event = struck("rook", "rook", "fsmash", 100.0)
    launch = victim.launch
    assert launch is not None
    flights = forecast.di_flights(match.stage, launch, victim.pos, True, victim.character)
    assert len(flights) == len(forecast.DI_CHOICES)
    plain = flights[0][2]
    assert all((flown.at(30) - plain.at(30)).length() > 0.05 for _, _, flown in flights[1:])
    strong = Launch(400.0, launch.heading, 40.0, True)
    assert forecast.kills_through_di(match.stage, strong, victim.pos, True, victim.character)
    percent = kill_percent(SKY, load_character("rook"), load_character("rook"), "usmash")
    assert percent is not None
    match, _striker, victim, _event = struck("rook", "rook", "usmash", float(percent))
    edge = victim.launch
    assert edge is not None
    assert forecast.kills(match.stage, edge, victim.pos, True, victim.character)
    assert not forecast.kills_through_di(match.stage, edge, victim.pos, True, victim.character)


def test_coast_carries_on_a_flight_already_under_way() -> None:
    match, _striker, victim, _event = struck("rook", "rook", "usmash", 60.0)
    for _ in range(40):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if any(isinstance(event, LaunchEvent) for event in match.events):
            break
    for _ in range(10):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
    assert victim.hitstun > 20
    flown = forecast.coast(
        match.stage,
        victim.pos,
        victim.kb_vel,
        victim.vel.z,
        victim.hitstun,
        victim.grounded,
        victim.character,
    )
    for frame in range(1, 21):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        assert (victim.pos - flown.at(frame)).length() <= 0.02, frame
