"""Unit tests for the F10 input display formatter (plan note 13, decision D-053)."""

from helpers import make_match, run
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import VERTICAL_DOWN, Button, Dir8, InputFrame
from isofightr.ui.input_display import input_line, input_lines, stick_text


def test_a_fighter_with_no_input_shows_dashes() -> None:
    match = make_match()
    assert input_line(match.fighters[0]) == "P1 stick - mod - c - held - buf - > idle f1 move -"


def test_the_line_shows_what_the_sim_received_this_tick() -> None:
    match = make_match()
    frame = InputFrame(
        move=Dir8.SE.world, vertical=VERTICAL_DOWN, held=int(Button.JUMP | Button.ATTACK)
    )
    run(match, [frame])
    line = input_line(match.fighters[0])
    assert line.startswith("P1 stick SE 1.00 mod DOWN c - held JUMP ATK buf ")
    assert "JUMP0" not in line, "the jump press was used to start the jumpsquat"
    assert "ATK0" in line and "DOWN0" in line, "unused presses stay buffered, with their age"
    assert line.endswith("> jump_squat f1 move -")


def test_an_attack_shows_its_move_id() -> None:
    match = make_match()
    run(match, [InputFrame(held=int(Button.ATTACK))])
    fighter = match.fighters[0]
    assert fighter.state is StateId.ATTACK
    assert input_line(fighter).endswith("> attack f1 move jab1")


def test_the_right_stick_and_partial_tilts() -> None:
    assert stick_text(None) == "-"
    assert stick_text(Dir8.NW.world * 0.1) == "-", "inside the neutral zone"
    assert stick_text(Dir8.NW.world * 0.5) == "NW 0.50"
    match = make_match()
    run(match, [InputFrame(cstick=Dir8.E.world)])
    assert " c E 1.00 " in input_line(match.fighters[0])


def test_one_line_per_player_clipped_to_the_width() -> None:
    match = make_match(fighters=("rook",) * 4)
    lines = input_lines(match.fighters, 20)
    assert [line[:2] for line in lines] == ["P1", "P2", "P3", "P4"]
    assert all(len(line) <= 20 for line in lines)
