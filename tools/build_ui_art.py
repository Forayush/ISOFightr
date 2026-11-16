"""Build the UI art: the icon sheet from its text recipes.

Usage::

    uv run python tools/build_ui_art.py

Writes ``assets/ui/icons.png`` and ``icons.json`` from ``art_src/ui/icons.toml``. Commit the
result with the source change: ``tests/test_ui_kit.py`` fails if they are out of date. Plan
note "09 - Art Direction" ("UI theme", decision D-061).

The menus' backdrop is not built here any more: since decision D-072 it is the Isle, a
stage, whose layers come from ``tools/build_backdrop.py isle --theme cloud_sea --seed 21
--out assets/ui/isle``.
"""

import json
import tomllib

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


if __name__ == "__main__":
    main()
