"""What the stage select screen says about a stage, worked out from its data.

Plan note "13 - Game Modes UI and Flow" ("Stage select", decision D-061): the stage's name
"in a banner with a one-line description (generated from the stage data if no text is
given)", plus the song it plays and the shape of the ground. Also the grid of stage tiles
and the cursor's moves over it.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from isofightr.data.paths import AUDIO_MANIFEST
from isofightr.sim.stage import Stage
from isofightr.ui.focus import Rect
from isofightr.ui.menu import MenuAction

NUMBER_WORDS: Final[tuple[str, ...]] = (
    "no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
)  # fmt: skip
STAGE_COLUMNS: Final[int] = 2
"""The stage grid is this many tiles across."""


def _count(number: int, thing: str) -> str:
    word = NUMBER_WORDS[number] if number < len(NUMBER_WORDS) else str(number)
    return f"{word} {thing}{'' if number == 1 else 's'}"


def island_count(stage: Stage) -> int:
    """Return how many separate pieces of solid ground the stage has (cells touching side
    by side are one piece)."""
    seen: set[tuple[int, int]] = set()
    pieces = 0
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None or (cx, cy) in seen:
                continue
            pieces += 1
            stack = [(cx, cy)]
            seen.add((cx, cy))
            while stack:
                x, y = stack.pop()
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if (nx, ny) in seen or not 0 <= ny < stage.size_y or not 0 <= nx < stage.size_x:
                        continue
                    if stage.cells[ny][nx] is not None:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
    return pieces


def is_flat(stage: Stage) -> bool:
    """Return whether every solid cell has the same top."""
    tops = {cell.top for row in stage.cells for cell in row if cell is not None}
    return len(tops) <= 1


def describe(stage: Stage) -> str:
    """Return the stage's one-line description: its own ``description``, or one made from
    its ground and platforms ("Two islands and one soft platform.")."""
    if stage.description:
        return stage.description
    islands = island_count(stage)
    ground = "One island" if islands == 1 else _count(islands, "island").capitalize()
    if not is_flat(stage):
        ground += " with raised ground"
    platforms = len(stage.soft_platforms)
    if platforms == 0:
        return f"{ground}, flat and open." if is_flat(stage) else f"{ground}."
    joiner = " and " if "with" in ground else " with "
    return f"{ground}{joiner}{_count(platforms, 'soft platform')}."


def load_music_titles(path: Path = AUDIO_MANIFEST) -> dict[str, str]:
    """Return every song's title by id, from the audio manifest (empty if it cannot be
    read: the screen then shows no title)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    music = data.get("music", {}) if isinstance(data, dict) else {}
    return {
        song: entry["title"]
        for song, entry in music.items()
        if isinstance(entry, dict) and isinstance(entry.get("title"), str)
    }


def music_line(stage: Stage, titles: Mapping[str, str]) -> str:
    """Return the song a stage plays, as the screen shows it ("" for none)."""
    if stage.music is None:
        return ""
    return titles.get(stage.music, stage.music.replace("_", " ").title())


def size_line(stage: Stage) -> str:
    """Return the stage's ground size and platform count, as the screen shows it."""
    platforms = len(stage.soft_platforms)
    return f"{stage.size_x} x {stage.size_y}   {platforms} PLATFORM{'' if platforms == 1 else 'S'}"


def grid_rects(count: int, left: int, top: int, width: int, height: int, gap: int) -> list[Rect]:
    """Return where ``count`` stage tiles go: :data:`STAGE_COLUMNS` across, hanging down
    from ``top``."""
    rects = []
    for index in range(count):
        row, column = divmod(index, STAGE_COLUMNS)
        rects.append(
            Rect(left + column * (width + gap), top - (row + 1) * height - row * gap, width, height)
        )
    return rects


def move_in_grid(index: int, action: MenuAction, count: int) -> int:
    """Return the tile a direction takes the cursor to: left and right wrap along a row,
    up and down move a row and stop at the ends."""
    if count <= 0:
        return index
    row, column = divmod(index, STAGE_COLUMNS)
    if action in (MenuAction.LEFT, MenuAction.RIGHT):
        start = row * STAGE_COLUMNS
        in_row = min(STAGE_COLUMNS, count - start)
        step = 1 if action is MenuAction.RIGHT else -1
        return start + (column + step) % in_row
    if action in (MenuAction.UP, MenuAction.DOWN):
        target = index + (STAGE_COLUMNS if action is MenuAction.DOWN else -STAGE_COLUMNS)
        if 0 <= target < count:
            return target
        if action is MenuAction.DOWN and row < (count - 1) // STAGE_COLUMNS:
            return count - 1
    return index


def pool_text(pool: Sequence[str], stage_ids: Sequence[str]) -> str:
    """Return how much of the roster the random pool holds ("4 / 5")."""
    return f"{len([stage for stage in stage_ids if stage in pool])} / {len(stage_ids)}"
