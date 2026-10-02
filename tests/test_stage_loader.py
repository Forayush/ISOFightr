"""Tests for the strict stage TOML loader and data validation of every shipped stage.

Plan notes "11 - Stages" (file format, design rules) and "16 - Testing Debug and Tooling"
(data validation tests load every TOML in ``assets/``).
"""

import itertools
import tomllib
from pathlib import Path

import pytest

from isofightr.config import MIN_PLATFORM_CLEARANCE
from isofightr.data.paths import STAGE_FILE_NAME, STAGES_DIR
from isofightr.data.stage_loader import list_stage_ids, load_stage, load_stage_file, parse_stage
from isofightr.data.validation import DataError
from isofightr.sim.math3d import Vec2
from isofightr.sim.stage import Cell, SoftPlatform, Stage

MIN_SPAWN_SPACING = 4.0  # design rule 4 in the plan note "11 - Stages"

MINIMAL = """
id = "mini"
display_name = "Mini"
tileset = "grid"
grid = '''
  000
  000
'''
[spawns]
p1 = [0.5, 0.5]
p2 = [2.5, 0.5]
p3 = [0.5, 1.5]
p4 = [2.5, 1.5]
respawn = [1.5, 1]
"""


def parse(text: str, expected_id: str | None = "mini") -> Stage:
    return parse_stage(tomllib.loads(text), source="mini/stage.toml", expected_id=expected_id)


def write_stage(stages_dir: Path, stage_id: str, text: str) -> Path:
    path = stages_dir / stage_id / STAGE_FILE_NAME
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- shipped stages -----------------------------------------------------------------------


def test_the_m1_stages_ship() -> None:
    assert {"training_grid", "sky_ruins"} <= set(list_stage_ids())


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_shipped_stage_loads_and_follows_the_design_rules(stage_id: str) -> None:
    stage = load_stage(stage_id)
    assert stage.id == stage_id

    for first, second in itertools.combinations(stage.spawns, 2):
        assert (first - second).length() >= MIN_SPAWN_SPACING
    assert stage.ledges, "ledges on all exterior edges"
    for platform in stage.soft_platforms:
        tops = [
            cell.top
            for cy in range(platform.y0, platform.y1)
            for cx in range(platform.x0, platform.x1)
            if (cell := stage.cell(cx, cy)) is not None
        ]
        assert tops, "a soft platform should have ground somewhere beneath it"
        assert platform.z >= max(tops) + MIN_PLATFORM_CLEARANCE
    for index in range(len(stage.spawns)):
        assert stage.blast_zone.contains(stage.spawn_point(index))


def test_training_grid_is_a_flat_12_by_12_square() -> None:
    stage = load_stage("training_grid")
    assert (stage.size_x, stage.size_y) == (12, 12)
    assert all(cell == Cell(top=0.0, tile="grid") for row in stage.cells for cell in row)
    assert stage.soft_platforms == ()
    assert sorted(ledge.length for ledge in stage.ledges) == [12.0] * 4


def test_sky_ruins_is_a_rounded_13_by_9_island_with_three_platforms() -> None:
    stage = load_stage("sky_ruins")
    assert (stage.size_x, stage.size_y) == (13, 9)
    assert sum(cell is not None for row in stage.cells for cell in row) == 13 * 9 - 12
    for cx, cy in [(0, 0), (1, 0), (0, 1), (12, 0), (0, 8), (12, 8), (11, 8), (12, 7)]:
        assert stage.cell(cx, cy) is None
    assert stage.cell(2, 0) is not None and stage.cell(0, 2) is not None
    assert stage.soft_platforms == (
        SoftPlatform(2, 6, 5, 9, 2.5),
        SoftPlatform(8, 0, 11, 3, 2.5),
        SoftPlatform(5, 3, 8, 6, 4.5),
    )
    assert stage.spawns[0] == Vec2(2.5, 4.5)
    # Each of the four sides: one long edge plus two one-cell steps at each rounded corner.
    assert len(stage.ledges) == 20
    assert sorted({ledge.length for ledge in stage.ledges}) == [1.0, 5.0, 9.0]
    blast = stage.blast_zone
    assert (blast.x_min, blast.x_max, blast.y_min, blast.y_max) == (-7.0, 20.0, -7.0, 16.0)
    assert (blast.z_min, blast.z_max) == (-8.0, 14.0)


# --- loading from disk --------------------------------------------------------------------


def test_load_from_a_directory(tmp_path: Path) -> None:
    write_stage(tmp_path, "mini", MINIMAL)
    assert list_stage_ids(tmp_path) == ["mini"]
    stage = load_stage("mini", tmp_path)
    assert (stage.id, stage.display_name, stage.size_x, stage.size_y) == ("mini", "Mini", 3, 2)


def test_unknown_stage_lists_what_is_available(tmp_path: Path) -> None:
    write_stage(tmp_path, "mini", MINIMAL)
    with pytest.raises(DataError, match=r"no such stage 'nope' \(available: mini\)"):
        load_stage("nope", tmp_path)


def test_id_must_match_the_directory(tmp_path: Path) -> None:
    path = write_stage(tmp_path, "other", MINIMAL)
    with pytest.raises(DataError, match=r"stage\.toml: id: is 'mini' but .* 'other'"):
        load_stage_file(path)


def test_invalid_toml_names_the_file(tmp_path: Path) -> None:
    path = write_stage(tmp_path, "mini", "id = ")
    with pytest.raises(DataError, match=r"stage\.toml: invalid TOML"):
        load_stage_file(path)


def test_shipped_stage_files_live_where_the_loader_looks() -> None:
    assert (STAGES_DIR / "sky_ruins" / STAGE_FILE_NAME).is_file()


# --- defaults and optional sections -------------------------------------------------------


def test_defaults_apply_when_optional_sections_are_missing() -> None:
    stage = parse(MINIMAL)
    assert stage.music is None
    assert stage.backgrounds == ()
    assert stage.soft_platforms == ()
    assert (stage.blast_zone.x_min, stage.blast_zone.z_min, stage.blast_zone.z_max) == (
        -7.0,
        -8.0,
        14.0,
    )
    assert stage.camera_bounds.x_min == -4.0
    assert stage.cell(0, 0) == Cell(top=0.0)


def test_optional_sections_are_read() -> None:
    text = (
        MINIMAL.replace('tileset = "grid"', 'tileset = "grid"\nmusic = "theme.ogg"')
        + """
[blast_zone]
side = 5
top = 10.0
bottom = -6.0
[camera]
bounds_margin = 2.5
[legend]
"0" = { height = 0, tile = "grass" }
[[soft_platforms]]
rect = [0, 0, 2, 1]
z = 2.5
[[background]]
image = "sky.png"
parallax = 0.1
"""
    )
    stage = parse(text)
    assert stage.music == "theme.ogg"
    assert stage.blast_zone.x_max == 3.0 + 5.0
    assert (stage.blast_zone.z_min, stage.blast_zone.z_max) == (-6.0, 10.0)
    assert stage.camera_bounds.x_min == -2.5
    assert stage.cell(1, 1) == Cell(top=0.0, tile="grass")
    assert stage.soft_platforms == (SoftPlatform(0, 0, 2, 1, 2.5),)
    assert [(layer.image, layer.parallax) for layer in stage.backgrounds] == [("sky.png", 0.1)]


def test_grid_indentation_and_blank_lines_are_ignored() -> None:
    assert parse(MINIMAL).size_x == 3


# --- strict validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('tileset = "grid"', 'tileset = "grid"\ntilset = "x"', r"unknown key\(s\) 'tilset'"),
        ('display_name = "Mini"', "", "display_name: missing required key"),
        ('display_name = "Mini"', "display_name = 5", "display_name: must be a non-empty string"),
        ("p2 = [2.5, 0.5]", "", r"spawns\.p2: missing required key"),
        ("p2 = [2.5, 0.5]", "p2 = [2.5]", r"spawns\.p2: must be an array of 2 numbers"),
        ("p2 = [2.5, 0.5]", 'p2 = ["a", 1]', r"spawns\.p2: must be an array of 2 numbers"),
        ("p2 = [2.5, 0.5]", "p2 = [2.5, 0.5]\np5 = [1, 1]", r"spawns: unknown key\(s\) 'p5'"),
        ("p2 = [2.5, 0.5]", "p2 = [9.5, 0.5]", "spawn p2 at .* is not on solid ground"),
        ("  000\n  000", "  000\n  00", "grid row 1 has 2 cells, expected 3"),
        ("  000\n  000", "  0X0\n  000", "unknown symbol 'X'"),
    ],
)
def test_mistakes_are_reported_with_file_and_key(old: str, new: str, message: str) -> None:
    assert old in MINIMAL
    with pytest.raises(DataError, match=r"^mini/stage\.toml: .*" + message):
        parse(MINIMAL.replace(old, new))


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("[blast_zone]\nsides = 7", r"blast_zone: unknown key\(s\) 'sides'"),
        ('[blast_zone]\nside = "wide"', r"blast_zone\.side: must be a number"),
        ("[blast_zone]\nside = true", r"blast_zone\.side: must be a number"),
        ("[camera]\nmargin = 4", r"camera: unknown key\(s\) 'margin'"),
        ('[legend]\n"ab" = { height = 0 }', r"legend\.ab: symbol must be one character"),
        ('[legend]\n"." = { height = 0 }', r"legend\.\.: symbol must be one character"),
        ('[legend]\n"0" = { hieght = 0 }', r"legend\.'0': unknown key\(s\) 'hieght'"),
        ('[legend]\n"0" = { tile = "grass" }', r"legend\.'0'\.height: missing required key"),
        ('[legend]\n"0" = { height = -1 }', r"legend\.'0'\.height: must be 0 or greater"),
        ('[legend]\n"0" = { height = 0, ledge = 1 }', r"legend\.'0'\.ledge: must be true or false"),
        (
            "[[soft_platforms]]\nrect = [0, 0, 2]\nz = 2",
            r"soft_platforms\[0\]\.rect: must be an array",
        ),
        (
            "[[soft_platforms]]\nrect = [0, 0, 1.5, 1]\nz = 2",
            r"soft_platforms\[0\]\.rect: must be whole numbers",
        ),
        (
            "[[soft_platforms]]\nrect = [0, 0, 2, 1]",
            r"soft_platforms\[0\]\.z: missing required key",
        ),
        ("[[soft_platforms]]\nrect = [0, 0, 2, 1]\nz = 0.5", "soft platform 0: z 0.5 is less than"),
        ('[[background]]\nimage = "a.png"', r"background\[0\]\.parallax: missing required key"),
        ("soft_platforms = 3", "soft_platforms: must be an array of tables"),
    ],
)
def test_optional_sections_are_validated_strictly(extra: str, message: str) -> None:
    text = extra + "\n" + MINIMAL if "=" in extra.splitlines()[0] else MINIMAL + "\n" + extra
    with pytest.raises(DataError, match=r"^mini/stage\.toml: .*" + message):
        parse(text)
