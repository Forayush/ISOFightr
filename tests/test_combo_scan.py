"""Tests for the combo scan (frame advantage on hit) and the combo targets of decision D-059."""

import pytest

from isofightr.data.character_loader import load_character
from isofightr.sim.combat import constants as c
from isofightr.sim.combat import knockback as kb
from isofightr.sim.combo_scan import best, scan, starters, table
from isofightr.sim.move_def import MoveKind

CHARACTERS = ("rook", "bramble", "zephyr", "mote")
ROOK = load_character("rook")
AT_0, AT_30, AT_60 = 0, 1, 2
STARTERS_AT_30 = 4
"""Every character has at least this many combo starters at 30%."""
OPENERS_AT_0 = ("rook", "zephyr")
"""Characters that must have a combo starter at 0%. Bramble (the heavy) and Mote (the zoner)
are exempt: Mote's best single hit is still 2 frames ahead (D-059, "As built")."""
FREE_STRING = 30
"""No single hit may leave the attacker this far ahead at 60% or below."""


def test_advantage_is_hitstun_minus_the_end_lag_after_the_first_active_frame() -> None:
    rows = {row.move_id: row for row in scan(ROOK, ROOK)}
    utilt = ROOK.moves["utilt"]
    box = utilt.windows[0].hitboxes[0]
    damage = box.damage * c.FRESH_BONUS
    knockback = kb.knockback(30 + damage, damage, ROOK.weight, box.bkb, box.kbg)
    expected = kb.hitstun_frames(knockback) - (utilt.faf - utilt.windows[0].frames.first)
    assert rows["utilt"].advantage[AT_30] == expected
    assert rows["utilt"].first_active == 6 and rows["utilt"].faf == utilt.faf


def test_multi_hit_moves_are_left_out_and_jabs_are_not_starters() -> None:
    rows = scan(ROOK, ROOK)
    ids = {row.move_id for row in rows}
    assert "nair" not in ids, "Rook's neutral air hits twice"
    assert "fsmash" not in ids and "nspecial" not in ids, "only jabs, tilts, dash attacks, aerials"
    jabs = [row for row in rows if row.kind is MoveKind.JAB]
    assert jabs and not any(row.starter for row in jabs)
    assert len(table(rows)) == len(rows) + 2


@pytest.mark.parametrize("character_id", CHARACTERS)
def test_combo_targets(character_id: str) -> None:
    rows = scan(load_character(character_id), ROOK)
    assert starters(rows, AT_30) >= STARTERS_AT_30
    if character_id in OPENERS_AT_0:
        assert starters(rows, AT_0) >= 1
    assert best(rows, AT_60) <= FREE_STRING and best(rows, AT_30) <= FREE_STRING


def test_a_heavier_target_is_stunned_for_less() -> None:
    light = scan(ROOK, load_character("zephyr"))
    heavy = scan(ROOK, load_character("bramble"))
    assert best(heavy, AT_60) < best(light, AT_60)
