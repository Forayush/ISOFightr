"""The character select screen's model: the roster grid, costumes and the stat bars.

Plan note "13 - Game Modes UI and Flow" ("Character select screen", decision D-061). The
roster is a grid of tiles, one per character plus Random, laid out by itself, so a new
character appears without touching the screen. Each player's cursor moves from tile to
tile. A player picks one of the character's costumes; two players on the same character
never wear the same one. The four stat bars are computed from the character's data and
scaled across the roster. All of that is here, so it is tested without a window.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from isofightr.art.palettes import RAMP_LENGTH
from isofightr.sim.character_def import CharacterDef
from isofightr.ui.focus import Rect
from isofightr.ui.menu import MenuAction

RANDOM: Final[str] = "random"
"""The tile that stands for "pick a character for me when the match starts"."""
RANDOM_NAME: Final[str] = "Random"
TILES_PER_ROW: Final[int] = 6
STAT_NAMES: Final[tuple[str, ...]] = ("weight", "speed", "air", "power")
"""The stat bars, in the order they are shown."""
STAT_LABELS: Final[dict[str, str]] = {
    "weight": "WEIGHT",
    "speed": "SPEED",
    "air": "AIR",
    "power": "POWER",
}
STAT_FLOOR: Final[float] = 0.2
"""The lowest character's bar is this full, not empty: every fighter has some of each."""
SWATCH_SHADE: Final[int] = 1
"""Which shade of a material's ramp a costume swatch shows: 0 highlight, 1 light, 2 mid."""
SWATCH_AREA_CAP: Final[float] = 0.08
POWER_MOVES: Final[int] = 3
"""A character's power is the mean damage of this many of its hardest-hitting moves."""
_STEPS: Final[dict[MenuAction, tuple[int, int]]] = {
    MenuAction.LEFT: (-1, 0),
    MenuAction.RIGHT: (1, 0),
    MenuAction.UP: (0, -1),
    MenuAction.DOWN: (0, 1),
}


def roster_tiles(character_ids: Sequence[str]) -> tuple[str, ...]:
    """Return the roster's tiles: every character in order, then Random."""
    return (*character_ids, RANDOM)


def tile_rects(
    count: int, left: int, top: int, width: int, height: int, gap: int = 4
) -> list[Rect]:
    """Return where ``count`` tiles go: rows of :data:`TILES_PER_ROW` hanging down from
    ``top``, left-aligned at ``left``."""
    rects = []
    for index in range(count):
        row, column = divmod(index, TILES_PER_ROW)
        rects.append(
            Rect(
                left + column * (width + gap),
                top - (row + 1) * height - row * gap,
                width,
                height,
            )
        )
    return rects


def move_cursor(index: int, action: MenuAction, count: int) -> int | None:
    """Return the tile a direction takes a cursor to from tile ``index``.

    Left and right wrap along the row. Up and down move between rows; leaving the grid at
    the top or the bottom returns ``None``, so the screen can move the cursor on to
    whatever is above or below the roster (the rules chip, a player's own rows).
    """
    step = _STEPS.get(action)
    if step is None or count <= 0:
        return index
    row, column = divmod(index, TILES_PER_ROW)
    rows = (count + TILES_PER_ROW - 1) // TILES_PER_ROW
    if step[0]:
        in_row = min(TILES_PER_ROW, count - row * TILES_PER_ROW)
        return row * TILES_PER_ROW + (column + step[0]) % in_row
    target = row + step[1]
    if not 0 <= target < rows:
        return None
    in_row = min(TILES_PER_ROW, count - target * TILES_PER_ROW)
    return target * TILES_PER_ROW + min(column, in_row - 1)


# --- costumes --------------------------------------------------------------------------------


def next_costume(current: int, step: int, count: int, taken: Sequence[int] = ()) -> int:
    """Return the next costume in a direction, skipping the ones in ``taken`` (worn by other
    players on the same character). With every other costume taken it stays put."""
    count = max(count, 1)
    costume = current % count
    for _ in range(count):
        costume = (costume + step) % count
        if costume not in taken:
            return costume
    return current % count


def free_costume(wanted: int, count: int, taken: Sequence[int] = ()) -> int:
    """Return ``wanted`` if nobody else on the character wears it, else the next free one."""
    count = max(count, 1)
    wanted %= count
    return wanted if wanted not in taken else next_costume(wanted, 1, count, taken)


def costume_swatches(
    costumes: Sequence[tuple[str, Sequence[tuple[int, int, int]]]],
    area: Mapping[int, int] | None = None,
) -> list[tuple[int, int, int]]:
    """Return one colour per costume to show on its swatch: the light shade of the material
    that says most about the costume. That is the material whose colours change most from
    costume to costume, weighted by how much of the character's picture it covers
    (``area``: pixels per palette entry, counted up to a twelfth of the picture), so a tunic
    wins over a plume but a golem's moss wins over his stone. A palette is a
    transparent entry followed by a ramp of :data:`RAMP_LENGTH` shades per material."""
    if not costumes:
        return []
    palettes = [colors for _, colors in costumes]
    entries = min(len(colors) for colors in palettes)
    materials = max((entries - 1) // RAMP_LENGTH, 1)

    def spread(entry: int) -> int:
        channels = list(zip(*(colors[entry] for colors in palettes), strict=True))
        return sum(max(channel) - min(channel) for channel in channels)

    total = sum(area.values()) if area else 0

    def weight(material: int) -> float:
        ramp = range(1 + material * RAMP_LENGTH, min(1 + (material + 1) * RAMP_LENGTH, entries))
        change = sum(spread(entry) for entry in ramp)
        if not area or total <= 0:
            return float(change)
        share = sum(area.get(entry, 0) for entry in ramp) / total
        # Past a twelfth of the picture more area says no more: a golem is mostly stone in
        # every costume, and it is his moss that tells them apart.
        return change * min(share, SWATCH_AREA_CAP)

    best = max(range(materials), key=weight)
    shade = min(1 + best * RAMP_LENGTH + SWATCH_SHADE, entries - 1)
    return [tuple(colors[shade]) for colors in palettes]  # type: ignore[misc]


# --- stats -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """What the detail strip shows for one character."""

    name: str
    archetype: str
    blurb: str
    stats: Mapping[str, float]
    """Each of :data:`STAT_NAMES`, from :data:`STAT_FLOOR` (the roster's lowest) to 1."""


def raw_stats(character: CharacterDef) -> dict[str, float]:
    """Return a character's stats in their own units: weight, run speed, air speed, and
    power (the mean damage of its hardest-hitting moves)."""
    damages = sorted(
        (
            max(hitbox.damage for window in move.windows for hitbox in window.hitboxes)
            for move in character.moves.values()
            if any(window.hitboxes for window in move.windows)
        ),
        reverse=True,
    )
    top = damages[:POWER_MOVES]
    return {
        "weight": character.weight,
        "speed": character.movement.run_speed,
        "air": character.movement.air_speed,
        "power": sum(top) / len(top) if top else 0.0,
    }


def roster_entries(characters: Sequence[CharacterDef]) -> dict[str, RosterEntry]:
    """Return every character's detail-strip entry, by id, with the stats scaled across the
    roster: the lowest value of each stat shows as :data:`STAT_FLOOR`, the highest as 1."""
    raw = {character.id: raw_stats(character) for character in characters}
    entries = {}
    for character in characters:
        stats = {}
        for name in STAT_NAMES:
            values = [each[name] for each in raw.values()]
            low, high = min(values), max(values)
            share = 1.0 if high <= low else (raw[character.id][name] - low) / (high - low)
            stats[name] = STAT_FLOOR + (1.0 - STAT_FLOOR) * share
        entries[character.id] = RosterEntry(
            character.display_name, character.archetype, character.blurb, stats
        )
    return entries


RANDOM_ENTRY: Final[RosterEntry] = RosterEntry(
    RANDOM_NAME, "the wildcard", "A fighter is picked for you when the match starts.", {}
)
