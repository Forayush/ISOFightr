"""The pictures of the depth aids (decision D-065) and their setting. Pure: no window."""

import tomllib
from pathlib import Path

from PIL import Image

from isofightr.render import placeholder_art as art
from isofightr.settings import DEPTH_AIDS, Settings, from_data, load_settings, save_settings

PALETTE = Path(__file__).parents[1] / "art_src" / "palettes" / "resurrect64.toml"


def opaque(image: Image.Image) -> list[tuple[int, int, int, int]]:
    return [pixel for pixel in image.convert("RGBA").getdata() if pixel[3]]


def test_the_void_ring_is_the_players_ring_broken_into_dashes() -> None:
    whole, dashed = art.build_ring(0), art.build_void_ring(0)
    assert whole.size == dashed.size == (art.SHADOW_WIDTH, art.SHADOW_HEIGHT)
    assert set(opaque(dashed)) == {art.player_color(0)}, "no shadow: nothing to fall on"
    assert set(opaque(art.build_void_ring(1))) == {art.player_color(1)}
    middle = dashed.getpixel((art.SHADOW_WIDTH // 2, art.SHADOW_HEIGHT // 2))
    assert middle[3] == 0, "hollow"
    assert art.build_ring(0, dashed=True).tobytes() == dashed.tobytes()
    assert art.build_shadow(0, 0).tobytes() != whole.tobytes(), "the ground marker has a shadow"


def test_dithering_removes_every_other_pixel() -> None:
    block = Image.new("RGBA", (6, 4), (255, 0, 0, 255))
    thinned = art.dithered(block)
    assert len(opaque(thinned)) == 12 and thinned.getpixel((0, 0))[3] == 255
    assert thinned.getpixel((1, 0))[3] == 0 and thinned.getpixel((1, 1))[3] == 255
    assert len(opaque(block)) == 24, "the original is untouched"


def test_the_height_line_is_one_pixel_wide_and_dotted() -> None:
    line = art.build_height_line(2, 48)
    assert line.size == (1, 48)
    column = [line.getpixel((0, row)) for row in range(48)]
    assert column.count(art.player_color(2)) == 24 and column.count(art.LINE_INK) == 24
    assert column[-1] == art.player_color(2), "a dot at the marker's end"
    covered = art.build_height_line(2, 48, art.COVERED_LINE_STEP)
    assert len(opaque(covered)) == 12, "thinner, and no ink, where the stage is in front"
    assert art.build_height_line(0, 0).size == (1, 1)


def test_the_outline_is_a_ring_of_the_players_colour_round_the_picture() -> None:
    body = Image.new("RGBA", (6, 8), (0, 0, 0, 0))
    body.paste((10, 200, 10, 255), (1, 1, 5, 7))
    outline = art.build_outline(body, 1)
    assert outline.size == (8, 10)
    solid = [pixel for pixel in outline.getdata() if pixel[3] == 255]
    assert solid and set(solid) == {art.player_color(1)}
    inside = outline.getpixel((3, 4))
    assert inside[:3] == (10, 200, 10) and inside[3] == art.OUTLINE_FILL_ALPHA, "faint inside"
    assert outline.getpixel((0, 0))[3] == 0


def test_the_plane_grid_outlines_only_the_empty_cells() -> None:
    size = 2 * art.PLANE_GRID_RADIUS + 1
    empty = tuple(tuple(True for _ in range(size)) for _ in range(size))
    full = tuple(tuple(False for _ in range(size)) for _ in range(size))
    grid = art.build_plane_grid(empty)
    assert grid.size == (size * 32, size * 16)
    assert set(opaque(grid)) == {art.PLANE_GRID_COLOR}
    assert not opaque(art.build_plane_grid(full)), "solid ground gets no grid"
    half = tuple(tuple(column < size // 2 for column in range(size)) for _ in range(size))
    assert 0 < len(opaque(art.build_plane_grid(half))) < len(opaque(grid))


def test_the_new_colours_are_palette_entries() -> None:
    colours = set(tomllib.loads(PALETTE.read_text(encoding="utf-8"))["colors"])
    for colour in (art.PLANE_GRID_COLOR, art.LINE_INK, *art.PLAYER_COLORS):
        assert f"{colour[0]:02x}{colour[1]:02x}{colour[2]:02x}" in colours


def test_the_depth_aids_setting_is_saved_and_a_bad_value_falls_back(tmp_path: Path) -> None:
    assert DEPTH_AIDS == ("off", "standard", "strong") and Settings().depth_aids == "standard"
    for value in DEPTH_AIDS:
        path = tmp_path / f"{value}.toml"
        save_settings(path, from_data({"video": {"depth_aids": value}}))
        assert load_settings(path).depth_aids == value
    assert from_data({"video": {"depth_aids": "loud"}}).depth_aids == "standard"
    assert from_data({"video": {"depth_aids": 3}}).depth_aids == "standard"
    assert from_data({}).depth_aids == "standard", "a file from before the setting"
