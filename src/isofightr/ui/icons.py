"""The small UI icons: text recipes to images, and the packed sheet the game loads.

Plan note "09 - Art Direction" ("UI theme", decision D-061): icons are drawn as text in
``art_src/ui/icons.toml`` (one character per pixel) and packed by ``tools/build_ui_art.py``
into ``assets/ui/icons.png`` with ``icons.json`` naming each cell. The game reads only the
packed sheet (the packaged game has no ``art_src``).

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from PIL import Image

from isofightr.data.paths import ASSETS_DIR, REPO_ROOT

LOG = logging.getLogger(__name__)

UI_DIR: Final[Path] = ASSETS_DIR / "ui"
ICON_SHEET: Final[Path] = UI_DIR / "icons.png"
ICON_INDEX: Final[Path] = UI_DIR / "icons.json"
ICON_SOURCE: Final[Path] = REPO_ROOT / "art_src" / "ui" / "icons.toml"
"""The recipes the sheet is packed from (not shipped)."""
TRANSPARENT: Final[tuple[int, int, int, int]] = (0, 0, 0, 0)
FLIP, FLIP_V, TURN = "flip", "flip_v", "turn"


class IconError(ValueError):
    """An icon recipe is malformed."""


def _color(value: str) -> tuple[int, int, int, int]:
    if not value:
        return TRANSPARENT
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


def parse_icons(data: Mapping[str, Any]) -> dict[str, Image.Image]:
    """Build every icon of a parsed ``icons.toml``: the drawn icons in the order the file
    lists them, then the derived ones.

    Raises:
        IconError: a row is the wrong length, uses a character the legend lacks, or a
            derived icon names something unknown.
    """
    size = int(data["size"])
    legend = {character: _color(value) for character, value in data["legend"].items()}
    icons: dict[str, Image.Image] = {}
    for name, text in data["icons"].items():
        rows = text.strip("\n").split("\n")
        if len(rows) != size or any(len(row) != size for row in rows):
            raise IconError(f"icon {name!r} is not {size} by {size}")
        image = Image.new("RGBA", (size, size), TRANSPARENT)
        for y, row in enumerate(rows):
            for x, character in enumerate(row):
                if character not in legend:
                    raise IconError(f"icon {name!r} uses {character!r}, not in the legend")
                image.putpixel((x, y), legend[character])
        icons[name] = image
    for name, recipe in data.get("derived", {}).items():
        operation, _, source = str(recipe).partition(":")
        if source not in icons:
            raise IconError(f"icon {name!r} is derived from unknown {source!r}")
        if operation == FLIP:
            icons[name] = icons[source].transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        elif operation == FLIP_V:
            icons[name] = icons[source].transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        elif operation == TURN:
            icons[name] = icons[source].transpose(Image.Transpose.ROTATE_90)
        else:
            raise IconError(f"icon {name!r}: unknown operation {operation!r}")
    return icons


def build_sheet(icons: Mapping[str, Image.Image]) -> tuple[Image.Image, dict[str, Any]]:
    """Pack icons side by side. Returns the sheet and its index (cell size and names)."""
    names = list(icons)
    size = next(iter(icons.values())).width
    sheet = Image.new("RGBA", (size * len(names), size), TRANSPARENT)
    for index, name in enumerate(names):
        sheet.paste(icons[name], (index * size, 0))
    return sheet, {"size": size, "icons": names}


def load_icons(sheet: Path = ICON_SHEET, index: Path = ICON_INDEX) -> dict[str, Image.Image]:
    """Read the packed icons. A missing or broken sheet gives no icons (and a warning), so
    the game still starts; widgets skip an icon they cannot find."""
    try:
        listing = json.loads(index.read_text(encoding="utf-8"))
        size, names = int(listing["size"]), list(listing["icons"])
        with Image.open(sheet) as opened:
            image = opened.convert("RGBA")
    except (OSError, ValueError, KeyError, TypeError) as error:
        LOG.warning("UI icons not loaded: %s", error)
        return {}
    return {
        str(name): image.crop((position * size, 0, (position + 1) * size, size))
        for position, name in enumerate(names)
    }
