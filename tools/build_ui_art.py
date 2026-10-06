"""Build the UI art: the icon sheet from its text recipes, and the menu backdrop layers.

Usage::

    uv run python tools/build_ui_art.py

Writes ``assets/ui/icons.png`` and ``icons.json`` from ``art_src/ui/icons.toml``, and the
dusk backdrop layers into ``assets/ui/backdrop/``. Commit the result with the source change:
``tests/test_ui_art.py`` fails if they are out of date. Plan note "09 - Art Direction"
("UI theme", decision D-061).
"""

import json
import tomllib

from isofightr.ui.backdrop import BACKDROP_DIR, paint_layers
from isofightr.ui.icons import ICON_INDEX, ICON_SHEET, ICON_SOURCE, build_sheet, parse_icons


def main() -> None:
    """Build everything and say what was written."""
    with ICON_SOURCE.open("rb") as file:
        icons = parse_icons(tomllib.load(file))
    sheet, index = build_sheet(icons)
    ICON_SHEET.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(ICON_SHEET, optimize=True)
    ICON_INDEX.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{ICON_SHEET}: {len(icons)} icons")
    BACKDROP_DIR.mkdir(parents=True, exist_ok=True)
    for name, image in paint_layers().items():
        image.save(BACKDROP_DIR / name, optimize=True)
        print(BACKDROP_DIR / name)


if __name__ == "__main__":
    main()
