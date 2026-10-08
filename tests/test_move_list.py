"""Unit tests for the pause menu's move list builder (plan note 13, decision D-053)."""

from dataclasses import fields

import pytest

from isofightr.data.character_loader import load_character
from isofightr.input.gamepad import MODIFIER_BUMPERS, RIGHT_STICK_MODIFIERS
from isofightr.settings import KEYBOARD_ARROWS, KEYBOARD_SOLO, Settings
from isofightr.sim.character_def import MoveSet
from isofightr.ui.move_list import (
    ACTIONS,
    UNBOUND,
    MoveSection,
    build_move_list,
    gamepad_labels,
    keyboard_labels,
    page_columns,
)

CHARACTERS = ("rook", "bramble", "zephyr", "mote")
COLUMN_WIDTH = 48
"""The battle scene's column capacity."""
SOLO = keyboard_labels(Settings().keys[KEYBOARD_SOLO])


def section(sections: tuple[MoveSection, ...], title: str) -> MoveSection:
    return next(found for found in sections if found.title == title)


def inputs_of(sections: tuple[MoveSection, ...], slot: str) -> str:
    return next(row.inputs for found in sections for row in found.rows if row.slot == slot)


@pytest.mark.parametrize("character", CHARACTERS)
def test_every_moveset_slot_appears_exactly_once(character: str) -> None:
    moveset = load_character(character).moveset
    sections = build_move_list(moveset, SOLO, short_hop_macro=True)
    slots = [row.slot for found in sections for row in found.rows if row.slot]
    assert sorted(slots) == sorted(field.name for field in fields(MoveSet))


@pytest.mark.parametrize("character", CHARACTERS)
def test_every_character_shows_five_aerials_and_the_macro_line_when_it_is_on(
    character: str,
) -> None:
    moveset = load_character(character).moveset
    on = section(build_move_list(moveset, SOLO, short_hop_macro=True), "AIR")
    off = section(build_move_list(moveset, SOLO, short_hop_macro=False), "AIR")
    aerials = ["nair", "fair", "bair", "uair", "dair"]
    assert [row.slot for row in off.rows] == aerials
    assert [row.slot for row in on.rows] == [*aerials, ""]
    assert on.rows[-1].inputs == "SPACE + J together"


def test_aerials_use_the_default_keyboard_keys() -> None:
    sections = build_move_list(load_character("rook").moveset, SOLO, short_hop_macro=True)
    assert inputs_of(sections, "nair") == "J"
    assert inputs_of(sections, "fair") == "J + WASD toward facing"
    assert inputs_of(sections, "bair") == "J + WASD away"
    assert inputs_of(sections, "uair") == "I + J"
    assert inputs_of(sections, "dair") == ", + J"
    assert inputs_of(sections, "jab") == "J (again to combo)", "Rook has a three-hit jab"


def test_rebinding_a_key_changes_its_label() -> None:
    rebound = Settings().with_key(KEYBOARD_SOLO, "attack", "P")
    labels = keyboard_labels(rebound.keys[KEYBOARD_SOLO])
    sections = build_move_list(load_character("rook").moveset, labels, short_hop_macro=True)
    assert inputs_of(sections, "uair") == "I + P"
    assert section(sections, "AIR").rows[-1].inputs == "SPACE + P together"


def test_an_unbound_action_says_so() -> None:
    keys = dict(Settings().keys[KEYBOARD_ARROWS])
    assert keys["walk"] == ""
    keys["taunt"] = ""
    assert keyboard_labels(keys)["taunt"] == UNBOUND


def test_arrow_keys_and_gamepad_presets() -> None:
    arrows = keyboard_labels(Settings().keys[KEYBOARD_ARROWS])
    assert (arrows["stick"], arrows["attack"], arrows["up"]) == ("arrows", "NUM_4", "NUM_8")
    pad = gamepad_labels(RIGHT_STICK_MODIFIERS)
    assert (pad["attack"], pad["jump"], pad["strong"], pad["up"]) == ("A", "X/Y", "LB", "RS up")
    bumpers = gamepad_labels(MODIFIER_BUMPERS)
    assert (bumpers["up"], bumpers["down"], bumpers["strong"]) == ("LB", "LT", "RS")


def test_every_label_map_names_every_action() -> None:
    for labels in (SOLO, gamepad_labels(RIGHT_STICK_MODIFIERS)):
        assert set(labels) == set(ACTIONS)
    with pytest.raises(ValueError, match="no label for attack"):
        build_move_list(
            load_character("rook").moveset,
            {k: v for k, v in SOLO.items() if k != "attack"},
            short_hop_macro=True,
        )


@pytest.mark.parametrize("character", CHARACTERS)
def test_the_page_fits_two_columns_without_clipping(character: str) -> None:
    moveset = load_character(character).moveset
    label_sets = [
        SOLO,
        keyboard_labels(Settings().keys[KEYBOARD_ARROWS]),
        gamepad_labels(RIGHT_STICK_MODIFIERS),
        gamepad_labels(MODIFIER_BUMPERS),
    ]
    for labels in label_sets:
        sections = build_move_list(moveset, labels, short_hop_macro=True)
        unclipped = page_columns(sections, 1000)
        assert page_columns(sections, COLUMN_WIDTH) == unclipped
        left, right = unclipped
        assert left[0] == "GROUND" and "AIR" in left
        assert right[0] == "SPECIALS" and "OTHER" in right
        assert max(len(left), len(right)) <= 18, "MOVES_MAX_ROWS in scenes/battle.py"


def test_the_arrow_keys_read_as_arrows_whatever_name_they_were_saved_under() -> None:
    keys = dict(Settings().keys[KEYBOARD_ARROWS])
    keys["move_up"], keys["move_right"] = "MOTION_UP", "MOTION_RIGHT"
    assert keyboard_labels(keys)["stick"] == "arrows"
    keys["move_up"] = "W"
    assert keyboard_labels(keys)["stick"] == "W/LEFT/DOWN/RIGHT"
