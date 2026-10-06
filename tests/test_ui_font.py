"""The game's pixel font (plan note 13, decision D-061): sizes, coverage and the fallback."""

from pathlib import Path

import pytest

from isofightr.ui import font, theme
from isofightr.ui.font import ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT, ARROW_UP, PRINTABLE, TextSize

CAP_HEIGHTS = {
    TextSize.SMALL: 5,
    TextSize.BODY: 8,
    TextSize.TITLE: 12,
    TextSize.DISPLAY: 16,
    TextSize.NUMERAL: 16,
}


def test_every_size_loads_its_own_font_file_with_a_licence_beside_it() -> None:
    assert not font.using_fallback()
    for name in font.FONT_FILES:
        assert (font.FONTS_DIR / name).is_file()
    licences = [path.read_text(encoding="utf-8") for path in font.FONTS_DIR.glob("*-OFL.txt")]
    families = {name.split("-")[0].rstrip("0123456789") for name in font.FONT_FILES}
    assert len(licences) == len(families) == 3, "one licence file per font family"
    for text in licences:
        assert "SIL Open Font License, Version 1.1" in text and "Copyright" in text
    credits = (font.FONTS_DIR.parent / "CREDITS.md").read_text(encoding="utf-8")
    for family in ("Departure Mono", "Jersey", "Tiny5"):
        assert family in credits


@pytest.mark.parametrize("size", list(TextSize))
def test_capital_heights_are_the_sizes_the_theme_is_built_on(size: TextSize) -> None:
    assert font.cap_height(size) == CAP_HEIGHTS[size]
    face = font.face(size)
    assert face.height == font.line_height(size) == face.baseline + face.descent
    assert 0 < face.descent < face.cap_height


@pytest.mark.parametrize("size", list(TextSize))
def test_every_printable_character_and_arrow_has_a_glyph(size: TextSize) -> None:
    for character in PRINTABLE + font.ARROWS:
        mask = font.mask(character, size)
        assert mask.getbbox() is not None, f"{character!r} draws nothing at {size.value}"
        assert mask.size == (font.text_width(character, size), font.line_height(size))
        assert set(mask.getdata()) <= {0, 255}, "anti-aliasing must be off"
    assert font.mask("7", size).tobytes() != font.mask("1", size).tobytes()
    assert font.mask(" ", size).getbbox() is None and font.text_width(" ", size) > 0


@pytest.mark.parametrize("size", list(TextSize))
def test_a_line_is_as_wide_as_its_characters_one_by_one(size: TextSize) -> None:
    """Labels place one sprite per character, so there must be no kerning to lose."""
    for text in ("AVATAR To. Yo, WAVE 1.0x", "jab x/y (3:00) 87%", f"{ARROW_LEFT} 3 {ARROW_RIGHT}"):
        assert font.text_width(text, size) == sum(font.text_width(c, size) for c in text)
        assert font.mask(text, size).width == font.text_width(text, size)


def test_body_text_is_fixed_width() -> None:
    widths = {font.text_width(character, TextSize.BODY) for character in PRINTABLE}
    assert widths == {7}


def test_capitals_always_start_on_the_same_row() -> None:
    for size in TextSize:
        face = font.face(size)
        for text in ("H", "Hg", "Ho|", "x"):
            box = font.mask(text, size).getbbox()
            assert (box is not None and box[1] <= face.cap_top) or text == "x"
        box = font.mask("HEX", size).getbbox()
        assert box is not None
        assert (box[1], box[3]) == (face.cap_top, face.baseline), "from cap line to baseline"
        low = font.mask("g", size).getbbox()
        assert low is not None and low[3] > face.baseline, "descenders hang below it"


def test_render_is_solid_colour_with_an_ink_shadow() -> None:
    image = font.render("Rook 87%", TextSize.TITLE, theme.GOLD)
    assert image.size == (
        font.text_width("Rook 87%", TextSize.TITLE) + 1,
        font.line_height(TextSize.TITLE) + 1,
    )
    colours = set(image.getdata())
    assert colours == {(*theme.GOLD, 255), theme.TEXT_SHADOW, (0, 0, 0, 0)}
    plain = font.render("Rook 87%", TextSize.TITLE, theme.GOLD, shadow=None)
    assert plain.size == (image.width - 1, image.height - 1)
    assert set(plain.getdata()) == {(*theme.GOLD, 255), (0, 0, 0, 0)}


def test_arrows_point_the_way_they_say() -> None:
    def weight(character: str) -> tuple[float, float]:
        mask = font.mask(character, TextSize.BODY)
        points = [
            (x, y) for y in range(mask.height) for x in range(mask.width) if mask.getpixel((x, y))
        ]
        box = mask.getbbox()
        assert box is not None
        return (
            sum(x for x, _ in points) / len(points) - (box[0] + box[2] - 1) / 2,
            sum(y for _, y in points) / len(points) - (box[1] + box[3] - 1) / 2,
        )

    assert weight(ARROW_RIGHT)[0] < 0 < weight(ARROW_LEFT)[0], "the wide end is behind the tip"
    assert weight(ARROW_DOWN)[1] < 0 < weight(ARROW_UP)[1]
    assert weight(ARROW_RIGHT)[1] == pytest.approx(0) and weight(ARROW_UP)[0] == pytest.approx(0)


def test_a_missing_font_file_falls_back_to_the_built_in_font(tmp_path: Path) -> None:
    assert font.using_fallback(tmp_path)
    for size in TextSize:
        face = font.face(size, tmp_path)
        assert face.fallback and face.cap_height > 0
        image = font.render("Stock 3 87%", size, fonts_dir=tmp_path)
        assert image.getbbox() is not None, "text still draws"
        assert font.mask("Stock", size, tmp_path).width == font.text_width("Stock", size, tmp_path)
    small, big = font.face(TextSize.BODY, tmp_path), font.face(TextSize.NUMERAL, tmp_path)
    assert big.cap_height == small.cap_height * 3, "enlarged by whole numbers only"
    assert not font.using_fallback(), "the real fonts are untouched"


def test_fit_shortens_and_wrap_breaks_at_spaces() -> None:
    text = "A mossy stone golem. Slow, huge reach."
    assert font.fit(text, 1000) == text
    short = font.fit(text, 80)
    assert short.endswith(font.ELLIPSIS) and font.text_width(short) <= 80
    lines = font.wrap(text, 120)
    assert " ".join(lines) == text and len(lines) > 1
    assert all(font.text_width(line) <= 120 for line in lines)
    assert font.wrap("Supercalifragilistic", 20) == ["Supercalifragilistic"]
    assert font.wrap("one\ntwo", 500) == ["one", "two"]
