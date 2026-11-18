"""Mote's neutral air no longer chains into itself (decision D-073).

A Mote that short-hops neutral air at its victim whenever it can act used to keep a level 9
CPU in the swirl for 22 hits (Rook) to 50 (Bramble) from 0%. Now at most two in a row land.
"""

import pytest

from helpers import place
from isofightr.ai.controller import CpuController
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, InputFrame
from isofightr.sim.match import Match, MatchRules

ONE_NAIR = 5
"""Hits in one neutral air: four of the swirl, then the finisher."""
CAN_ACT = {
    StateId.IDLE,
    StateId.WALK,
    StateId.DASH,
    StateId.RUN,
    StateId.LAND,
    StateId.CROUCH,
}


def longest_chain(victim_id: str, percent: float, seed: int, idle: bool = False) -> tuple[int, int]:
    """(the victim's longest combo, the most hits one neutral air landed). The victim is a
    level 9 CPU, or stands still with ``idle``."""
    stage = load_stage("final_plateau")
    mote_def = load_character("mote")
    match = Match.create(
        stage, [mote_def, load_character(victim_id)], seed=seed, rules=MatchRules(stocks=None)
    )
    mote, victim = match.fighters
    place(match, mote, 7.0, 5.0)
    place(match, victim, 7.6, 5.0, damage=percent)
    cpu = CpuController(1, 9, seed, stage)
    longest = most_in_one = in_this = 0
    pressed = False
    for _ in range(600):
        toward = victim.pos.xy - mote.pos.xy
        aim = toward.normalized() if toward.length() > 0.2 else toward
        frame = InputFrame(move=aim if not mote.grounded else aim * 0.0)
        if mote.grounded and mote.state in CAN_ACT and not pressed:
            # No stick on the press: the short-hop macro reads it at takeoff (a forward air).
            # Pressed every other tick, so a press lost to landing lag is made again.
            frame = InputFrame(held=int(Button.JUMP) | int(Button.ATTACK))
            pressed = True
            if mote.state is not StateId.LAND:
                in_this = 0
        else:
            pressed = False
        match.tick([frame, NEUTRAL_INPUT if idle else cpu.think(match)])
        in_this += sum(1 for e in match.events if isinstance(e, HitEvent) and e.attacker == 0)
        most_in_one = max(most_in_one, in_this)
        longest = max(longest, victim.combo_hits)
    return longest, most_in_one


@pytest.mark.parametrize("victim_id", ["rook", "bramble", "zephyr"])
def test_mote_neutral_air_chains_at_most_twice_from_low_percent(victim_id: str) -> None:
    for percent in (0.0, 20.0, 40.0):
        for seed in (1, 2):
            longest, _most = longest_chain(victim_id, percent, seed)
            assert longest <= 2 * ONE_NAIR, (victim_id, percent, seed, longest)


def test_one_mote_neutral_air_still_connects_all_its_hits() -> None:
    _longest, most = longest_chain("rook", 0.0, seed=1, idle=True)
    assert most >= ONE_NAIR
