"""Tests for the offline art pipeline: palettes, animation timing and the packer.

Plan note "10 - Animation and Asset Pipeline", decisions D-045 and D-047. Uses small synthetic
render passes, so no Blender is needed.
"""

from pathlib import Path

import pytest
from PIL import Image

from isofightr.art.anims import AnimError, parse_timing
from isofightr.art.packer import (
    DEPTH_GAP,
    ID_STEP,
    PART_STEP,
    Frame,
    compose,
    pack,
    trim,
    write_sheets,
)
from isofightr.art.palettes import (
    OUTLINE_SLOT,
    TRANSPARENT_INDEX,
    PaletteError,
    load_palettes,
    parse_palettes,
    ramp_index,
)
from isofightr.data.sprite_sheet import parse_sprite_set

ROOK = load_palettes("rook")
LIT, UNLIT = 1, ROOK.materials.index(next(m for m in ROOK.materials if not m.lit)) + 1
NO_OUTLINE = ROOK.materials.index(next(m for m in ROOK.materials if not m.outline)) + 1

# --- palettes -----------------------------------------------------------------------------


def test_rook_palettes() -> None:
    assert ROOK.index_count == 1 + len(ROOK.materials) * 5
    assert [costume.name for costume in ROOK.costumes][:1] == ["Royal"]
    assert len(ROOK.costumes) == 6
    assert all(len(costume.colors()) == ROOK.index_count for costume in ROOK.costumes)
    royal, ember = ROOK.costumes[0], ROOK.costumes[1]
    skin = [m.name for m in ROOK.materials].index("skin")
    cloth = [m.name for m in ROOK.materials].index("cloth")
    assert ember.ramps[skin] == royal.ramps[skin], "later costumes inherit unlisted ramps"
    assert ember.ramps[cloth] != royal.ramps[cloth]


def test_palette_layout() -> None:
    assert ramp_index(1, 0) == 1 and ramp_index(1, OUTLINE_SLOT) == 5 and ramp_index(2, 0) == 6
    assert [ROOK.band_of(value) for value in (1.0, 0.86, 0.6, 0.2, 0.0)] == [0, 0, 1, 2, 3]


def _palettes(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "master": "resurrect64",
        "bands": [0.8, 0.5, 0.2],
        "materials": [{"name": "skin"}],
        "costumes": [{"name": "A", "skin": ["ffffff", "c7dcd0", "9babb2", "7f708a", "2e222f"]}],
    }
    data.update(changes)
    return data


def test_palettes_reject_mistakes() -> None:
    assert parse_palettes(_palettes()).index_count == 6
    with pytest.raises(PaletteError, match="not in resurrect64"):
        parse_palettes(
            _palettes(
                costumes=[{"name": "A", "skin": ["123456", "c7dcd0", "9babb2", "7f708a", "2e222f"]}]
            )
        )
    with pytest.raises(PaletteError, match="5 colours"):
        parse_palettes(_palettes(costumes=[{"name": "A", "skin": ["ffffff"]}]))
    with pytest.raises(PaletteError, match="unknown keys"):
        parse_palettes(_palettes(colour="red"))
    with pytest.raises(PaletteError, match="brightest first"):
        parse_palettes(_palettes(bands=[0.2, 0.5, 0.8]))
    with pytest.raises(PaletteError, match="first costume needs"):
        parse_palettes(_palettes(costumes=[{"name": "A"}]))


# --- animation timing ---------------------------------------------------------------------


def test_timing() -> None:
    loop = parse_timing("idle", {"loop": True, "fps": 6, "poses": [{}, {}]})
    assert loop.loop and loop.fps == 6 and loop.poses == 2
    timed = parse_timing("jab1", {"poses": [{"start": 1}, {"start": 3}, {"start": 5}]})
    assert not timed.loop and timed.starts == (1, 3, 5)
    for bad, message in (
        ({"poses": [{"start": 2}]}, "begin at 1"),
        ({"poses": [{"start": 1}, {"start": 1}]}, "increase"),
        ({"poses": [{"start": 1}, {}]}, "needs a start"),
        ({"loop": True, "poses": [{}]}, "fps"),
        ({"loop": True, "fps": 6, "poses": [{"start": 1}]}, "no start"),
        ({"fps": 6, "poses": [{"start": 1}]}, "only loops"),
        ({"poses": []}, "no poses"),
        ({"speed": 2, "poses": [{"start": 1}]}, "unknown keys"),
    ):
        with pytest.raises(AnimError, match=message):
            parse_timing("x", bad)


# --- compose ------------------------------------------------------------------------------


def _passes(
    pixels: dict[tuple[int, int], tuple[int, int, int, int]], size: tuple[int, int] = (6, 6)
) -> tuple[Image.Image, Image.Image]:
    """Build an id pass and a light pass: pixels map to (material, part, depth, light)."""
    ids = Image.new("RGBA", size, (0, 0, 0, 0))
    light = Image.new("RGBA", size, (0, 0, 0, 0))
    for (x, y), (material, part, depth, value) in pixels.items():
        ids.putpixel((x, y), (material * ID_STEP, part * PART_STEP, depth, 255))
        light.putpixel((x, y), (value, value, value, 255))
    return ids, light


def test_compose_bands_and_outer_outline() -> None:
    ids, light = _passes({(2, 2): (LIT, 1, 100, 255), (3, 2): (LIT, 1, 100, 0)})
    out = compose(ids, light, ROOK)
    assert out.getpixel((2, 2)) == ramp_index(LIT, 0), "fully lit: highlight"
    assert out.getpixel((3, 2)) == ramp_index(LIT, 3), "unlit side: shadow"
    for empty in ((1, 2), (4, 2), (2, 1), (3, 3)):
        assert out.getpixel(empty) == ramp_index(LIT, OUTLINE_SLOT), "selout around the model"
    assert out.getpixel((0, 0)) == TRANSPARENT_INDEX and out.getpixel((1, 1)) == 0


def test_unlit_and_outline_free_materials() -> None:
    ids, light = _passes({(2, 2): (UNLIT, 1, 100, 0), (4, 4): (NO_OUTLINE, 2, 100, 0)})
    out = compose(ids, light, ROOK)
    assert out.getpixel((2, 2)) == ramp_index(UNLIT, 0), "unlit materials ignore the light"
    assert out.getpixel((4, 3)) == TRANSPARENT_INDEX, "smears get no outline"


def test_interior_line_only_behind_a_nearer_part() -> None:
    near, far = 100, 100 + DEPTH_GAP + 1
    ids, light = _passes(
        {
            (2, 2): (LIT, 1, near, 255),
            (3, 2): (LIT, 2, far, 255),
            (2, 3): (LIT, 3, near + DEPTH_GAP, 255),
        }
    )
    out = compose(ids, light, ROOK)
    assert out.getpixel((3, 2)) == ramp_index(LIT, OUTLINE_SLOT), "the part behind gets a line"
    assert out.getpixel((2, 2)) == ramp_index(LIT, 0), "the part in front does not"
    assert out.getpixel((2, 3)) == ramp_index(LIT, 0), "parts that only touch get no line"


def test_compose_rejects_unknown_materials() -> None:
    ids, light = _passes({(1, 1): (30, 1, 0, 0)})
    with pytest.raises(ValueError, match="unknown material"):
        compose(ids, light, ROOK)


# --- trim and pack ------------------------------------------------------------------------


def test_trim_keeps_the_pivot() -> None:
    image = Image.new("L", (20, 20))
    image.putpixel((5, 4), 3)
    image.putpixel((8, 9), 3)
    frame = trim("a/0/E", image, (10, 12))
    assert frame.image.size == (4, 6) and frame.pivot == (5, 8)
    empty = trim("a/0/E", Image.new("L", (20, 20)), (10, 12))
    assert empty.image.size == (1, 1) and empty.pivot == (0, 0)


def test_pack_never_overlaps_and_spills_into_new_sheets() -> None:
    frames = [Frame(f"f{i}", Image.new("L", (30 + i % 7, 20 + i % 5)), (0, 0)) for i in range(40)]
    placements = pack(frames, size=100)
    assert len({placement.sheet for placement in placements}) > 1
    boxes = [
        (p.sheet, p.x, p.y, p.x + f.image.width, p.y + f.image.height)
        for f, p in zip(frames, placements, strict=True)
    ]
    for index, (sheet, left, top, right, bottom) in enumerate(boxes):
        assert right <= 100 and bottom <= 100
        for other_sheet, other_left, other_top, other_right, other_bottom in boxes[index + 1 :]:
            assert not (
                other_sheet == sheet
                and left < other_right
                and other_left < right
                and top < other_bottom
                and other_top < bottom
            )
    with pytest.raises(ValueError, match="larger than a sheet"):
        pack([Frame("big", Image.new("L", (101, 5)), (0, 0))], size=100)


def test_written_sheets_round_trip(tmp_path: Path) -> None:
    from isofightr.art.anims import AnimTiming

    image = Image.new("L", (3, 4), ramp_index(LIT, 1))
    frames = [Frame(f"idle/0/{d}", image, (1, 4)) for d in ("E", "SE")]
    data = write_sheets(
        tmp_path / "sprites", "test", frames, [AnimTiming("idle", 1, True, fps=4)], ROOK, "4.5.5"
    )
    assert data["blender"] == "4.5.5" and data["sheets"] == ["sheet_0.png"]
    sheet = Image.open(tmp_path / "sprites" / "sheet_0.png")
    assert sheet.mode == "P" and sheet.info.get("transparency") == TRANSPARENT_INDEX
    sprite_set = parse_sprite_set(data, tmp_path / "sprites")
    rect = sprite_set.frame("idle", 0, "SE")
    assert (rect.width, rect.height, rect.pivot_x, rect.pivot_y) == (3, 4, 1, 4)
    cropped = sheet.crop((rect.x, rect.y, rect.x + 3, rect.y + 4))
    assert set(cropped.getdata()) == {ramp_index(LIT, 1)}
    assert sprite_set.costumes[0][1][ramp_index(LIT, 1)] == ROOK.costumes[0].ramps[0][1]
