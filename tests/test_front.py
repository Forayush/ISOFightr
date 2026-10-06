"""The logo and the loading screen's tips (plan note 13, decision D-061, M13 group 3).

Pure: no window. The screens themselves are driven in ``tests/test_front_gl.py``.
"""

from PIL import Image

from isofightr.settings import Settings
from isofightr.ui import font, logo, theme
from isofightr.ui.hints import device_labels
from isofightr.ui.tips import TIP_PREFIX, TIP_TICKS, TIPS, tip_at

SOLO = device_labels(Settings(), "keyboard:solo")
PAD = device_labels(Settings(), "pad:0")
LINE_WIDTH = 500
"""A tip must fit on the loading screen's line."""


# --- logo ------------------------------------------------------------------------------------


def test_the_logo_is_the_games_name_in_palette_colours() -> None:
    image = logo.build_logo()
    assert logo.LOGO_TEXT == "ISOFIGHTR"
    assert image.size == logo.logo_size() and image.mode == "RGBA"
    assert 300 <= image.width <= 400 and 40 <= image.height <= 70, "it fits the title's top"
    colours = {pixel[:3] for pixel in image.getdata() if pixel[3]}
    assert colours == {logo.FACE, logo.FACE_LIGHT, logo.SIDE, logo.SIDE_DEEP, logo.EDGE}
    assert colours <= set(theme.PALETTE)
    assert {pixel[3] for pixel in image.getdata()} == {0, 255}, "no soft edges"
    assert image.getpixel((0, 0))[3] == 0


def test_the_letters_are_whole_pixels_of_the_display_font_enlarged() -> None:
    mask = logo.letter_mask("IO")
    scale = logo.LETTER_SCALE
    nearest = Image.Resampling.NEAREST
    assert mask.height == font.cap_height(font.TextSize.DISPLAY) * scale
    small = mask.resize((mask.width // scale, mask.height // scale), nearest)
    assert small.resize(mask.size, nearest).tobytes() == mask.tobytes(), "3x3 blocks only"
    assert logo.letter_mask("I").width < logo.letter_mask("IO").width


def _pixels(image: Image.Image, colours: tuple[tuple[int, int, int], ...]) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if image.getpixel((x, y))[3] and image.getpixel((x, y))[:3] in colours
    ]


def test_the_depth_runs_down_and_to_the_right_two_across_for_one_down() -> None:
    image = logo.build_logo("I")
    face = _pixels(image, (logo.FACE, logo.FACE_LIGHT))
    side = _pixels(image, (logo.SIDE, logo.SIDE_DEEP))
    assert face and side
    assert max(x for x, _ in side) - max(x for x, _ in face) == 2 * logo.DEPTH
    assert max(y for _, y in side) - max(y for _, y in face) == logo.DEPTH
    assert min(x for x, _ in side) > min(x for x, _ in face), "nothing sticks out on the left"
    near = _pixels(image, (logo.SIDE,))
    far = _pixels(image, (logo.SIDE_DEEP,))
    assert max(y for _, y in far) > max(y for _, y in near), "the far band is the deeper one"
    assert logo.build_logo("I").tobytes() == image.tobytes(), "always the same picture"


# --- tips ------------------------------------------------------------------------------------


def test_every_tip_fits_its_line_on_any_device() -> None:
    assert len(TIPS) >= 10 and len(set(TIPS)) == len(TIPS)
    for index in range(len(TIPS)):
        for labels in (SOLO, PAD, device_labels(Settings(), "keyboard:arrows")):
            text = tip_at(index, 0, labels)
            assert text.startswith(TIP_PREFIX) and "{" not in text and "}" not in text
            assert font.text_width(text) <= LINE_WIDTH, text


def test_tips_name_the_readers_own_controls() -> None:
    first = next(index for index, tip in enumerate(TIPS) if "{jump}" in tip and "{attack}" in tip)
    assert tip_at(first, 0, SOLO) == "TIP: SPACE and J together: a short-hop aerial."
    assert tip_at(first, 0, PAD) == "TIP: X/Y and A together: a short-hop aerial."
    rebound = device_labels(Settings().with_key("solo", "attack", "F"), "keyboard:solo")
    assert "SPACE and F" in tip_at(first, 0, rebound)
    topics = " ".join(TIPS).lower()
    for word in ("short-hop", "tech", "sdi", "di", "smash", "recovery"):
        assert word in topics, f"no tip mentions {word}"


def test_tips_rotate_with_time_and_start_where_they_are_told() -> None:
    assert tip_at(0, 0, SOLO) == tip_at(0, TIP_TICKS - 1, SOLO)
    assert tip_at(0, TIP_TICKS, SOLO) == tip_at(1, 0, SOLO) != tip_at(0, 0, SOLO)
    assert tip_at(len(TIPS) - 1, TIP_TICKS, SOLO) == tip_at(0, 0, SOLO), "it wraps"
    assert tip_at(3, -5, SOLO) == tip_at(3, 0, SOLO)
    assert tip_at(len(TIPS) + 2, 0, SOLO) == tip_at(2, 0, SOLO)
