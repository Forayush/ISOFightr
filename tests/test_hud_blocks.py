"""The battle HUD in the block kit (decision D-072, M21 group 7): the cards are ink blocks with
the player's colours on a name band and a lip, and every word on them is readable."""

from __future__ import annotations

import pytest

from isofightr.ui import hud_art, hud_layout, theme
from test_block_kit import contrast

WIDTH, HEIGHT = hud_layout.CARD_WIDTH, hud_layout.CARD_HEIGHT


def pixel(image, x: int, y_from_bottom: int) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    """The colour at a card-relative point, y counted up from the card's bottom as the HUD
    lays things out."""
    return image.getpixel((x, image.height - 1 - y_from_bottom))[:3]


@pytest.mark.parametrize("player", range(4))
def test_a_card_is_an_ink_block_with_its_players_band_and_lip(player: int) -> None:
    ramp = theme.player_ramp(player)
    image = hud_art.card(WIDTH, HEIGHT, ramp)
    assert image.size == (WIDTH, HEIGHT)
    name_row = hud_layout.NAME_BOTTOM + 3
    assert pixel(image, hud_art.BAND_LEFT + 10, name_row) == ramp[0], "the name band"
    assert pixel(image, WIDTH // 2, 1) == ramp[2], "the lip, in the player's dark shade"
    assert pixel(image, WIDTH - hud_art.WELL_RIGHT - 10, 10) == theme.INK, "the number's well"
    assert pixel(image, hud_layout.BUST.left - 2, 20) == theme.NIGHT, "the ink face"


def test_a_lit_card_has_a_white_outline_and_a_launch_paints_the_attackers_colours() -> None:
    ramp, attacker = theme.player_ramp(0), theme.player_ramp(1)
    still = hud_art.card(WIDTH, HEIGHT, ramp)
    lit = hud_art.card(WIDTH, HEIGHT, ramp, lit=True)
    accent = hud_art.card(WIDTH, HEIGHT, ramp, accent=attacker)
    middle = HEIGHT - 1 - 20
    assert still.getpixel((0, middle))[:3] == theme.INK
    assert lit.getpixel((0, middle))[:3] == theme.WHITE
    assert accent.getpixel((0, middle))[:3] == attacker[1]
    assert pixel(accent, hud_art.BAND_LEFT + 10, hud_layout.NAME_BOTTOM + 3) == attacker[0]


def test_the_words_on_a_card_are_readable() -> None:
    """Ink names on every player's band (4.5:1), and the damage number on its well: the
    number is 30 px display lettering, large text, whose bar is 3:1. Past 150% plan note 09's
    ramp darkens toward dark red, below that bar on ink by design; the percent's look is a
    later entry of its own (D-068, D-072's open point), so it is left as it is."""
    for index in range(len(theme.PLAYER_RAMPS)):
        assert contrast(theme.INK, theme.player_ramp(index)[0]) >= 4.5
    for percent in range(0, 151, 5):
        assert contrast(hud_layout.damage_color(percent), theme.INK) >= 3.0, percent


@pytest.mark.parametrize(
    "picture",
    [
        lambda: hud_art.clock_plate(60, 18),
        lambda: hud_art.clock_plate(60, 18, alarm=True, glow=True),
        lambda: hud_art.feed_row(120, 14, theme.RED),
        lambda: hud_art.combo_plate(60, 16),
    ],
)
def test_the_small_plates_are_blocks_with_a_lip(picture) -> None:  # type: ignore[no-untyped-def]
    image = picture()
    column = image.width // 2
    bottom = [image.getpixel((column, image.height - 1 - row)) for row in range(4)]
    assert bottom[0][3] == 255 and bottom[0][:3] == theme.INK, "the outline under the lip"
    lip = bottom[1][:3]
    assert lip in {theme.INK, theme.MAROON, theme.AMBER}, "a lip under the face"
