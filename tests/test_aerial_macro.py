"""Scenario tests for jump-and-attack aerials and the short-hop macro (decision D-053).

Plan notes "04 - Movement and Physics" (jump table) and "08 - Controls and Input" (airborne
table). A person presses jump and attack within a tick or two of each other and keeps jump held
longer than a 3-frame jumpsquat, so without the macro nearly every keyboard hop is a full hop,
whose aerial sails over a standing opponent.
"""

import pytest

from helpers import make_match, place, run
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.events import HitEvent, JumpEvent, JumpKind
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import (
    VERTICAL_DOWN,
    VERTICAL_NONE,
    VERTICAL_UP,
    Button,
    Dir8,
    InputFrame,
)
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import ZERO2

ROOK_JUMPSQUAT = 3
ROOK_SHORT_HOP_APEX = 1.26
ROOK_FULL_HOP_APEX = 3.60
JUMP_HELD_TICKS = 6
"""How long a person typically holds jump: longer than any character's jumpsquat."""
CHARACTERS = ("rook", "bramble", "zephyr", "mote")
TOWARD, AWAY = Dir8.SE, Dir8.NW
"""P1 faces south-east, so these are stick toward and away from the facing."""


def setup(
    character: str = "rook", rules: MatchRules | None = None, gap: float = 5.0
) -> tuple[Match, Fighter]:
    """P1 in the middle of Training Grid facing SE; a copy of it ``gap`` units ahead."""
    built = rules or MatchRules(stocks=None)
    characters = [load_character(character)] * 2
    match = Match.create(load_stage("training_grid"), characters, seed=1, rules=built)
    p1, p2 = match.fighters
    place(match, p1, 3.0, 6.0, facing=TOWARD)
    place(match, p2, 3.0 + gap, 6.0, facing=AWAY)
    return match, p1


def hop(
    attack_tick: int | None,
    jump_ticks: int = JUMP_HELD_TICKS,
    buttons: int = Button.ATTACK,
    direction: Dir8 | None = None,
    vertical: int = VERTICAL_NONE,
    cstick: Dir8 | None = None,
    ticks: int = 120,
) -> list[InputFrame]:
    """Jump held for ``jump_ticks``; on ``attack_tick`` (1-based) ``buttons`` (or a right-stick
    flick) is pressed. Stick direction and modifier are held from then until jump is released,
    as a person holds them through the takeoff."""
    frames = []
    for tick in range(1, ticks + 1):
        held = Button.JUMP if tick <= jump_ticks else 0
        pressing = tick == attack_tick
        if pressing and cstick is None:
            held |= buttons
        holding = attack_tick is not None and attack_tick <= tick <= max(jump_ticks, attack_tick)
        frames.append(
            InputFrame(
                move=direction.world if holding and direction is not None else ZERO2,
                vertical=vertical if holding else VERTICAL_NONE,
                held=int(held),
                cstick=cstick.world if pressing and cstick is not None else None,
            )
        )
    return frames


def play(match: Match, fighter: Fighter, frames: list[InputFrame]) -> tuple[list[str], float]:
    """Run P1's frames; return the moves P1 started (in order) and its peak height."""
    moves: list[str] = []
    peak = fighter.pos.z
    for frame in frames:
        run(match, [frame])
        peak = max(peak, fighter.pos.z)
        if fighter.state is StateId.ATTACK and fighter.move_id and fighter.move_id not in moves:
            moves.append(fighter.move_id)
    return moves, peak


def damage_dealt(match: Match, frames: list[InputFrame]) -> float:
    """Run P1's frames and total the damage P1's hits dealt."""
    total = 0.0
    for frame in frames:
        run(match, [frame])
        total += sum(e.damage for e in match.events if isinstance(e, HitEvent) and e.attacker == 0)
    return total


# --- the macro ----------------------------------------------------------------------------


AERIALS = [
    (None, VERTICAL_NONE, "nair"),
    (TOWARD, VERTICAL_NONE, "fair"),
    (AWAY, VERTICAL_NONE, "bair"),
    (None, VERTICAL_UP, "uair"),
    (TOWARD, VERTICAL_DOWN, "dair"),
]


@pytest.mark.parametrize("buttons", [Button.ATTACK, Button.STRONG], ids=["attack", "strong"])
@pytest.mark.parametrize(("direction", "vertical", "move_id"), AERIALS)
def test_jump_held_with_attack_on_the_next_tick_is_a_short_hop_aerial(
    buttons: int, direction: Dir8 | None, vertical: int, move_id: str
) -> None:
    match, rook = setup()
    moves, peak = play(match, rook, hop(2, buttons=buttons, direction=direction, vertical=vertical))
    assert moves == [move_id]
    assert peak == pytest.approx(ROOK_SHORT_HOP_APEX)
    assert not rook.fast_falling, "the down modifier picked the move, not a fast fall"


@pytest.mark.parametrize(("cstick", "move_id"), [(TOWARD, "fair"), (AWAY, "bair")])
def test_a_right_stick_flick_with_the_jump_is_a_short_hop_aerial(
    cstick: Dir8, move_id: str
) -> None:
    match, rook = setup()
    moves, peak = play(match, rook, hop(2, cstick=cstick))
    assert moves == [move_id]
    assert peak == pytest.approx(ROOK_SHORT_HOP_APEX)


def test_the_aerial_starts_on_the_takeoff_tick_and_keeps_the_press_for_it() -> None:
    match, rook = setup()
    frames = hop(2)
    run(match, frames[:ROOK_JUMPSQUAT])
    assert rook.state is StateId.JUMP_SQUAT, "the press is only peeked during jumpsquat"
    run(match, frames[ROOK_JUMPSQUAT : ROOK_JUMPSQUAT + 1])
    assert not rook.grounded
    assert (rook.state, rook.move_id) == (StateId.ATTACK, "nair")
    jumps = [e for e in match.events if isinstance(e, JumpEvent)]
    assert [e.kind for e in jumps] == [JumpKind.SHORT_HOP]


def test_jump_alone_held_is_still_a_full_hop() -> None:
    match, rook = setup()
    moves, peak = play(match, rook, hop(None))
    assert moves == []
    assert peak == pytest.approx(ROOK_FULL_HOP_APEX)


def test_an_attack_after_takeoff_does_not_change_the_hop() -> None:
    match, rook = setup()
    moves, peak = play(match, rook, hop(ROOK_JUMPSQUAT + 2))
    assert moves == ["nair"]
    assert peak == pytest.approx(ROOK_FULL_HOP_APEX)


def test_with_the_rule_off_jump_held_stays_a_full_hop() -> None:
    match, rook = setup(rules=MatchRules(stocks=None, short_hop_macro=False))
    moves, peak = play(match, rook, hop(2))
    assert moves == ["nair"], "the buffered press still starts the aerial at takeoff"
    assert peak == pytest.approx(ROOK_FULL_HOP_APEX)


def test_tapping_jump_is_a_short_hop_with_or_without_the_rule() -> None:
    for macro in (True, False):
        match, rook = setup(rules=MatchRules(stocks=None, short_hop_macro=macro))
        assert play(match, rook, hop(None, jump_ticks=1))[1] == pytest.approx(ROOK_SHORT_HOP_APEX)


def test_the_macro_is_on_by_default() -> None:
    assert MatchRules().short_hop_macro
    assert make_match().rules.short_hop_macro


@pytest.mark.parametrize("macro", [True, False], ids=["macro", "no_macro"])
@pytest.mark.parametrize("character", CHARACTERS)
def test_jump_and_attack_pressed_together_start_the_aerial_at_takeoff(
    character: str, macro: bool
) -> None:
    """Regression: Bramble's 5-frame jumpsquat used to let a press made with the jump run out
    of the 6-frame buffer before the jump's first interruptible frame, so no aerial came out."""
    match, fighter = setup(character, MatchRules(stocks=None, short_hop_macro=macro))
    frames = hop(1, direction=TOWARD)
    jumpsquat = fighter.character.movement.jumpsquat
    run(match, frames[: jumpsquat + 1])
    assert not fighter.grounded
    assert (fighter.state, fighter.move_id) == (StateId.ATTACK, "fair")


# --- the original problem -----------------------------------------------------------------


@pytest.mark.parametrize("character", CHARACTERS)
def test_a_jump_and_attack_aerial_hits_a_standing_copy_only_with_the_macro(character: str) -> None:
    """Jump held 6 ticks, attack and the stick toward the opponent on tick 2, a standing copy
    1.4 units ahead: the short-hop aerial connects; the full-hop one sails over it."""
    frames = hop(2, direction=TOWARD)
    match, _ = setup(character, MatchRules(stocks=None), gap=1.4)
    assert damage_dealt(match, frames) > 0
    match, _ = setup(character, MatchRules(stocks=None, short_hop_macro=False), gap=1.4)
    assert damage_dealt(match, frames) == 0
