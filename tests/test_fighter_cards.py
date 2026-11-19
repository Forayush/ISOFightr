"""The Fighters screen's model and art: archetype colours, what a card says, its layout,
pages and the cursor (decision D-077).

Pure: no window. The screen itself is driven in ``tests/test_fighters_gl.py``.
"""

import itertools
import tomllib
from dataclasses import replace

import pytest
from PIL import Image

from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.move_loader import parse_move
from isofightr.data.paths import CHARACTERS_DIR, REPO_ROOT
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.data.validation import DataError
from isofightr.render.placeholder_art import NO_PLAYER, build_shadow
from isofightr.scenes import fighter_cards as cards
from isofightr.scenes.fighter_cards import (
    CARD_HEIGHT,
    CARD_WIDTH,
    DESCRIPTION_LINES,
    PER_PAGE,
    SPECIAL_SLOTS,
    TEXT_WIDTH,
    archetype_colours,
    card_layout,
    card_rect,
    fighter_cards,
    move_focus,
    on_page,
    page_count,
    page_of,
    swatch_rects,
)
from isofightr.scenes.menu_world_model import (
    RING_SPOTS,
    STATIONS,
    rest_pose,
    screen_point,
)
from isofightr.scenes.roster_model import (
    STAT_FLOOR,
    STAT_NAMES,
    costume_colors,
    costume_swatches,
)
from isofightr.ui import card_art, font, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.menu import MenuAction

PALETTE_FILE = REPO_ROOT / "art_src" / "palettes" / "resurrect64.toml"
MIN_CONTRAST = 4.5
ROSTER = [load_character(name) for name in list_character_ids()]
CARDS = {card.id: card for card in fighter_cards(ROSTER)}
LAYOUT = card_layout()


def resurrect64() -> set[tuple[int, int, int]]:
    with PALETTE_FILE.open("rb") as file:
        return {theme.rgb(value) for value in tomllib.load(file)["colors"]}


def colours(image: Image.Image) -> set[tuple[int, int, int]]:
    return {pixel[:3] for pixel in image.convert("RGBA").getdata() if pixel[3] > 0}


def contrast(first: tuple[int, ...], second: tuple[int, ...]) -> float:
    def luminance(colour: tuple[int, ...]) -> float:
        def channel(value: int) -> float:
            share = value / 255
            return share / 12.92 if share <= 0.04045 else ((share + 0.055) / 1.055) ** 2.4

        red, green, blue = (channel(value) for value in colour[:3])
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# --- the data ----------------------------------------------------------------------------------


@pytest.mark.parametrize("character", ROSTER, ids=lambda character: character.id)
def test_every_character_has_a_description_and_named_specials(character: object) -> None:
    """A new character needs both (decision D-077)."""
    assert character.description.endswith(".") and len(character.description) >= 40
    assert character.description != character.blurb, "the card says more than the strip"
    for slot in SPECIAL_SLOTS:
        move = character.moves[getattr(character.moveset, slot)]
        assert move.name and move.name[0].isupper(), f"{slot} of {character.id} has no name"


def test_description_and_name_are_optional_text_keys() -> None:
    from isofightr.data.character_loader import parse_character

    rook = load_character("rook")
    with (CHARACTERS_DIR / "rook" / "fighter.toml").open("rb") as file:
        data = tomllib.load(file)
    del data["description"]
    assert parse_character(data, moves=rook.moves, source="test").description == ""
    with pytest.raises(DataError):
        parse_character({**data, "description": 3}, moves=rook.moves, source="test")
    move: dict[str, object] = {"id": "jab", "kind": "jab", "total": 10, "faf": 11}
    assert parse_move(move, source="jab.toml").name == ""
    assert parse_move({**move, "name": "Poke"}, source="jab.toml").name == "Poke"
    with pytest.raises(DataError):
        parse_move({**move, "name": 3}, source="jab.toml")
    with pytest.raises(DataError):
        parse_move({**move, "name": ""}, source="jab.toml")


def test_the_text_keys_change_nothing_the_sim_reads() -> None:
    """Text only: characters that differ only in them play the same match to the bit."""
    from isofightr.ai.random_inputs import random_inputs
    from isofightr.data.stage_loader import load_stage
    from isofightr.sim.match import Match, MatchRules

    def plain(character_id: str) -> object:
        character = load_character(character_id)
        moves = {key: replace(move, name="") for key, move in character.moves.items()}
        return replace(character, description="", moves=moves)

    inputs = random_inputs(seed=7, frames=900, players=4)
    hashes = []
    for build in (load_character, plain):
        match = Match.create(
            load_stage("sky_ruins"),
            [build(name) for name in ("rook", "bramble", "zephyr", "mote")],
            seed=4,
            rules=MatchRules(stocks=None),
        )
        for frames in inputs:
            match.tick(frames)
        hashes.append(match.state_hash())
    assert hashes[0] == hashes[1]


# --- archetype colours -------------------------------------------------------------------------


def test_every_archetype_on_the_roster_has_its_own_colours() -> None:
    looks = [archetype_colours(character.archetype) for character in ROSTER]
    assert all(look is not theme.UNKNOWN_ARCHETYPE for look in looks)
    assert all(
        look.label in {each.label for each in theme.ARCHETYPE_COLOURS.values()} for look in looks
    )
    assert len({look.ramp[1] for look in looks}) == len(looks), "one colour per archetype"


def test_the_archetype_colours_are_the_ones_agreed() -> None:
    """Teal, clay, magenta and violet (the user's choice, 2026-11-20)."""
    bases = {key: look.ramp[1] for key, look in theme.ARCHETYPE_COLOURS.items()}
    assert bases == {
        "all-rounder": theme.rgb("0eaf9b"),
        "heavyweight": theme.rgb("cd683d"),
        "rushdown": theme.rgb("f04f78"),
        "zoner": theme.rgb("905ea9"),
    }
    players = set(theme.PLAYER_COLORS) | {theme.FOCUS}
    assert not players & set(bases.values()), "never a player's colour or the focus gold"


@pytest.mark.parametrize(
    "look",
    [*theme.ARCHETYPE_COLOURS.values(), theme.UNKNOWN_ARCHETYPE],
    ids=lambda look: look.label,
)
def test_archetype_colours_are_the_palette_and_their_band_text_reads(look: object) -> None:
    palette = resurrect64()
    assert {*look.ramp, look.band, look.band_text} <= palette
    assert look.band in look.ramp
    assert contrast(look.band, look.band_text) >= MIN_CONTRAST


def test_an_archetype_is_looked_up_without_its_article_and_case() -> None:
    assert archetype_colours("the all-rounder") is theme.ARCHETYPE_COLOURS["all-rounder"]
    assert archetype_colours("  The Zoner ") is theme.ARCHETYPE_COLOURS["zoner"]
    odd = archetype_colours("the trickster")
    assert odd.ramp == theme.EMPTY_RAMP and odd.label == "Trickster"
    assert archetype_colours("").label == theme.UNKNOWN_ARCHETYPE.label


# --- what a card says ----------------------------------------------------------------------------


@pytest.mark.parametrize("character", ROSTER, ids=lambda character: character.id)
def test_a_card_says_it_all_and_every_line_fits(character: object) -> None:
    card = CARDS[character.id]
    assert card.name == character.display_name
    joined = " ".join(card.description)
    assert joined == character.description, "the whole description, in its lines"
    assert 1 <= len(card.description) <= DESCRIPTION_LINES
    for line in card.description:
        assert font.text_width(line, TextSize.TEXT) <= TEXT_WIDTH
    assert font.text_width(card.name, TextSize.TITLE) <= TEXT_WIDTH
    for line, box in zip(card.specials, LAYOUT.specials, strict=True):
        assert font.text_width(line, TextSize.SMALL) <= box.width, line
    for stat, row in zip(STAT_NAMES, LAYOUT.stats, strict=True):
        word = cards.STAT_WORDS[stat]
        assert font.text_width(word, TextSize.SMALL) <= LAYOUT.label(row).width
        assert font.text_width(card.figures[stat], TextSize.SMALL) <= LAYOUT.figure(row).width
        assert STAT_FLOOR <= card.stats[stat] <= 1.0
    assert font.text_width(card.facts, TextSize.SMALL) <= LAYOUT.facts.width
    swatches = swatch_rects(len(load_sprite_set(character.id).costumes), LAYOUT)
    label = font.text_width(card.colours.label, TextSize.TEXT)
    assert LAYOUT.band.left + cards.INSET + label + 4 <= swatches[0].left, "label clear of chips"


def test_the_figures_are_real_numbers() -> None:
    """Weight as it is, speeds in tiles a second, power as a percent."""
    rook = CARDS["rook"]
    assert rook.figures["weight"] == "98"
    assert rook.figures["speed"] == "7.5"
    assert rook.figures["air"] == "5.0"
    assert rook.figures["power"].endswith("%") and rook.figures["power"][:-1].isdigit()
    assert CARDS["zephyr"].facts == "Air jumps 2   Jumpsquat 3f"


def test_specials_are_listed_neutral_side_up_down_with_their_marks() -> None:
    rook = CARDS["rook"]
    assert rook.specials == (
        "• Crescent Wave",
        f"{font.ARROW_RIGHT} Lunge",
        f"{font.ARROW_UP} Rising Spin",
        f"{font.ARROW_DOWN} Riposte",
    )
    unnamed = load_character("rook")
    unnamed = replace(unnamed, moves={k: replace(m, name="") for k, m in unnamed.moves.items()})
    assert cards.special_lines(unnamed)[0] == "• Neutral special"


def test_a_description_too_long_for_the_card_is_cut_short() -> None:
    lines = cards.description_lines("word " * 200)
    assert len(lines) == DESCRIPTION_LINES
    assert all(font.text_width(line, TextSize.TEXT) <= TEXT_WIDTH for line in lines)
    assert cards.description_lines("") == ()


def test_the_costume_colours_are_character_selects() -> None:
    sprites = load_sprite_set("bramble")
    assert sprites is not None
    shown = costume_colors(sprites)
    assert len(shown) == len(sprites.costumes)
    assert shown != costume_swatches(sprites.costumes), "weighted by the hero picture"


# --- layout --------------------------------------------------------------------------------------


def boxes() -> list[Rect]:
    return [
        LAYOUT.band,
        LAYOUT.name,
        *LAYOUT.description,
        *LAYOUT.specials,
        *(
            part(row)
            for row in LAYOUT.stats
            for part in (LAYOUT.label, LAYOUT.gauge, LAYOUT.figure)
        ),
        LAYOUT.facts,
    ]


def overlaps(first: Rect, second: Rect) -> bool:
    return (
        first.left < second.right
        and second.left < first.right
        and first.bottom < second.top
        and second.bottom < first.top
    )


def test_a_cards_boxes_are_inside_it_above_its_lip_and_apart() -> None:
    every = boxes()
    for box in every:
        assert box.left > 0 and box.right < CARD_WIDTH, box
        assert box.bottom > theme.LIP and box.top < CARD_HEIGHT, box
    for index, box in enumerate(every):
        for other in every[index + 1 :]:
            assert not overlaps(box, other), (box, other)
    for row in LAYOUT.dividers:
        assert not any(box.bottom <= row < box.top for box in every if box is not LAYOUT.band)


def test_swatches_sit_on_the_band() -> None:
    chips = swatch_rects(6, LAYOUT)
    band = LAYOUT.band
    for chip in chips:
        assert band.left <= chip.left - 1 and chip.right + 1 <= band.right - cards.INSET + 2
        assert band.bottom <= chip.bottom - 1 and chip.top + 1 <= band.top
    assert all(b.left - a.right == cards.SWATCH_GAP for a, b in itertools.pairwise(chips))


def test_cards_sit_under_their_fighters_inside_the_screen() -> None:
    from isofightr.config import NATIVE_W
    from isofightr.scenes.menu_world import PAD_WIDTH

    pose = rest_pose(STATIONS["gallery"])
    rects = []
    for x, y in RING_SPOTS:
        column, feet = screen_point(pose, x, y)
        rect = card_rect(column)
        rects.append(rect)
        assert rect.left >= 0 and rect.right <= NATIVE_W
        assert rect.bottom > theme.FOOTER_HEIGHT
        # The marker is a 2:1 diamond PAD_WIDTH wide at 1x, centred on the feet.
        marker_bottom = feet - PAD_WIDTH // 4 * round(pose.zoom)
        assert rect.top + theme.RAISE < marker_bottom, "the card clears the spot's marker"
    for first, second in itertools.pairwise(rects):
        assert first.right < second.left


@pytest.mark.parametrize("character", ROSTER, ids=lambda character: character.id)
def test_a_fighter_at_the_gallery_stays_clear_of_its_card_and_the_title(character: object) -> None:
    """Facing the viewer at twice battle size: standing, taunting and landing it never
    reaches down into its card (raised under the cursor), and no pose the screen shows it in
    reaches the title band. (A victory's ground effects, Bramble's quake, may pass under a
    card's top edge.)"""
    from isofightr.config import NATIVE_H

    sprites = load_sprite_set(character.id)
    assert sprites is not None
    pose = rest_pose(STATIONS["gallery"])
    zoom = round(pose.zoom)
    for x, y in RING_SPOTS:
        column, feet = screen_point(pose, x, y)
        card_top = card_rect(column).top + theme.RAISE
        for anim in ("idle", "taunt", "land", "victory"):
            info = sprites.anims[anim]
            for index in range(info.poses):
                frame = sprites.frame(anim, index, "S")
                top = feet + zoom * frame.pivot_y
                bottom = feet - zoom * (frame.height - frame.pivot_y)
                assert top <= NATIVE_H - theme.HEADER_HEIGHT + 2, (anim, index, top)
                if anim != "victory":
                    assert bottom > card_top, (anim, index, bottom, card_top)


# --- pages and the cursor ------------------------------------------------------------------


@pytest.mark.parametrize("count", range(1, 10))
def test_pages_hold_every_card_once(count: int) -> None:
    pages = page_count(count)
    shown = [index for page in range(pages) for index in on_page(page, count)]
    assert shown == list(range(count))
    assert all(len(on_page(page, count)) <= PER_PAGE for page in range(pages))
    assert all(page_of(index) == page for page in range(pages) for index in on_page(page, count))


@pytest.mark.parametrize("count", range(1, 10))
def test_left_and_right_visit_every_card_and_wrap(count: int) -> None:
    seen, index = [], 0
    for _ in range(count):
        seen.append(index)
        index = move_focus(index, MenuAction.RIGHT, count)
    assert sorted(seen) == list(range(count)) and index == 0
    assert move_focus(0, MenuAction.LEFT, count) == count - 1
    assert move_focus(0, MenuAction.UP, count) == 0 and move_focus(0, MenuAction.DOWN, count) == 0


# --- art ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize(
    "look",
    [*theme.ARCHETYPE_COLOURS.values(), theme.UNKNOWN_ARCHETYPE],
    ids=lambda look: look.label,
)
def test_card_art_is_the_palette_and_carries_its_colours(look: object, focused: bool) -> None:
    image = card_art.fighter_card(
        CARD_WIDTH, CARD_HEIGHT, look, cards.BAND, LAYOUT.dividers, focused
    )
    assert image.size == (CARD_WIDTH, CARD_HEIGHT)
    used = colours(image)
    assert used <= resurrect64()
    assert look.band in used and look.ramp[1] in used
    assert (theme.FOCUS in used) == focused
    # The band's text sits on the band colour itself.
    band = LAYOUT.band
    middle = image.getpixel(
        (CARD_WIDTH // 2 - 30, CARD_HEIGHT - 1 - (band.bottom + band.height // 2))
    )
    assert middle[:3] == look.band


@pytest.mark.parametrize("shown", [False, True])
def test_costume_chips_are_the_palette_and_the_shown_one_is_ringed(shown: bool) -> None:
    chip = card_art.costume_chip(cards.SWATCH, theme.CLAY, shown)
    assert chip.size == ((cards.SWATCH + 2,) * 2 if shown else (cards.SWATCH,) * 2)
    assert colours(chip) <= resurrect64()
    assert (theme.WHITE in colours(chip)) == shown


def test_a_stand_in_for_no_player_has_a_plain_shadow() -> None:
    plain, ringed = build_shadow(NO_PLAYER, 0), build_shadow(0, 0)
    assert {pixel[:3] for pixel in plain.getdata() if pixel[3]} == {(0, 0, 0)}
    assert len({pixel[:3] for pixel in ringed.getdata() if pixel[3]}) > 1
