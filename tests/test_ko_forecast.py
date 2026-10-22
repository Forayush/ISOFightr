"""Tests for the KO forecast (decision D-068, M17 group 1): the hit splash's critical tier is
for hits that KO, forecast the moment they land. Held to the real sim's KO percents
(``tools/kill_calc.py``): the forecast must say KO at the percent the sim first KOs at, and
not a point below.
"""

import pytest

from helpers import place
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render.ko_forecast import FORECAST_MIN_KNOCKBACK, will_ko
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import Launch
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.kill_calc import DEFAULT_GAP, kill_percent
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.states.interrupts import start_move


def forecast_at(attacker: str, move: str, percent: float) -> bool:
    """Set up as ``kill_calc`` does (Rook from the centre of Sky Ruins, facing SE) and
    forecast the hit on the tick it lands, before the match changes anything."""
    stage = load_stage("sky_ruins")
    match = Match.create(
        stage, [load_character(attacker), load_character("rook")], rules=MatchRules(stocks=None)
    )
    striker, victim = match.fighters
    spot = stage.respawn
    top = stage.surface_top(spot.x, spot.y)
    assert top is not None
    victim.pos = Vec3(spot.x, spot.y, top)
    victim.damage = percent
    behind = spot - Dir8.SE.world * DEFAULT_GAP
    striker.pos = Vec3(behind.x, behind.y, top)
    striker.facing = Dir8.SE
    start_move(match, striker, move)
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if any(isinstance(event, HitEvent) and event.target == 1 for event in match.events):
            before = match.state_hash()
            kills = will_ko(match.stage, victim)
            assert match.state_hash() == before, "it only reads"
            return kills
    raise AssertionError(f"{attacker}'s {move} never hit")


@pytest.mark.parametrize(
    ("attacker", "move"),
    [("rook", "fsmash"), ("rook", "usmash"), ("bramble", "dsmash"), ("mote", "fair")],
)
def test_the_forecast_kos_exactly_where_the_sim_does(attacker: str, move: str) -> None:
    stage = load_stage("sky_ruins")
    percent = kill_percent(stage, load_character(attacker), load_character("rook"), move)
    assert percent is not None
    assert forecast_at(attacker, move, float(percent))
    assert not forecast_at(attacker, move, float(percent - 1))


def test_a_move_that_never_kos_is_never_forecast_to() -> None:
    assert not forecast_at("rook", "dtilt", 300.0)


def test_no_launch_or_a_weak_one_is_no_ko() -> None:
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    fighter = match.fighters[1]
    place(match, fighter, 5.0, 6.0)
    assert not will_ko(match.stage, fighter)
    up = Launch(FORECAST_MIN_KNOCKBACK - 1.0, Vec2(1.0, 0.0), 90.0, False)
    fighter.launch = up
    assert not will_ko(match.stage, fighter), "under tumble strength: never flown"
    fighter.launch = Launch(400.0, Vec2(1.0, 0.0), 90.0, True)
    assert will_ko(match.stage, fighter), "straight up, hard"
    place(match, fighter, 5.0, 6.0, z=match.stage.surface_top(5.0, 6.0) + 2.0)
    fighter.launch = Launch(400.0, Vec2(1.0, 0.0), -60.0, True)
    assert not fighter.grounded
    assert not will_ko(match.stage, fighter), "spiked into solid ground: it lands"
