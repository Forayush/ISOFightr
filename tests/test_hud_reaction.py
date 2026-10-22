"""The player cards' two-stage reaction to a hit (decision D-068, M17 group 4): the portrait
flashes and the number jitters through the freeze, then at the launch the number punches and,
for heavy and critical hits, the frame takes the attacker's colour. Pure: no window; the
cards drawing it are tested in ``tests/test_battle_gl.py``.
"""

import pytest

from helpers import place
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render.effects import BattleEffects
from isofightr.render.hit_splash import HEAVY
from isofightr.settings import HIT_EFFECTS_FULL, HIT_EFFECTS_MINIMAL, HIT_EFFECTS_OFF
from isofightr.sim.events import HazardHitEvent, HitEvent, LaunchEvent
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.states.interrupts import start_move
from isofightr.ui import hud_reaction as hr
from isofightr.ui.hud_reaction import HudReactions


def test_a_contact_flashes_the_portrait_and_jitters_the_number_through_the_freeze() -> None:
    reactions = HudReactions()
    reactions.contact(1, hitlag=6)
    flashes, offsets = [], []
    for _ in range(9):
        flashes.append(reactions.portrait_flash(1))
        offsets.append(reactions.offset(1))
        reactions.tick()
    assert flashes == [True] * hr.PORTRAIT_FLASH_TICKS + [False] * (9 - hr.PORTRAIT_FLASH_TICKS)
    assert offsets[:6] == [(1, 0), (-1, 0)] * 3, "a pixel either way while frozen"
    assert offsets[6:] == [(0, 0)] * 3, "still once the freeze is over"
    assert not reactions.portrait_flash(0) and reactions.offset(0) == (0, 0)


@pytest.mark.parametrize("tier", range(4))
def test_a_launch_punches_the_number_by_its_tier(tier: int) -> None:
    reactions = HudReactions()
    reactions.contact(1, hitlag=8)
    reactions.launch(1, tier, attacker=0)
    big, shakes, frames = [], [], []
    for _ in range(16):
        big.append(reactions.punched(1))
        shakes.append(max(abs(part) for part in reactions.offset(1)))
        frames.append(reactions.frame_attacker(1))
        reactions.tick()
    assert big == [True] * hr.PUNCH_BIG_TICKS[tier] + [False] * (16 - hr.PUNCH_BIG_TICKS[tier])
    assert shakes[0] == hr.PUNCH_PIXELS[tier], "the jitter stops; the shake starts at its size"
    assert shakes == sorted(shakes, reverse=True), "it fades"
    assert all(shake == 0 for shake in shakes[hr.PUNCH_TICKS[tier] :])
    shown = [frame for frame in frames if frame is not None]
    if tier < HEAVY:
        assert shown == [], "light and medium hits keep the card's own frame"
    else:
        assert set(shown) == {0}, "a heavy or critical launch shows the attacker's colour"
        assert all(frame is None for frame in frames[hr.FRAME_FLASH_TICKS[tier] :])


def test_a_critical_frame_blinks_between_the_attackers_colour_and_white() -> None:
    reactions = HudReactions()
    reactions.launch(2, hr.CRITICAL, attacker=3)
    seen = []
    for _ in range(hr.FRAME_FLASH_TICKS[hr.CRITICAL] + 2):
        seen.append((reactions.frame_attacker(2), reactions.frame_white(2)))
        reactions.tick()
    blink = hr.FRAME_BLINK_TICKS
    assert seen[:blink] == [(3, False)] * blink
    assert seen[blink : 2 * blink] == [(None, True)] * blink
    assert seen[-2:] == [(None, False)] * 2


def test_a_hazards_launch_punches_but_has_no_attacker_colour() -> None:
    reactions = HudReactions()
    reactions.launch(0, hr.CRITICAL, attacker=None)
    assert reactions.punched(0) and reactions.frame_attacker(0) is None
    assert not reactions.frame_white(0)


def test_shake_off_keeps_the_number_still() -> None:
    reactions = HudReactions()
    reactions.contact(0, hitlag=4)
    assert reactions.offset(0, strength=0.0) == (0, 0)
    reactions.launch(0, hr.CRITICAL, attacker=1)
    assert reactions.offset(0, strength=0.0) == (0, 0)
    assert reactions.punched(0), "the punch is a size, not a movement"
    half = max(abs(part) for part in reactions.offset(0, strength=0.5))
    assert 0 < half < hr.PUNCH_PIXELS[hr.CRITICAL]


# --- from the real sim ---------------------------------------------------------------------


def fsmash(hit_effects: str, percent: float = 60.0) -> tuple[BattleEffects, list[dict], int]:  # type: ignore[type-arg]
    """Rook forward-smashes Rook on Training Grid, the battle's effects fed as the battle
    feeds them; per tick from the hit, what the victim's card reaction is doing."""
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, target = match.fighters
    spot = match.stage.respawn
    place(match, target, spot.x, spot.y, facing=Dir8.W, damage=percent)
    behind = spot - Dir8.E.world * 0.9
    place(match, striker, behind.x, behind.y, facing=Dir8.E)
    effects = BattleEffects(hit_effects=hit_effects)
    start_move(match, striker, "fsmash")
    seen: list[dict] = []  # type: ignore[type-arg]
    hitlag = -1
    for _ in range(90):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        effects.tick()
        effects.consume(match.events)
        effects.observe(match.fighters, match.stage, match.frame)
        if hitlag < 0 and any(isinstance(event, HitEvent) for event in match.events):
            hitlag = target.hitlag
        if hitlag >= 0:
            reactions = effects.reactions
            seen.append(
                {
                    "frozen": target.hitlag > 0,
                    "launched": any(isinstance(e, LaunchEvent) for e in match.events),
                    "portrait": reactions.portrait_flash(1),
                    "offset": reactions.offset(1),
                    "punched": reactions.punched(1),
                    "frame": reactions.frame_attacker(1),
                }
            )
    assert hitlag > 0
    return effects, seen, hitlag


def test_a_real_hit_reacts_at_contact_and_again_at_its_launch() -> None:
    _, seen, hitlag = fsmash(HIT_EFFECTS_FULL)
    assert seen[0]["portrait"] and not seen[hr.PORTRAIT_FLASH_TICKS]["portrait"]
    frozen = [row for row in seen if row["frozen"]]
    assert len(frozen) == hitlag and all(row["offset"][0] for row in frozen)
    assert not any(row["punched"] or row["frame"] is not None for row in frozen)
    launch = next(index for index, row in enumerate(seen) if row["launched"])
    assert launch == hitlag, "the launch comes on the tick the freeze ends"
    big = [row["punched"] for row in seen[launch:]]
    assert big[: hr.PUNCH_BIG_TICKS[HEAVY]] == [True] * hr.PUNCH_BIG_TICKS[HEAVY]
    frames = [row["frame"] for row in seen[launch:]]
    assert frames[: hr.FRAME_FLASH_TICKS[HEAVY]] == [0] * hr.FRAME_FLASH_TICKS[HEAVY], (
        "60%: a heavy hit, so the frame takes Rook's (player 1's) colour"
    )
    assert seen[-1] == {
        "frozen": False,
        "launched": False,
        "portrait": False,
        "offset": (0, 0),
        "punched": False,
        "frame": None,
    }


def test_minimal_reacts_too() -> None:
    _, seen, _ = fsmash(HIT_EFFECTS_MINIMAL)
    assert seen[0]["portrait"] and any(row["punched"] for row in seen)


def test_with_hit_effects_off_the_cards_do_not_react() -> None:
    effects, seen, _ = fsmash(HIT_EFFECTS_OFF)
    assert effects.reactions.cards == {}
    assert not any(row["portrait"] or row["punched"] or row["frame"] is not None for row in seen)


def test_a_blocked_hazard_does_not_react_and_a_hazard_hit_has_no_attacker() -> None:
    effects = BattleEffects(hit_effects=HIT_EFFECTS_FULL)
    hit = HazardHitEvent(0, "geyser", 1, 12.0, 120.0, Vec3(1, 1, 1), Effect.FIRE, 9, True)
    effects.consume([hit])
    assert effects.reactions.cards == {}, "a blocked one is not a hit on the card"
    effects.consume(
        [HazardHitEvent(0, "geyser", 1, 12.0, 120.0, Vec3(1, 1, 1), Effect.FIRE, 9, False)]
    )
    assert effects.reactions.portrait_flash(1)
    effects.consume([LaunchEvent(1, Vec3(1, 1, 1), Vec3(1.0, 0.0, 0.5).normalized(), 120.0)])
    assert effects.reactions.punched(1) and effects.reactions.frame_attacker(1) is None
