"""Tests for the packed sprites in ``assets/`` and how the game picks a pose.

Plan note "10 - Animation and Asset Pipeline" ("Asset validation") and decisions D-045 to
D-047. The validation half checks every committed sheet against ``art_src`` and the move data,
so an out-of-date or broken build fails here rather than in a match.
"""

import pytest
from PIL import Image

from helpers import make_match
from isofightr.art.anims import list_anims, load_timing
from isofightr.art.palettes import load_palettes
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.sprite_sheet import (
    AnimInfo,
    SpriteSheetError,
    load_sprite_set,
    parse_sprite_set,
)
from isofightr.render.anim_select import FALLBACKS, STATE_ANIMS, select_anim, wanted_anim
from isofightr.render.fighter_look import costume_for, fighter_look
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import Dir8

ANIMATED = [cid for cid in list_character_ids() if load_sprite_set(cid) is not None]


def test_rook_has_sprites() -> None:
    assert "rook" in ANIMATED


# --- validation of committed sheets ------------------------------------------------------


@pytest.mark.parametrize("character_id", ANIMATED)
def test_sheets_match_the_art_sources(character_id: str) -> None:
    sprite_set = load_sprite_set(character_id)
    assert sprite_set is not None
    names = list_anims(character_id)
    assert sorted(sprite_set.anims) == names, "rebuild with tools/build_art.py"
    for name in names:
        timing = load_timing(character_id, name)
        info = sprite_set.anims[name]
        assert (info.poses, info.loop, info.fps, info.starts) == (
            timing.poses,
            timing.loop,
            timing.fps,
            timing.starts,
        ), f"{name}: sheet timing is out of date; rebuild"
    palettes = load_palettes(character_id)
    assert [name for name, _ in sprite_set.costumes] == [c.name for c in palettes.costumes]
    for (_, colors), costume in zip(sprite_set.costumes, palettes.costumes, strict=True):
        assert list(colors) == costume.colors(), "costume colours are out of date; rebuild"


@pytest.mark.parametrize("character_id", ANIMATED)
def test_every_pose_exists_in_all_eight_directions(character_id: str) -> None:
    sprite_set = load_sprite_set(character_id)
    assert sprite_set is not None
    expected = {
        f"{anim}/{pose}/{facing.name}"
        for anim, info in sprite_set.anims.items()
        for pose in range(info.poses)
        for facing in Dir8
    }
    assert set(sprite_set.frames) == expected
    sheets = [Image.open(sprite_set.folder / name) for name in sprite_set.sheets]
    assert all(sheet.mode == "P" for sheet in sheets)
    index_count = len(sprite_set.costumes[0][1])
    for key, rect in sprite_set.frames.items():
        sheet = sheets[rect.sheet]
        assert rect.x + rect.width <= sheet.width and rect.y + rect.height <= sheet.height, key
        # The feet are under the drawing horizontally; they are below its top (in the air
        # the body is lifted, so they may be below its bottom too).
        assert 0 <= rect.pivot_x <= rect.width, key
        assert rect.pivot_y > 0, key
        crop = sheet.crop((rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))
        assert max(crop.getdata()) < index_count, f"{key} uses a colour no costume defines"


@pytest.mark.parametrize("character_id", ANIMATED)
def test_attack_animations_fit_their_moves(character_id: str) -> None:
    sprite_set = load_sprite_set(character_id)
    assert sprite_set is not None
    character = load_character(character_id)
    for move_id, move in character.moves.items():
        info = sprite_set.anims.get(move_id)
        if info is None:
            continue
        assert not info.loop, f"{move_id}: a move's animation is timed, not looped"
        assert info.starts[-1] <= move.total, f"{move_id}: a pose starts after the move ends"
        first = move.first_active_frame
        if first is not None:
            assert first in info.starts, f"{move_id}: no pose starts on active frame {first}"


# --- sprites.json -------------------------------------------------------------------------


def test_pose_timing() -> None:
    loop = AnimInfo(poses=4, loop=True, fps=6)
    assert [loop.pose_at(frame) for frame in (1, 10, 11, 20, 21, 40, 41)] == [0, 0, 1, 1, 2, 3, 0]
    timed = AnimInfo(poses=3, loop=False, starts=(1, 4, 9))
    assert [timed.pose_at(frame) for frame in (0, 1, 3, 4, 8, 9, 50)] == [0, 0, 0, 1, 1, 2, 2]


def test_malformed_sprites_json_is_refused(tmp_path: object) -> None:
    with pytest.raises(SpriteSheetError, match="format"):
        parse_sprite_set({"format": 99}, tmp_path)  # type: ignore[arg-type]
    good = {
        "format": 1,
        "character": "x",
        "sheets": ["sheet_0.png"],
        "costumes": [{"name": "A", "colors": ["000000", "ffffff"]}],
        "anims": {"idle": {"loop": True, "fps": 6, "poses": 1}},
        "frames": {"idle/0/E": [1, 0, 0, 1, 1, 0, 1]},
    }
    with pytest.raises(SpriteSheetError, match="no sheet 1"):
        parse_sprite_set(good, tmp_path)  # type: ignore[arg-type]
    with pytest.raises(SpriteSheetError, match="malformed"):
        parse_sprite_set({**good, "frames": {"idle/0/E": ["a"]}}, tmp_path)  # type: ignore[arg-type]


# --- picking a pose -----------------------------------------------------------------------

ANIMS = {
    "idle": AnimInfo(poses=4, loop=True, fps=6),
    "fall": AnimInfo(poses=1, loop=True, fps=1),
    "jab1": AnimInfo(poses=3, loop=False, starts=(1, 3, 5)),
}


def test_every_state_has_an_animation_name() -> None:
    missing = [state for state in StateId if state not in STATE_ANIMS]
    assert missing == [StateId.ATTACK, StateId.THROW, StateId.KO]
    for name in FALLBACKS:
        seen = {name}
        while name in FALLBACKS:
            name = FALLBACKS[name]
            assert name not in seen, "fallbacks must not loop"
            seen.add(name)


def test_attacks_use_their_move_and_its_timing() -> None:
    match = make_match()
    fighter = match.fighters[0]
    fighter.state, fighter.move_id, fighter.state_frame = StateId.ATTACK, "jab1", 4
    assert wanted_anim(fighter) == "jab1"
    choice = select_anim(fighter, ANIMS)
    assert choice is not None and (choice.anim, choice.pose, choice.exact) == ("jab1", 1, True)
    fighter.state_frame = 5
    assert select_anim(fighter, ANIMS).pose == 2  # type: ignore[union-attr]
    fighter.state, fighter.throw_id = StateId.THROW, "bthrow"
    assert wanted_anim(fighter) == "bthrow"


def test_missing_animations_fall_back() -> None:
    match = make_match()
    fighter = match.fighters[0]
    fighter.state, fighter.state_frame = StateId.HELPLESS, 3
    choice = select_anim(fighter, ANIMS)
    assert choice is not None and (choice.anim, choice.exact) == ("fall", False)
    fighter.state = StateId.ATTACK
    fighter.move_id = "fsmash"
    choice = select_anim(fighter, ANIMS)
    assert choice is not None and choice.anim == "idle" and not choice.exact
    assert select_anim(fighter, {}) is None


def test_costumes() -> None:
    match = make_match(fighters=("rook",) * 4)
    assert [costume_for(fighter, 6) for fighter in match.fighters] == [0, 2, 3, 4]
    for fighter, team in zip(match.fighters, (1, 0, 1, 2), strict=True):
        fighter.team = team
    assert [costume_for(fighter, 6) for fighter in match.fighters] == [2, 1, 2, 3]


def test_look_carries_the_pose() -> None:
    match = make_match()
    fighter = match.fighters[0]
    look = fighter_look(fighter, 1, anims=ANIMS, costume=2)
    assert look.sprite is not None and look.sprite.anim == "idle"
    assert look.costume == 2 and look.character == "rook"
    assert fighter_look(fighter, 1).sprite is None, "no sprites: the placeholder"
