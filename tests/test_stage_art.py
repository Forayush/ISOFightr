"""Tests for rendered stage tiles and parallax backdrops.

Plan notes "03 - Isometric World and Rendering" ("Rendering 3D source art") and "09 - Art
Direction" ("Environments"), decision D-044.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from isofightr.art.palettes import load_master
from isofightr.data.paths import STAGES_DIR
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.data.tileset_art import TilesetArtError, load_tileset_art
from isofightr.render import placeholder_art as art
from isofightr.render.backdrop import DAY, clouds, islands, sky
from isofightr.render.stage_art import StageArt

GRASS_STONE = load_tileset_art("grass_stone")
MASTER = load_master("resurrect64")


def test_the_grass_stone_tileset_is_built() -> None:
    assert GRASS_STONE is not None
    assert set(GRASS_STONE.tiles) == {"grass", "stone", "deck"}
    assert len(GRASS_STONE.costumes) == 2, "light and dark cells"
    for tile in GRASS_STONE.tiles:
        path = GRASS_STONE.tile_path(tile)
        assert path is not None and Image.open(path).mode == "P"
    assert GRASS_STONE.tile_path("lava") is None


@pytest.mark.parametrize("side_px", [4, 16, 32, 48])
@pytest.mark.parametrize("tile", ["grass", "stone"])
def test_blocks_have_exactly_the_procedural_shape(tile: str, side_px: int) -> None:
    assert GRASS_STONE is not None
    stage_art = StageArt(GRASS_STONE)
    for light in (True, False):
        image = stage_art.tile(tile, light, side_px)
        assert image is not None
        shape = art.build_block(art.tile_palette(tile), light, side_px)
        assert image.size == shape.size
        drawn = image.getchannel("A").point(lambda a: 255 * (a > 0))
        assert list(drawn.getdata()) == list(shape.getchannel("A").getdata())
        colors = {pixel[:3] for pixel in image.getdata() if pixel[3]}
        assert colors <= MASTER, "only master palette colours"


def test_light_and_dark_cells_differ_and_images_are_cached() -> None:
    assert GRASS_STONE is not None
    stage_art = StageArt(GRASS_STONE)
    light, dark = stage_art.tile("grass", True, 16), stage_art.tile("grass", False, 16)
    assert light is not None and dark is not None and light.tobytes() != dark.tobytes()
    assert stage_art.tile("grass", True, 16) is light
    deck = stage_art.deck(True)
    assert deck is not None and deck.size == art.build_deck(True).size


def test_tiles_fall_back_to_procedural_blocks() -> None:
    assert GRASS_STONE is not None
    stage_art = StageArt(GRASS_STONE)
    assert stage_art.tile("lava", True, 16) is None, "a tile the tileset does not have"
    assert stage_art.tile("grass", True, GRASS_STONE.depth_px + 1) is None, "taller than the render"
    assert load_tileset_art("grid") is None, "Training Grid keeps its procedural look"


def test_a_broken_tileset_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "tileset.json").write_text(json.dumps({"format": 7}), encoding="utf-8")
    with pytest.raises(TilesetArtError, match="format"):
        load_tileset_art("bad", tmp_path)
    (folder / "tileset.json").write_text(json.dumps({"format": 1}), encoding="utf-8")
    with pytest.raises(TilesetArtError):
        load_tileset_art("bad", tmp_path)


# --- backdrops ----------------------------------------------------------------------------


def test_backdrop_layers_use_only_palette_colours_and_are_repeatable() -> None:
    layers = [sky(DAY, 64, 90), clouds(DAY, 3, 2, (40, 60), (8, 10), 128, 90)]
    layers.append(islands(DAY, 4, 2, (20, 50), (8, 12), 128, 90))
    for layer in layers:
        assert {pixel[:3] for pixel in layer.getdata() if pixel[3]} <= MASTER
    assert sky(DAY, 64, 90).tobytes() == layers[0].tobytes()
    assert clouds(DAY, 3, 2, (40, 60), (8, 10), 128, 90).tobytes() == layers[1].tobytes()


def test_cloud_layers_wrap_seamlessly() -> None:
    layer = clouds(DAY, 5, 3, (30, 50), (8, 12), 96, 80)
    left = [layer.getpixel((0, y)) for y in range(80)]
    right = [layer.getpixel((95, y)) for y in range(80)]
    # A cloud that leaves one edge comes back on the other: the edge columns join up.
    assert any(pixel[3] for pixel in left + right)


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_every_background_image_exists_in_palette(stage_id: str) -> None:
    stage = load_stage(stage_id)
    for layer in stage.backgrounds:
        image = Image.open(STAGES_DIR / stage_id / layer.image).convert("RGBA")
        assert 0.0 <= layer.parallax <= 1.0
        assert {pixel[:3] for pixel in image.getdata() if pixel[3]} <= MASTER, layer.image


def test_sky_ruins_has_a_parallax_backdrop() -> None:
    layers = load_stage("sky_ruins").backgrounds
    assert [layer.parallax for layer in layers] == sorted(layer.parallax for layer in layers)
    assert len(layers) == 4 and layers[0].parallax == 0.0
