"""Tests for the crouch report (which moves reach a standing and a crouching target, D-069)."""

import pytest

from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.combat.hitbox import hurtbox, hurtbox_capsule
from isofightr.sim.crouch_report import (
    CROUCHING,
    FACING,
    GUARD_SLOTS,
    STANDING,
    CrouchRow,
    Reach,
    findings,
    guarded_actions,
    scan,
    scanned_actions,
    table,
)
from isofightr.sim.events import HitEvent
from isofightr.sim.input_frame import NEUTRAL_INPUT
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.states.interrupts import start_move

GRID = load_stage("training_grid")
CHARACTERS = {character_id: load_character(character_id) for character_id in list_character_ids()}


@pytest.fixture(scope="module")
def reports() -> dict[str, list[CrouchRow]]:
    return {character_id: scan(GRID, character) for character_id, character in CHARACTERS.items()}


def really_hits(character: CharacterDef, move_id: str, distance: float) -> bool:
    """Whether the move really hits a target of the same character standing ``distance``
    units in front, in a real match."""
    match = Match.create(GRID, [character, character], rules=MatchRules(stocks=None))
    attacker, target = match.fighters
    spot = GRID.respawn
    top = GRID.surface_top(spot.x, spot.y)
    assert top is not None
    attacker.pos = Vec3(spot.x, spot.y, top)
    attacker.facing = FACING
    ahead = spot + FACING.world * distance
    target.pos = Vec3(ahead.x, ahead.y, top)
    start_move(match, attacker, move_id)
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        if any(isinstance(event, HitEvent) for event in match.events):
            return True
    return False


def test_the_capsule_helper_is_the_hurtbox() -> None:
    match = Match.create(GRID, [CHARACTERS["rook"], CHARACTERS["mote"]])
    for fighter in match.fighters:
        assert hurtbox(fighter) == hurtbox_capsule(fighter.pos, fighter.character.body.hurtbox)


def test_the_standing_column_agrees_with_real_hits(reports: dict[str, list[CrouchRow]]) -> None:
    """The report's standing target is where a real fighter would be hit."""
    rook = {row.action: row for row in reports["rook"]}
    zephyr = {row.action: row for row in reports["zephyr"]}
    cases = [
        ("rook", rook, "jab1", 1.0),
        ("rook", rook, "utilt", 1.0),
        ("rook", rook, "utilt", 1.5),
        ("zephyr", zephyr, "jab1", 1.5),
        ("zephyr", zephyr, "dtilt", 1.5),
    ]
    for character_id, rows, move_id, distance in cases:
        reported = rows[move_id].reaches(distance, STANDING)
        assert reported == really_hits(CHARACTERS[character_id], move_id, distance), (
            character_id,
            move_id,
            distance,
        )


def test_every_move_and_grab_has_a_row_and_the_guard_list_is_marked(
    reports: dict[str, list[CrouchRow]],
) -> None:
    for character_id, rows in reports.items():
        character = CHARACTERS[character_id]
        assert [row.action for row in rows] == scanned_actions(character)
        guarded = set(guarded_actions(character).values())
        assert len(guarded_actions(character)) == len(GUARD_SLOTS)
        assert {row.action for row in rows if row.guarded} == guarded
        lines = table(rows)
        assert len(lines) == len(rows) + 1
        assert all(line.lstrip().startswith("*") for line in lines[1:] if "*" in line[:4])


def test_the_guard_list_reaches_a_standing_target_first(
    reports: dict[str, list[CrouchRow]],
) -> None:
    """The guard moves are all close-range: each reaches a standing target at 1 unit with
    its first window (so the guard has something to protect)."""
    for character_id, rows in reports.items():
        for row in rows:
            if row.guarded:
                assert row.reach[(1.0, STANDING)] is Reach.FIRST, (character_id, row.action)


def test_d069s_guard_list_reaches_a_crouching_target(
    reports: dict[str, list[CrouchRow]],
) -> None:
    """Decision D-069's balance guard, with each character's own crouch capsule."""
    for character_id, rows in reports.items():
        assert not [row.action for row in rows if row.guard_failure], character_id


def test_a_low_preview_capsule_lets_high_moves_pass_over() -> None:
    rook = CHARACTERS["rook"]
    low = rook.body.hurtbox.lowered(0.0)
    rows = {row.action: row for row in scan(GRID, rook, low, actions=["utilt", "dtilt"])}
    assert rows["utilt"].reaches(1.0, STANDING)
    assert not rows["utilt"].reaches(1.0, CROUCHING)
    assert rows["utilt"].passes_over == (1.0,)
    assert rows["dtilt"].reaches(1.0, CROUCHING)
    assert any("utilt" in line for line in findings(list(rows.values())))


def test_the_report_crouches_with_the_characters_own_capsule() -> None:
    rook = CHARACTERS["rook"]
    row = scan(GRID, rook, actions=["utilt"])[0]
    same = scan(GRID, rook, rook.body.crouch_hurtbox, actions=["utilt"])[0]
    assert row == same


def test_d069s_share_and_the_lowest_capsule() -> None:
    tops = {
        character_id: character.body.hurtbox.lowered(0.62).z1
        for character_id, character in CHARACTERS.items()
    }
    expected = {"rook": 1.5, "bramble": 1.69, "zephyr": 1.2, "mote": 1.38}
    assert tops == pytest.approx(expected, abs=0.005)
    shape = CHARACTERS["rook"].body.hurtbox.lowered(0.0)
    assert shape.z1 == pytest.approx(shape.z0 + 2 * shape.radius), "never lower than a sphere"
