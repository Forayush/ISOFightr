"""Tests for the training tools the sim offers, the right-stick smash input and ``--training``.

Plan notes "13 - Game Modes UI and Flow" (training mode) and "08 - Controls and Input"
(the right stick as a smash stick).
"""

import shutil
from pathlib import Path

import pytest

from helpers import hold, make_match, neutral, place, run
from isofightr.__main__ import build_parser, main, stage_id
from isofightr.config import DEFAULT_STAGE_ID, TRAINING_STAGE_ID
from isofightr.data.character_loader import load_character
from isofightr.data.paths import CHARACTERS_DIR
from isofightr.data.validation import DataError
from isofightr.input.gamepad import (
    MODIFIER_BUMPERS,
    RIGHT_STICK_MODIFIERS,
    PadState,
    gamepad_frame,
    merge_frames,
    smash_stick,
)
from isofightr.sim.combat.constants import MAX_DAMAGE
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, VERTICAL_UP, Button, Dir8, InputFrame

# --- Match.set_damage ---------------------------------------------------------------------


def test_set_damage_sets_and_clamps() -> None:
    match = make_match()
    match.set_damage(1, 85.0)
    assert match.fighters[1].damage == 85.0 and match.fighters[0].damage == 0.0
    match.set_damage(1, -20.0)
    assert match.fighters[1].damage == 0.0
    match.set_damage(1, 5000.0)
    assert match.fighters[1].damage == MAX_DAMAGE


def test_set_damage_changes_the_state_hash() -> None:
    match = make_match()
    before = match.state_hash()
    match.set_damage(0, 40.0)
    assert match.state_hash() != before


# --- Match.reload_characters --------------------------------------------------------------


@pytest.fixture
def characters_dir(tmp_path: Path) -> Path:
    """A private copy of the shipped character data that a test may edit."""
    target = tmp_path / "characters"
    shutil.copytree(CHARACTERS_DIR, target)
    return target


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_reloaded_move_data_takes_effect_in_the_running_match(characters_dir: Path) -> None:
    match = make_match(stocks=None)
    attacker, target = match.fighters
    place(match, attacker, 4.0, 6.0, facing=Dir8.SE)
    place(match, target, 5.0, 6.0)
    run(match, hold(buttons=Button.ATTACK, frames=1) + neutral(40))
    assert target.damage == pytest.approx(2.625)

    edit(characters_dir / "rook" / "moves" / "jab1.toml", "damage = 2.5", "damage = 10.0")
    reloaded = load_character("rook", characters_dir)
    match.reload_characters([reloaded, reloaded])
    assert attacker.character is reloaded
    match.set_damage(1, 0.0)
    attacker.stale_queue.clear()
    place(match, target, 5.0, 6.0)
    run(match, hold(buttons=Button.ATTACK, frames=1) + neutral(40))
    assert target.damage == pytest.approx(10.5)


def test_reloading_stats_changes_movement(characters_dir: Path) -> None:
    edit(characters_dir / "rook" / "fighter.toml", "walk_speed = 0.060", "walk_speed = 0.030")
    match = make_match()
    slow = load_character("rook", characters_dir)
    match.reload_characters([slow, load_character("rook")])
    assert match.fighters[0].character.movement.walk_speed == 0.030
    assert match.fighters[1].character.movement.walk_speed == 0.060


def test_a_fighter_using_a_move_that_disappeared_drops_out_of_it(characters_dir: Path) -> None:
    match = make_match()
    attacker, other = match.fighters
    place(match, other, 4.0, 3.0, z=5.0)
    run(match, hold(buttons=Button.ATTACK, frames=1), hold(buttons=Button.ATTACK, frames=1))
    assert attacker.move_id == "jab1" and other.move_id == "nair"
    assert attacker.state is other.state is StateId.ATTACK

    moves = characters_dir / "rook" / "moves"
    for old, new in (("jab1", "poke1"), ("nair", "spin")):
        (moves / f"{old}.toml").rename(moves / f"{new}.toml")
        edit(moves / f"{new}.toml", f'id = "{old}"', f'id = "{new}"')
    edit(characters_dir / "rook" / "fighter.toml", '"jab1"', '"poke1"')
    edit(characters_dir / "rook" / "fighter.toml", 'nair = "nair"', 'nair = "spin"')
    reloaded = load_character("rook", characters_dir)
    match.reload_characters([reloaded, reloaded])
    assert attacker.state is StateId.IDLE and other.state is StateId.FALL
    run(match, neutral(30))  # and the match carries on


def test_a_broken_file_fails_to_load_and_leaves_the_match_alone(characters_dir: Path) -> None:
    match = make_match()
    before = match.fighters[0].character
    edit(characters_dir / "rook" / "moves" / "fsmash.toml", "kbg = 105", "kgb = 105")
    with pytest.raises(DataError, match=r"fsmash\.toml.*unknown key\(s\) 'kgb'"):
        load_character("rook", characters_dir)
    assert match.fighters[0].character is before


def test_reload_needs_one_character_per_fighter() -> None:
    match = make_match()
    with pytest.raises(ValueError, match="expected 2 characters, got 1"):
        match.reload_characters([load_character("rook")])


# --- right-stick smash --------------------------------------------------------------------


def test_default_preset_sideways_right_stick_is_a_smash_direction() -> None:
    right = gamepad_frame(PadState(right_x=1.0))
    assert right.cstick is not None and right.vertical == 0
    assert (right.cstick.x, right.cstick.y) == pytest.approx((Dir8.E.world.x, Dir8.E.world.y))
    left = gamepad_frame(PadState(right_x=-0.8, right_y=0.3))
    assert left.cstick is not None and left.cstick.length() == pytest.approx(1.0)
    assert left.cstick.dot(Dir8.W.world) > 0.9


def test_default_preset_vertical_right_stick_is_only_the_modifier() -> None:
    up = gamepad_frame(PadState(right_y=1.0))
    assert up.vertical == VERTICAL_UP and up.cstick is None
    assert gamepad_frame(PadState(right_x=0.3)).cstick is None, "below the threshold"
    assert gamepad_frame(PadState()).cstick is None


def test_bumper_preset_right_stick_smashes_in_every_direction() -> None:
    up = smash_stick(PadState(right_y=1.0), MODIFIER_BUMPERS)
    assert up is not None
    assert (up.x, up.y) == pytest.approx((Dir8.N.world.x, Dir8.N.world.y))
    assert smash_stick(PadState(right_y=1.0), RIGHT_STICK_MODIFIERS) is None
    assert gamepad_frame(PadState(right_y=1.0), MODIFIER_BUMPERS).vertical == 0


def test_merging_keeps_the_smash_stick() -> None:
    pad = gamepad_frame(PadState(right_x=1.0))
    keys = InputFrame(held=int(Button.JUMP))
    assert merge_frames(keys, pad).cstick == pad.cstick
    assert merge_frames(pad, keys).cstick == pad.cstick
    assert merge_frames(keys, NEUTRAL_INPUT).cstick is None


def test_a_right_stick_flick_smashes_once_however_long_it_is_held() -> None:
    match = make_match()
    fighter = match.fighters[0]
    flick = gamepad_frame(PadState(right_x=-1.0))
    run(match, [flick] * 80)
    assert fighter.state is StateId.IDLE and fighter.move_id == "fsmash"
    assert fighter.charge_frames == 0, "the right stick never charges"
    run(match, [*neutral(1), flick])
    assert fighter.state is StateId.ATTACK and fighter.state_frame == 1


# --- --training ---------------------------------------------------------------------------


def test_training_flag_and_its_default_stage() -> None:
    parser = build_parser()
    assert stage_id(parser.parse_args([])) == DEFAULT_STAGE_ID == "sky_ruins"
    training = parser.parse_args(["--training"])
    assert training.training is True
    assert stage_id(training) == TRAINING_STAGE_ID == "training_grid"
    assert stage_id(parser.parse_args(["--training", "--stage", "sky_ruins"])) == "sky_ruins"


@pytest.mark.parametrize("other", [["--headless", "--frames", "10"], ["--test-pattern"]])
def test_training_needs_the_game_window(
    other: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["--training", *other])
    assert "--training needs the normal game window" in capsys.readouterr().err
