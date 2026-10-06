"""Hero art: each character's big key pose, win pose and roster tile (plan note 10,
decision D-061, M13 group 4).

The committed pictures in ``assets/characters/<id>/ui/`` are checked against their sources
by a hash, so a stale build fails here without needing Blender.
"""

import json
import tomllib
from pathlib import Path

import pytest
from PIL import Image

from isofightr.art import hero
from isofightr.art.blender import GAME_ELEVATION, TURNED_VIEW, RenderJob, _directions, stamp_for
from isofightr.art.hero import HeroCamera, HeroError, parse_camera
from isofightr.data.character_loader import list_character_ids
from isofightr.data.sprite_sheet import UI_PICTURES, load_sprite_set
from isofightr.sim.input_frame import Dir8

ANIMATED = [cid for cid in list_character_ids() if load_sprite_set(cid) is not None]
MAX_HEIGHT = 140
"""D-061: about 120 to 140 px tall at most. A player panel shows that much."""
MAX_WIDTH = 132
"""The narrowest place hero art stands: a card of a four-player loading screen."""


def ui_folder(character_id: str) -> Path:
    sprite_set = load_sprite_set(character_id)
    assert sprite_set is not None
    return sprite_set.folder.parent / "ui"


def test_every_character_with_sprites_has_hero_art() -> None:
    assert sorted(ANIMATED) == ["bramble", "mote", "rook", "zephyr"]
    for character_id in ANIMATED:
        assert hero.has_hero(character_id), f"{character_id} needs art_src hero.toml"
        folder = ui_folder(character_id)
        for name in (*hero.OUTPUTS, hero.INDEX_FILE):
            assert (folder / name).is_file(), f"{character_id}: run build_art.py --hero"
    assert tuple(f"{name}.png" for name in UI_PICTURES) == hero.OUTPUTS


@pytest.mark.parametrize("character_id", ANIMATED)
def test_the_committed_hero_art_is_up_to_date_with_its_sources(character_id: str) -> None:
    index = json.loads((ui_folder(character_id) / hero.INDEX_FILE).read_text(encoding="utf-8"))
    assert index["source"] == hero.source_hash(character_id), (
        f"{character_id}: a hero source changed; run tools/build_art.py {character_id} --hero"
    )
    camera = hero.load_camera(character_id)
    assert index["camera"] == {"turn": camera.turn, "elevation": camera.elevation}
    assert index["scale"] == hero.HERO_SCALE == 2, "the scale the user chose"
    assert index["character"] == character_id


@pytest.mark.parametrize("character_id", ANIMATED)
def test_hero_pictures_are_indexed_like_the_sheets_and_fit_the_panels(character_id: str) -> None:
    sprite_set = load_sprite_set(character_id)
    assert sprite_set is not None
    folder = ui_folder(character_id)
    index = json.loads((folder / hero.INDEX_FILE).read_text(encoding="utf-8"))
    colours = len(sprite_set.costumes[0][1])
    for name in UI_PICTURES:
        with Image.open(folder / f"{name}.png") as image:
            assert image.mode == "P", f"{name} must stay indexed, so costumes recolour it"
            assert list(image.size) == index["sizes"][name]
            assert max(image.getdata()) < colours, f"{name} uses a colour no costume defines"
            drawn = image.convert("RGBA").getbbox()
            assert drawn is not None
            if name == "tile":
                assert image.size == (hero.TILE_SIZE, hero.TILE_SIZE)
                continue
            assert 70 <= image.height <= MAX_HEIGHT, f"{name} is {image.height} px tall"
            assert image.width <= MAX_WIDTH
            margin = hero.MARGIN
            assert drawn == (margin, margin, image.width - margin, image.height - margin), (
                "trimmed to the drawing, with a 1 px margin"
            )
    assert len(sprite_set.costumes) == 6


@pytest.mark.parametrize("character_id", ANIMATED)
def test_every_costume_recolours_the_hero_art(character_id: str) -> None:
    sprite_set = load_sprite_set(character_id)
    assert sprite_set is not None
    with Image.open(ui_folder(character_id) / "hero.png") as opened:
        indexed = opened.copy()
    looks = set()
    for _, colors in sprite_set.costumes:
        flat = [0, 0, 0, 0]
        for red, green, blue in colors[1:]:
            flat += [red, green, blue, 255]
        picture = indexed.copy()
        picture.putpalette(flat + [0] * (256 * 4 - len(flat)), rawmode="RGBA")
        looks.add(picture.convert("RGBA").tobytes())
    assert len(looks) == len(sprite_set.costumes), "six costumes, six pictures"


def test_the_sprite_set_finds_menu_art_next_to_the_sheets() -> None:
    sprite_set = load_sprite_set("rook")
    assert sprite_set is not None
    for name in UI_PICTURES:
        path = sprite_set.portrait_path(name)
        assert path is not None and path.parent.name == "ui"
    bust = sprite_set.portrait_path("bust")
    assert bust is not None and bust.parent == sprite_set.folder
    assert sprite_set.portrait_path("nonsense") is None


# --- the camera ------------------------------------------------------------------------------


def test_each_character_has_a_view_that_suits_its_pose() -> None:
    cameras = {character_id: hero.load_camera(character_id) for character_id in ANIMATED}
    assert cameras["bramble"].elevation < cameras["rook"].elevation, "the golem is seen from low"
    assert abs(cameras["zephyr"].turn) > 40, "the dash is seen from the side"
    assert abs(cameras["rook"].turn) < 30 and abs(cameras["bramble"].turn) < 30, "squared up"
    for camera in cameras.values():
        assert camera.elevation < GAME_ELEVATION, "a portrait, not the game's view from above"
    assert len(set(cameras.values())) == len(cameras)


def test_the_camera_table_is_read_strictly() -> None:
    assert parse_camera({}) == HeroCamera(0.0, hero.DEFAULT_ELEVATION)
    assert parse_camera({"camera": {"turn": -20, "elevation": 8.5}}) == HeroCamera(-20.0, 8.5)
    assert parse_camera({"camera": {"turn": 30}}).elevation == hero.DEFAULT_ELEVATION
    for bad, message in (
        ({"camera": {"zoom": 2}}, "unknown"),
        ({"camera": {"turn": "left"}}, "must be a number"),
        ({"camera": {"turn": True}}, "must be a number"),
        ({"camera": {"turn": 120}}, "must be -80 to 80"),
        ({"camera": {"elevation": -5}}, "must be 0 to 45"),
        ({"camera": 3}, "must be a table"),
    ):
        with pytest.raises(HeroError, match=message):
            parse_camera(bad)


def test_a_hero_file_needs_a_pose(tmp_path: Path) -> None:
    folder = tmp_path / "characters" / "nobody"
    folder.mkdir(parents=True)
    assert not hero.has_hero("nobody", tmp_path)
    (folder / hero.HERO_FILE).write_text("[camera]\nturn = 10\n", encoding="utf-8")
    assert hero.has_hero("nobody", tmp_path)
    with pytest.raises(HeroError, match="needs one"):
        hero.load_camera("nobody", tmp_path)
    (folder / hero.HERO_FILE).write_text('[[poses]]\nuse = "ready"\n', encoding="utf-8")
    assert hero.load_camera("nobody", tmp_path) == HeroCamera()


def test_the_source_hash_follows_every_source_but_not_line_endings(tmp_path: Path) -> None:
    folder = tmp_path / "characters" / "nobody"
    (folder / "anims").mkdir(parents=True)
    for name in hero.SOURCES:
        if name != hero.WIN_FILE:
            (folder / name).write_bytes(f"# {name}\nvalue = 1\n".encode())
    first = hero.source_hash("nobody", tmp_path)
    assert first == hero.source_hash("nobody", tmp_path)
    (folder / "rig.toml").write_bytes(b"# rig.toml\r\nvalue = 1\r\n")
    assert hero.source_hash("nobody", tmp_path) == first, "CRLF is the same file"
    seen = {first}
    for name in hero.SOURCES:
        path = folder / name
        before = path.read_bytes() if path.is_file() else None
        path.write_bytes(b"changed = true\n")
        seen.add(hero.source_hash("nobody", tmp_path))
        if before is None:
            path.unlink()
        else:
            path.write_bytes(before)
    assert len(seen) == len(hero.SOURCES) + 1, "each source changes the hash"
    assert hero.win_pose_file("nobody", tmp_path).name == "victory.toml"
    (folder / hero.WIN_FILE).write_text("[[poses]]\n", encoding="utf-8")
    assert hero.win_pose_file("nobody", tmp_path).name == hero.WIN_FILE
    assert hero.win_pose_file("rook").name == hero.WIN_FILE, "Rook has a win pose of his own"


def test_hero_files_only_pose_joints_the_rig_has() -> None:
    for character_id in ANIMATED:
        folder = hero.character_dir(character_id)
        with (folder / "rig.toml").open("rb") as file:
            joints = {joint["name"] for joint in tomllib.load(file)["joints"]}
        for name in (hero.HERO_FILE, hero.WIN_FILE):
            path = folder / name
            if not path.is_file():
                continue
            with path.open("rb") as file:
                data = tomllib.load(file)
            assert set(data) <= {"camera", "poses", "parts", "smears", "base"}, path
            assert len(data["poses"]) == 1, f"{path}: one pose"
            posed = set(data["poses"][0]) - {"use", "offset", "show", "start"}
            assert posed <= joints, f"{path}: unknown joints {sorted(posed - joints)}"


# --- the render job --------------------------------------------------------------------------


def job(**options: object) -> RenderJob:
    here = Path("nowhere")
    return RenderJob("rook", here, here, ("skin",), {"hero": here}, here, **options)  # type: ignore[arg-type]


def test_a_turned_job_renders_one_view_and_a_plain_job_is_unchanged() -> None:
    plain = _directions(job())
    assert [direction["name"] for direction in plain] == [facing.name for facing in Dir8]
    [front] = _directions(job(turn=0.0))
    south = next(direction for direction in plain if direction["name"] == "S")
    assert front["name"] == TURNED_VIEW
    assert front["blender"] == pytest.approx(south["blender"]), "no turn faces the viewer"
    [side] = _directions(job(turn=90.0))
    x, y = side["blender"]  # type: ignore[misc]
    fx, fy = front["blender"]  # type: ignore[misc]
    assert x * fx + y * fy == pytest.approx(0.0, abs=1e-9), "a quarter turn"
    assert x * x + y * y == pytest.approx(1.0)
    [left], [right] = _directions(job(turn=-30.0)), _directions(job(turn=30.0))
    assert left["blender"] != right["blender"]


def test_the_cache_stamp_knows_the_camera() -> None:
    assert job().elevation == GAME_ELEVATION and job().z_squash is None and job().turn is None
    base = stamp_for(job(), "hero")
    assert stamp_for(job(), "hero") == base
    assert stamp_for(job(elevation=12.0), "hero") != base
    assert stamp_for(job(z_squash=1.0), "hero") != base
    assert stamp_for(job(turn=20.0), "hero") != stamp_for(job(turn=0.0), "hero")
