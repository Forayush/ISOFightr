"""The Fighters screen's model: one card per character, under its fighter at the ring.

Decision D-077. The main menu's Fighters button leads to a sheet of cards, one per character,
each under its fighter standing live on the Isle's ring. A card says who the character is:
its archetype on a band in the archetype's colour, its costumes, its name, a few sentences
about it (``description`` in ``fighter.toml``), its four specials (each move's ``name``),
the four stat bars of character select with the real figures beside them, and a line of
key numbers. Everything here comes from the game's data, so a new character gets a card
without touching the screen.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from isofightr.config import TICK_RATE
from isofightr.scenes.menu_world_model import RING_SPOTS
from isofightr.scenes.roster_model import STAT_NAMES, raw_stats, roster_entries
from isofightr.sim.character_def import CharacterDef
from isofightr.ui import font, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import ARROW_DOWN, ARROW_RIGHT, ARROW_UP, TextSize
from isofightr.ui.menu import MenuAction

# --- archetypes ------------------------------------------------------------------------------


def archetype_key(archetype: str) -> str:
    """Return the name an archetype is looked up by: "the all-rounder" is "all-rounder"."""
    key = archetype.strip().lower()
    return key.removeprefix("the ").strip()


def archetype_colours(archetype: str) -> theme.ArchetypeColours:
    """Return an archetype's colours; one the theme does not know is grey, with its own
    name (or "Fighter") on the band."""
    key = archetype_key(archetype)
    known = theme.ARCHETYPE_COLOURS.get(key)
    if known is not None:
        return known
    return replace(theme.UNKNOWN_ARCHETYPE, label=key.capitalize() or theme.UNKNOWN_ARCHETYPE.label)


# --- what a card says ------------------------------------------------------------------------

SPECIAL_SLOTS: Final[tuple[str, ...]] = ("nspecial", "sspecial", "uspecial", "dspecial")
"""The specials a card lists, in the order the move list gives them."""
SPECIAL_MARKS: Final[dict[str, str]] = {
    "nspecial": "•",
    "sspecial": ARROW_RIGHT,
    "uspecial": ARROW_UP,
    "dspecial": ARROW_DOWN,
}
"""The mark before each special's name: a dot for the neutral one, else the stick's way."""
SPECIAL_WORDS: Final[dict[str, str]] = {
    "nspecial": "Neutral special",
    "sspecial": "Side special",
    "uspecial": "Up special",
    "dspecial": "Down special",
}
"""What a special without a name is called."""
STAT_WORDS: Final[dict[str, str]] = {
    "weight": "Weight",
    "speed": "Speed",
    "air": "Air",
    "power": "Power",
}
"""The stat rows' labels, in mixed case (decision D-072)."""


@dataclass(frozen=True, slots=True)
class FighterCard:
    """Everything one character's card shows."""

    id: str
    name: str
    colours: theme.ArchetypeColours
    description: tuple[str, ...]
    """The description, one line of the card per entry (at most :data:`DESCRIPTION_LINES`)."""
    stats: Mapping[str, float]
    """Each of :data:`~isofightr.scenes.roster_model.STAT_NAMES`, scaled across the roster
    (as character select's bars)."""
    figures: Mapping[str, str]
    """The real value beside each bar."""
    facts: str
    specials: tuple[str, ...]
    """One line per :data:`SPECIAL_SLOTS`: its mark and its name."""


def figures(raw: Mapping[str, float]) -> dict[str, str]:
    """Return the figures beside the bars: weight as it is, run and air speed in tiles a
    second, power as the percent its hardest hits deal."""
    return {
        "weight": f"{raw['weight']:.0f}",
        "speed": f"{raw['speed'] * TICK_RATE:.1f}",
        "air": f"{raw['air'] * TICK_RATE:.1f}",
        "power": f"{raw['power']:.0f}%",
    }


def facts_line(character: CharacterDef) -> str:
    """Return the card's line of key numbers: air jumps and jumpsquat frames."""
    movement = character.movement
    return f"Air jumps {movement.air_jumps}   Jumpsquat {movement.jumpsquat}f"


def special_lines(character: CharacterDef) -> tuple[str, ...]:
    """Return each special's mark and name (the slot's own words if the move has none)."""
    lines = []
    for slot in SPECIAL_SLOTS:
        move = character.moves.get(getattr(character.moveset, slot))
        name = move.name if move is not None and move.name else SPECIAL_WORDS[slot]
        lines.append(f"{SPECIAL_MARKS[slot]} {name}")
    return tuple(lines)


def description_lines(text: str) -> tuple[str, ...]:
    """Return a description cut into the card's lines (anything past the last line is cut
    short, so a long text never runs off the card)."""
    lines = font.wrap(text, TEXT_WIDTH, TextSize.TEXT) if text else []
    shown = lines[:DESCRIPTION_LINES]
    return tuple(font.fit(line, TEXT_WIDTH, TextSize.TEXT) for line in shown)


def fighter_cards(characters: Sequence[CharacterDef]) -> list[FighterCard]:
    """Return every character's card, in the order given (the roster's)."""
    entries = roster_entries(characters)
    cards = []
    for character in characters:
        entry = entries[character.id]
        cards.append(
            FighterCard(
                id=character.id,
                name=character.display_name,
                colours=archetype_colours(character.archetype),
                description=description_lines(character.description or character.blurb),
                stats=dict(entry.stats),
                figures=figures(raw_stats(character)),
                facts=facts_line(character),
                specials=special_lines(character),
            )
        )
    return cards


# --- the card's layout -----------------------------------------------------------------------
#
# Native pixels, y up. A card's boxes are relative to its bottom-left corner.

CARD_WIDTH: Final[int] = 148
CARD_HEIGHT: Final[int] = 160
CARD_BOTTOM: Final[int] = 22
"""The cards stand on the footer's ledge, their tops below the fighters' markers."""
INSET: Final[int] = 6
TEXT_WIDTH: Final[int] = CARD_WIDTH - 2 * INSET
BAND: Final[int] = 14
"""The archetype band across the card's top, inside its outline."""
NAME_ROW: Final[int] = 18
LINE: Final[int] = 11
"""Pitch of the description's lines (the ``TEXT`` face)."""
DESCRIPTION_LINES: Final[int] = 4
SMALL_ROW: Final[int] = 9
"""Pitch of the rows in the ``SMALL`` face: specials, stats, facts."""
SPECIAL_COLUMNS: Final[int] = 2
COLUMN_GAP: Final[int] = 4
SPECIAL_WIDTH: Final[int] = (TEXT_WIDTH - COLUMN_GAP) // SPECIAL_COLUMNS
STAT_LABEL_WIDTH: Final[int] = 28
GAUGE_WIDTH: Final[int] = 82
GAUGE_HEIGHT: Final[int] = 7
SWATCH: Final[int] = 7
"""A costume chip on the band; the one shown is drawn a pixel bigger all round."""
SWATCH_GAP: Final[int] = 2
SWATCH_RISE: Final[int] = 1


@dataclass(frozen=True, slots=True)
class CardLayout:
    """Where everything on a card goes, relative to its bottom-left corner."""

    band: Rect
    name: Rect
    description: tuple[Rect, ...]
    specials: tuple[Rect, ...]
    """One box per special: two columns, two rows, left to right then down."""
    stats: tuple[Rect, ...]
    """One row per stat."""
    facts: Rect
    dividers: tuple[int, ...]
    """Rows of the thin lines between the sections."""

    def label(self, row: Rect) -> Rect:
        """Return where a stat row's label goes."""
        return Rect(row.left, row.bottom, STAT_LABEL_WIDTH, row.height)

    def gauge(self, row: Rect) -> Rect:
        """Return where a stat row's bar goes: after its label, centred on the row."""
        bottom = row.bottom + (row.height - GAUGE_HEIGHT) // 2
        return Rect(row.left + STAT_LABEL_WIDTH, bottom, GAUGE_WIDTH, GAUGE_HEIGHT)

    def figure(self, row: Rect) -> Rect:
        """Return where a stat row's figure goes: the rest of the row, right-aligned."""
        left = row.left + STAT_LABEL_WIDTH + GAUGE_WIDTH + 2
        return Rect(left, row.bottom, row.right - left, row.height)


def card_layout() -> CardLayout:
    """Return the card's layout, from the top down."""
    band = Rect(1, CARD_HEIGHT - 1 - BAND, CARD_WIDTH - 2, BAND)
    y = band.bottom - 2
    name = Rect(INSET, y - NAME_ROW, TEXT_WIDTH, NAME_ROW)
    y = name.bottom
    description = tuple(
        Rect(INSET, y - (row + 1) * LINE, TEXT_WIDTH, LINE) for row in range(DESCRIPTION_LINES)
    )
    y -= DESCRIPTION_LINES * LINE
    first_divider = y - 2
    y = first_divider - 2
    specials = []
    rows = -(-len(SPECIAL_SLOTS) // SPECIAL_COLUMNS)
    for index in range(len(SPECIAL_SLOTS)):
        row, column = divmod(index, SPECIAL_COLUMNS)
        left = INSET + column * (SPECIAL_WIDTH + COLUMN_GAP)
        specials.append(Rect(left, y - (row + 1) * SMALL_ROW, SPECIAL_WIDTH, SMALL_ROW))
    y -= rows * SMALL_ROW
    second_divider = y - 2
    y = second_divider - 2
    stats = tuple(
        Rect(INSET, y - (row + 1) * SMALL_ROW, TEXT_WIDTH, SMALL_ROW)
        for row in range(len(STAT_NAMES))
    )
    y -= len(STAT_NAMES) * SMALL_ROW
    facts = Rect(INSET, y - SMALL_ROW, TEXT_WIDTH, SMALL_ROW)
    return CardLayout(
        band, name, description, tuple(specials), stats, facts, (first_divider, second_divider)
    )


def swatch_rects(count: int, layout: CardLayout | None = None) -> list[Rect]:
    """Return where a card's costume chips go: in a row at the right of its band."""
    band = (layout or card_layout()).band
    step = SWATCH + SWATCH_GAP
    left = band.right - INSET + 1 - count * step + SWATCH_GAP
    bottom = band.bottom + (band.height - SWATCH) // 2
    return [Rect(left + index * step, bottom, SWATCH, SWATCH) for index in range(count)]


def card_rect(spot_x: int) -> Rect:
    """Return where the card under a ring spot's fighter goes (at rest)."""
    return Rect(spot_x - CARD_WIDTH // 2, CARD_BOTTOM, CARD_WIDTH, CARD_HEIGHT)


# --- pages and the cursor --------------------------------------------------------------------

PER_PAGE: Final[int] = len(RING_SPOTS)
"""Cards on a page: one per ring spot."""


def page_count(count: int) -> int:
    """Return how many pages ``count`` cards fill (at least one)."""
    return max(-(-count // PER_PAGE), 1)


def page_of(index: int) -> int:
    """Return the page a card is on."""
    return max(index, 0) // PER_PAGE


def on_page(page: int, count: int) -> range:
    """Return the cards on a page."""
    first = page * PER_PAGE
    return range(first, min(first + PER_PAGE, count))


def move_focus(index: int, action: MenuAction, count: int) -> int:
    """Return the card a direction takes the cursor to: left and right step through every
    card, wrapping at the ends (past a page's edge is the next page's first card); up and
    down do nothing (one row)."""
    if count <= 0:
        return 0
    if action is MenuAction.RIGHT:
        return (index + 1) % count
    if action is MenuAction.LEFT:
        return (index - 1) % count
    return index


# --- timing ----------------------------------------------------------------------------------

DROP_STAGGER: Final[int] = 6
"""Ticks between one fighter dropping onto its spot and the next."""
RISE_TICKS: Final[int] = 18
RISE_FROM: Final[int] = -CARD_HEIGHT - CARD_BOTTOM
"""The cards rise into place from below the screen as the screen opens."""
RISE_STAGGER: Final[int] = 3


def drop_tick(slot: int) -> int:
    """Return the tick of the screen a ring spot's fighter drops in on."""
    return slot * DROP_STAGGER


def rise_start(slot: int) -> int:
    """Return the tick a card under a ring spot starts to rise on."""
    return slot * RISE_STAGGER


_LAYOUT = card_layout()
assert _LAYOUT.facts.bottom >= theme.LIP + 2, "the card's rows run into its lip"
assert all(rect.width > 0 for rect in _LAYOUT.specials)
