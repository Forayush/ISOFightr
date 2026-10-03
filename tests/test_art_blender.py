"""Tests that run Blender (``pytest -m blender``; skipped without a Blender install).

Plan note "03 - Isometric World and Rendering" ("Rendering 3D source art") and decision D-044:
the render camera must reproduce the game's projection, and a build must be reproducible.
"""

from pathlib import Path

import pytest
from PIL import Image

from isofightr.art.blender import (
    PIVOT,
    RenderJob,
    find_blender,
    render,
    run_script,
)
from isofightr.art.packer import compose, trim
from isofightr.art.palettes import ART_SRC, load_palettes
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.render import placeholder_art as art
from isofightr.sim.input_frame import Dir8

pytestmark = [
    pytest.mark.blender,
    pytest.mark.skipif(find_blender() is None, reason="Blender is not installed"),
]


def _opaque(image: Image.Image, x: int, y: int) -> bool:
    return image.getchannel("A").getpixel((x, y)) > 0


def test_render_camera_matches_the_game_projection(tmp_path: Path) -> None:
    blender = find_blender()
    assert blender is not None
    out = tmp_path / "spike"
    run_script(blender, "render_spike.py", out)  # its argument is the output folder

    # A unit block: the game's diamond-and-sides sprite, its top corner on the pivot.
    rendered = Image.open(out / "block_id.png")
    game = Image.new("RGBA", rendered.size)
    game.paste(art.build_block(art.tile_palette("grass"), True, 16), (PIVOT[0] - 16, PIVOT[1]))
    assert rendered.getchannel("A").getbbox() == game.getchannel("A").getbbox()
    differ = [
        (x, y)
        for y in range(rendered.height)
        for x in range(rendered.width)
        if _opaque(rendered, x, y) != _opaque(game, x, y)
    ]
    # Only the stair-step pixels of the four slanted edges may differ (the exact edge passes
    # through their centres), and only where the game draws and the render does not.
    assert len(differ) <= 32
    assert all(_opaque(game, x, y) and not _opaque(rendered, x, y) for x, y in differ)

    # Rook's body (radius 0.30, 2.5 units): as wide as the placeholder capsule, and 40 px tall
    # down its middle, plus the ends of its round caps.
    body = Image.open(out / "capsule_id.png").getchannel("A").getbbox()
    assert body is not None
    left, top, right, bottom = body
    assert (left, right) == (PIVOT[0] - art.BODY_HALF_WIDTH, PIVOT[0] + art.BODY_HALF_WIDTH)
    assert 0 <= bottom - top - art.BODY_HEIGHT <= 8


def test_a_rebuild_reproduces_the_committed_sheet(tmp_path: Path) -> None:
    blender = find_blender()
    assert blender is not None
    palettes = load_palettes("rook")
    sprite_set = load_sprite_set("rook")
    assert sprite_set is not None
    job = RenderJob(
        "rook",
        ART_SRC / "characters" / "rook" / "rig.toml",
        ART_SRC / "characters" / "rook" / "poses.toml",
        tuple(material.name for material in palettes.materials),
        {"idle": ART_SRC / "characters" / "rook" / "anims" / "idle.toml"},
        tmp_path,
    )
    assert render(blender, job) == ["idle"]
    assert render(blender, job) == [], "unchanged inputs are not rendered again"
    sheets = [Image.open(sprite_set.folder / name) for name in sprite_set.sheets]
    for facing in Dir8:
        stem = tmp_path / "idle" / f"00_{facing.name}"
        frame = trim(
            f"idle/0/{facing.name}",
            compose(Image.open(f"{stem}_id.png"), Image.open(f"{stem}_light.png"), palettes),
            PIVOT,
        )
        rect = sprite_set.frame("idle", 0, facing.name)
        committed = sheets[rect.sheet].crop(
            (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height)
        )
        assert frame.pivot == (rect.pivot_x, rect.pivot_y), facing
        assert list(frame.image.getdata()) == list(committed.getdata()), facing
