"""Print a character's frame data as a Markdown table, from the move data and the real sim.

Usage::

    uv run python tools/frame_data_report.py                    # Rook, to the terminal
    uv run python tools/frame_data_report.py --write NOTE.md    # replace the table in a note

``--write`` replaces everything between ``<!-- FRAME_DATA_START -->`` and
``<!-- FRAME_DATA_END -->`` in the given file (a character note in the plan vault).
Plan note "16 - Testing Debug and Tooling" (``frame_data_report.py``).
"""

import argparse
from pathlib import Path

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.kill_calc import kill_percent
from isofightr.sim.move_def import MoveDef
from isofightr.sim.stage import Stage

START_MARKER = "<!-- FRAME_DATA_START -->"
END_MARKER = "<!-- FRAME_DATA_END -->"
COLUMNS = (
    "Move",
    "Startup",
    "Active",
    "FAF",
    "Landing lag",
    "Damage",
    "BKB/KBG",
    "Angle/Yaw",
    "Kill % (center)",
)
HEADER = ("| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS))


def _number(value: float) -> str:
    return f"{value:g}"


def move_row(character: CharacterDef, move: MoveDef, stage: Stage) -> str:
    """Return one table row. Per-hitbox values are listed sweet spot (lowest id) first."""
    boxes = [box for window in move.windows for box in window.hitboxes]
    active = ", ".join(
        str(window.frames.first)
        if window.frames.first == window.frames.last
        else f"{window.frames.first}-{window.frames.last}"
        for window in move.windows
    )
    damage = " / ".join(dict.fromkeys(_number(box.damage) for box in boxes))
    growth = " / ".join(dict.fromkeys(f"{_number(box.bkb)}/{_number(box.kbg)}" for box in boxes))
    angle = " / ".join(
        dict.fromkeys(
            _number(box.angle) + (f" (yaw {_number(box.yaw)})" if box.yaw else "") for box in boxes
        )
    )
    kill = kill_percent(stage, character, character, move.id)
    cells = (
        move.id,
        str(move.first_active_frame),
        active,
        str(move.faf),
        str(move.landing_lag) if move.autocancel else "",
        damage,
        growth,
        angle,
        "" if kill is None else f"{kill}%",
    )
    return "| " + " | ".join(cells) + " |"


def report(character: CharacterDef, stage: Stage) -> str:
    """Return the whole table, moves in moveset order."""
    order = list(dict.fromkeys(character.moveset.all_ids()))
    rows = [move_row(character, character.moves[move_id], stage) for move_id in order]
    return "\n".join([*HEADER, *rows])


def replace_table(text: str, table: str) -> str:
    """Return ``text`` with everything between the two markers replaced by ``table``."""
    start = text.index(START_MARKER) + len(START_MARKER)
    end = text.index(END_MARKER)
    return f"{text[:start]}\n{table}\n{text[end:]}"


def main() -> None:
    """Parse arguments, then print the table or write it into a note."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--character", default="rook")
    parser.add_argument("--stage", default="sky_ruins", help="stage for the kill percents")
    parser.add_argument("--write", type=Path, default=None, metavar="NOTE.md")
    args = parser.parse_args()

    table = report(load_character(args.character), load_stage(args.stage))
    if args.write is None:
        print(table)
        return
    note = args.write.read_text(encoding="utf-8")
    args.write.write_text(replace_table(note, table), encoding="utf-8", newline="\n")
    print(f"wrote {args.character}'s frame data into {args.write}")


if __name__ == "__main__":
    main()
