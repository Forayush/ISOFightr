"""Tests for the hit splash's art (decision D-068, M17 group 2): every picture of every theme
is palette-locked and centred on a pixel, the held pictures are open line art that never
hides the victim, and the directional ones point where their key says.
"""

import math

import pytest
from PIL import Image

from isofightr.art.palettes import load_master
from isofightr.render import splash_art as art

MASTER = load_master("resurrect64")
OPEN_KINDS = ("core", "lines", "ring", "flare")
"""Pictures that stay up for more than the two ticks of the burst: never more than half solid."""


def opaque(image: Image.Image) -> list[tuple[int, int]]:
    return [
        (x, y) for y in range(image.height) for x in range(image.width)
        if image.getpixel((x, y))[3]
    ]  # fmt: skip


@pytest.mark.parametrize("theme", art.THEMES)
def test_every_picture_of_a_theme_is_palette_locked_and_centred(theme: str) -> None:
    keys = art.theme_keys(theme)
    assert len(keys) == len(set(keys)), "each picture once"
    for key in keys:
        image = art.build(key)
        assert {pixel[:3] for pixel in image.getdata() if pixel[3]} <= MASTER, key
        assert image.width % 2 == 1 and image.height % 2 == 1, f"{key}: centred on a pixel"
        assert opaque(image), f"{key}: draws something"


def test_a_theme_has_every_kind_of_picture() -> None:
    kinds = {key[0] for key in art.theme_keys("slash")}
    assert kinds == {"burst", "split", "core", "lines", "particle", "ring", "flare"}
    assert len(art.theme_keys("slash")) == 391


@pytest.mark.parametrize("theme", sorted(art.DRAWN))
def test_held_pictures_are_open_line_art(theme: str) -> None:
    """Rule 3 of note 09: only the two-tick burst may be solid; what is held over the victim
    for the rest of the freeze leaves most of what is behind it showing."""
    for key in art.theme_keys(theme):
        if key[0] not in OPEN_KINDS:
            continue
        image = art.build(key)
        solid = sum(1 for pixel in image.getdata() if pixel[3] == 255)
        assert solid < image.width * image.height * 0.5, key


def screen_turn_of(points: list[tuple[int, int]], centre: float) -> float:
    """The direction on screen (counter-clockwise from right, y up) of the points' centroid."""
    mean_x = sum(x for x, _ in points) / len(points) - centre
    mean_y = sum(y for _, y in points) / len(points) - centre
    return math.atan2(-mean_y, mean_x)


def gap(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)


@pytest.mark.parametrize("theme", sorted(art.DRAWN))
@pytest.mark.parametrize("tier", range(4))
def test_the_core_and_lines_point_along_their_angle(theme: str, tier: int) -> None:
    pictures = set()
    for angle in range(art.ANGLES):
        core = art.build(("core", theme, tier, angle, 0))
        lines = art.build(("lines", theme, tier, angle))
        aim = 2.0 * math.pi * angle / art.ANGLES
        centre = (core.width - 1) / 2
        assert gap(screen_turn_of(opaque(core), centre), aim) < math.radians(30), angle
        assert gap(screen_turn_of(opaque(lines), centre), aim) < math.radians(30), angle
        pictures.add(core.tobytes())
    assert len(pictures) == art.ANGLES, "each direction is drawn, not reused"


@pytest.mark.parametrize("theme", sorted(art.DRAWN))
def test_without_a_direction_the_core_points_nowhere(theme: str) -> None:
    for tier in range(4):
        for frame in range(art.CORE_FRAMES):
            image = art.build(("core", theme, tier, -1, frame))
            points = opaque(image)
            centre = (image.width - 1) / 2
            mean_x = sum(x for x, _ in points) / len(points) - centre
            mean_y = sum(y for _, y in points) / len(points) - centre
            assert math.hypot(mean_x, mean_y) < 1.5, (tier, frame)


def test_without_a_direction_the_slash_core_is_an_even_cross() -> None:
    for tier in range(4):
        image = art.build(("core", "slash", tier, -1, 0))
        shape = image.getchannel("A").point(lambda alpha: 255 if alpha else 0)
        mirrored = shape.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        assert shape.tobytes() == mirrored.tobytes()


@pytest.mark.parametrize("theme", sorted(art.DRAWN))
def test_the_split_is_the_bursts_shape_in_two_colours(theme: str) -> None:
    for tier in (2, 3):
        for frame in range(art.BURST_FRAMES):
            first = art.build(("split", theme, tier, frame, 0))
            second = art.build(("split", theme, tier, frame, 1))
            colours = [{p[:3] for p in image.getdata() if p[3]} for image in (first, second)]
            expected = [{colour[:3]} for colour in art.split_colours(theme)]
            assert colours == expected and colours[0] != colours[1]
            assert opaque(first) == opaque(second)
            burst = set(opaque(art.build(("burst", theme, tier, frame))))
            assert set(opaque(first)) <= burst, "inside the burst's own outline"


@pytest.mark.parametrize("theme", sorted(art.DRAWN))
def test_particles_are_drawn_along_their_flight(theme: str) -> None:
    for angle in range(art.ANGLES):
        image = art.build(("particle", theme, 1, angle, 0))
        points = opaque(image)
        aim = 2.0 * math.pi * angle / art.ANGLES
        along = (math.cos(aim), -math.sin(aim))
        across = (-along[1], along[0])
        centre = (image.width - 1) / 2
        spread = [((x - centre) * along[0] + (y - centre) * along[1]) for x, y in points]
        width = [((x - centre) * across[0] + (y - centre) * across[1]) for x, y in points]
        assert max(spread) - min(spread) >= max(width) - min(width), angle


@pytest.mark.parametrize("theme", sorted(art.DRAWN))
def test_a_bigger_tier_draws_bigger(theme: str) -> None:
    drawn = [len(opaque(art.build(("burst", theme, tier, 0)))) for tier in range(4)]
    assert drawn == sorted(drawn) and len(set(drawn)) == 4
    for kind in ("core", "lines"):
        sizes = [len(opaque(art.build((kind, theme, tier, 3, 0)[: 5 if kind == "core" else 4])))
                 for tier in range(4)]  # fmt: skip
        assert sizes == sorted(sizes), kind
    rings = [art.build(("ring", theme, tier, 1)).width for tier in (2, 3)]
    assert rings[0] < rings[1], "a critical ring is wider"


def test_themes_without_art_yet_use_the_old_effects() -> None:
    assert art.has_art("slash")
    for theme in ("fire", "earth"):
        if art.has_art(theme):
            continue
        assert art.build(("burst", theme, 0, 0)).size == (19, 19), "the old 19 px spark"
