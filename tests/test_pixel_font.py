"""Unit tests for the debug pixel font (pure Pillow part)."""

from isofightr.ui.pixel_font import (
    GLYPH_ADVANCE,
    GLYPH_HEIGHT,
    GLYPH_WIDTH,
    PRINTABLE,
    build_glyph,
    text_width,
)


def test_glyphs_are_even_sized_so_sprites_stay_pixel_aligned() -> None:
    glyph = build_glyph("A")
    assert glyph.size == (GLYPH_WIDTH, GLYPH_HEIGHT)
    assert GLYPH_WIDTH % 2 == 0 and GLYPH_HEIGHT % 2 == 0


def test_every_printable_glyph_draws_something() -> None:
    assert len(PRINTABLE) == 94
    for character in PRINTABLE:
        assert build_glyph(character).getbbox() is not None, character


def test_glyph_is_white_with_a_dark_drop_shadow() -> None:
    colors = {color for _, color in build_glyph("H").getcolors()}  # type: ignore[union-attr]
    assert colors == {(0, 0, 0, 0), (255, 255, 255, 255), (16, 16, 28, 255)}


def test_text_width_uses_the_fixed_advance() -> None:
    assert text_width("") == 0
    assert text_width("x=12") == 4 * GLYPH_ADVANCE
