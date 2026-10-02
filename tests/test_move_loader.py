"""Tests for the strict move TOML loader and data validation of Rook's shipped moves.

Plan note "07 - Fighter State Machine and Move Data" ("Move data format", "Validation at
load", "Frame data conventions").
"""

import tomllib

import pytest

from isofightr.data.character_loader import load_character
from isofightr.data.move_loader import parse_move
from isofightr.data.validation import DataError
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import DirectionMode, Effect, FrameRange, MoveDef, MoveKind

TILT = """
id = "ftilt"
kind = "tilt"
total = 30
faf = 31

[[windows]]
frames = "7-9"
  [[windows.hitboxes]]
  id = 1
  offset = [0.6, 0.0, 1.2]
  radius = 0.4
  damage = 8.0
  angle = 361
  [[windows.hitboxes]]
  id = 0
  offset = [1.1, 0.0, 1.2]
  radius = 0.5
  damage = 9.0
  angle = 361
  bkb = 20
  kbg = 90
"""

AERIAL = """
id = "nair"
kind = "aerial"
total = 40
faf = 41
landing_lag = 7
autocancel = ["1-3", "32-"]

[[windows]]
frames = "4-7"
  [[windows.hitboxes]]
  id = 0
  offset = [0.3, 0.0, 1.2]
  radius = 0.7
  damage = 8.0
  angle = 361
"""


def parse(text: str, name: str = "ftilt") -> MoveDef:
    return parse_move(tomllib.loads(text), source=f"{name}.toml", expected_id=name)


ROOK = load_character("rook")


# --- parsing ------------------------------------------------------------------------------


def test_a_move_parses_with_defaults() -> None:
    move = parse(TILT)
    assert (move.id, move.kind, move.total, move.faf, move.anim) == (
        "ftilt",
        MoveKind.TILT,
        30,
        31,
        "ftilt",
    )
    assert move.charge is None and move.cancel is None and move.motion == ()
    [window] = move.windows
    assert window.frames == FrameRange(7, 9)
    sweet, sour = window.hitboxes
    assert (sweet.id, sour.id) == (0, 1), "hitboxes are kept in priority order"
    assert sweet.offset == Vec3(1.1, 0.0, 1.2)
    assert (sweet.bkb, sweet.kbg) == (20.0, 90.0)
    assert (sour.bkb, sour.kbg, sour.fkb, sour.yaw, sour.group, sour.rehit) == (0, 100, 0, 0, 0, 0)
    assert (sour.hitlag_mult, sour.sdi_mult) == (1.0, 1.0)
    assert sour.direction_mode is DirectionMode.FACING and sour.effect is Effect.NORMAL
    assert sour.hits_ground and sour.hits_air
    assert sour.clank, "ground attacks clank by default"


def test_frame_ranges_are_inclusive_and_one_indexed() -> None:
    move = parse(TILT)
    assert [frame for frame in range(1, 31) if move.active_hitboxes(frame)] == [7, 8, 9]
    assert move.first_active_frame == 7
    assert 9 in FrameRange(7, 9) and 10 not in FrameRange(7, 9) and 6 not in FrameRange(7, 9)


def test_aerials_need_landing_lag_and_do_not_clank() -> None:
    move = parse(AERIAL, "nair")
    assert move.landing_lag == 7
    assert move.autocancel == (FrameRange(1, 3), FrameRange(32, 40)), "an open range ends at total"
    assert not move.windows[0].hitboxes[0].clank


def test_optional_hitbox_fields() -> None:
    text = TILT.replace(
        "  bkb = 20",
        '  bkb = 20\n  fkb = 30\n  yaw = 180\n  group = 2\n  rehit = 6\n  effect = "electric"\n'
        '  direction_mode = "radial"\n  hits = ["air"]\n  clank = false\n  hitlag_mult = 0.5\n'
        "  sdi_mult = 2.0",
    )
    box = parse(text).windows[0].hitboxes[0]
    assert (box.fkb, box.yaw, box.group, box.rehit) == (30, 180, 2, 6)
    assert box.effect is Effect.ELECTRIC and box.direction_mode is DirectionMode.RADIAL
    assert (box.hits_ground, box.hits_air, box.clank) == (False, True, False)
    assert (box.hitlag_mult, box.sdi_mult) == (0.5, 2.0)


def test_motion_charge_and_cancel() -> None:
    text = (
        TILT.replace(
            'kind = "tilt"',
            'kind = "smash"\ncharge = { frame = 6, max_frames = 60, damage_mult = 1.4 }',
        )
        + '\n[[motion]]\nframes = "12-16"\nvelocity = [0.06, 0.0, 0.0]\n'
        + '\n[cancel]\nframes = "10-20"\ninto = "jab2"\n'
    )
    move = parse(text)
    assert move.charge is not None
    assert (move.charge.frame, move.charge.max_frames, move.charge.damage_mult) == (6, 60, 1.4)
    assert move.scripted_velocity(12) == Vec3(0.06, 0.0, 0.0)
    assert move.scripted_velocity(11) is None and move.scripted_velocity(17) is None
    assert move.cancel is not None and move.cancel.into == "jab2"
    assert move.cancel.frames == FrameRange(10, 20)


# --- strict validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("total = 30", "total = 30\nkgb = 3", r"unknown key\(s\) 'kgb'"),
        ("  kbg = 90", "  kgb = 90", r"windows\[0\]\.hitboxes\[1\]: unknown key\(s\) 'kgb'"),
        ('kind = "tilt"', 'kind = "poke"', "kind: must be one of jab, tilt, dash_attack"),
        ("faf = 31", "faf = 33", r"faf: must be between 1 and total \+ 1 \(31\)"),
        ("total = 30", "total = 0", "total: must be 1 or greater"),
        ('frames = "7-9"', 'frames = "7-31"', r"frames '7-31' must lie within 1\.\.30"),
        ('frames = "7-9"', 'frames = "9-7"', "must lie within"),
        ('frames = "7-9"', 'frames = "0-3"', "must lie within"),
        ('frames = "7-9"', 'frames = "soon"', 'must be a frame range like "14-16"'),
        ("  id = 1", "  id = 0", r"hitbox ids must be unique within a window, got \[0, 0\]"),
        ("  radius = 0.4", "  radius = 0", r"hitboxes\[0\]\.radius: must be greater than 0"),
        ("  damage = 8.0", "  damage = -1", "damage: must be 0 or greater"),
        ("  angle = 361\n  [[", "  angle = 120\n  [[", "angle: must be between -90 and 90, or 361"),
        ("  offset = [0.6, 0.0, 1.2]", "  offset = [0.6, 1.2]", "offset: must be an array of 3"),
        ("  radius = 0.4", "", r"hitboxes\[0\]\.radius: missing required key"),
        ("faf = 31", "faf = 31\nlanding_lag = 5", "landing_lag: is only allowed on aerials"),
        (
            "faf = 31",
            "faf = 31\ncharge = { frame = 6, max_frames = 60, damage_mult = 1.4 }",
            "charge: is only allowed on smash attacks",
        ),
        ("  bkb = 20", '  bkb = 20\n  hits = ["sky"]', 'hits: must be a list of "ground"'),
        ("  bkb = 20", '  bkb = 20\n  effect = "wet"', "effect: must be one of normal, slash"),
    ],
)
def test_mistakes_are_reported_with_file_and_key(old: str, new: str, message: str) -> None:
    assert old in TILT
    with pytest.raises(DataError, match=r"^ftilt\.toml: .*" + message):
        parse(TILT.replace(old, new, 1))


def test_id_must_match_the_file_name() -> None:
    with pytest.raises(DataError, match="id: is 'ftilt' but the file is named 'utilt'"):
        parse(TILT, "utilt")


def test_an_aerial_without_landing_lag_is_rejected() -> None:
    with pytest.raises(DataError, match="landing_lag: missing required key"):
        parse(AERIAL.replace("landing_lag = 7\n", ""), "nair")


def test_overlapping_hit_windows_are_rejected() -> None:
    text = (
        TILT
        + '\n[[windows]]\nframes = "9-12"\n  [[windows.hitboxes]]\n  id = 0\n'
        + ("  offset = [1.0, 0.0, 1.0]\n  radius = 0.5\n  damage = 1.0\n  angle = 0\n")
    )
    with pytest.raises(DataError, match="hit windows must be in order and must not overlap"):
        parse(text)


def test_a_window_needs_a_hitbox() -> None:
    with pytest.raises(DataError, match=r"windows\[0\]\.hitboxes: needs at least one hitbox"):
        parse('id = "ftilt"\nkind = "tilt"\ntotal = 30\nfaf = 31\n[[windows]]\nframes = "7-9"\n')


# --- Rook's shipped moves -----------------------------------------------------------------


def test_rook_has_all_the_m3_normals() -> None:
    grounded = ["jab1", "jab2", "jab3", "ftilt", "utilt", "dtilt", "dash_attack"]
    smashes_and_aerials = ["fsmash", "usmash", "dsmash", "nair", "fair", "bair", "uair", "dair"]
    recovery = ["getup_attack", "ledge_attack"]  # added in M4
    assert sorted(ROOK.moves) == sorted([*grounded, *smashes_and_aerials, *recovery])
    assert set(ROOK.moveset.all_ids()) == set(ROOK.moves)
    assert ROOK.moveset.jab == ("jab1", "jab2", "jab3")


def test_rook_moves_have_sensible_frame_data() -> None:
    for move in ROOK.moves.values():
        assert move.first_active_frame is not None, move.id
        assert 1 < move.first_active_frame <= move.faf <= move.total + 1, move.id
        for window in move.windows:
            for box in window.hitboxes:
                assert 0 < box.radius <= 1.0 and 0 < box.damage <= 20, move.id
        if move.kind is MoveKind.SMASH:
            assert move.charge is not None and move.charge.frame < move.first_active_frame
        if move.kind is MoveKind.AERIAL:
            assert move.landing_lag > ROOK.movement.land_lag and move.autocancel


def test_rook_jabs_chain_into_each_other() -> None:
    assert ROOK.moves["jab1"].cancel is not None and ROOK.moves["jab1"].cancel.into == "jab2"
    assert ROOK.moves["jab2"].cancel is not None and ROOK.moves["jab2"].cancel.into == "jab3"
    assert ROOK.moves["jab3"].cancel is None


def test_rook_forward_smash_matches_the_plan_example() -> None:
    move = ROOK.moves["fsmash"]
    assert (move.total, move.faf, move.first_active_frame) == (48, 49, 14)
    sweet, sour = move.windows[0].hitboxes
    assert (sweet.damage, sweet.angle, sweet.bkb, sweet.kbg) == (16.0, 38.0, 30.0, 105.0)
    assert (sour.damage, sour.bkb, sour.kbg) == (13.0, 25.0, 100.0)
    assert sweet.effect is Effect.SLASH
