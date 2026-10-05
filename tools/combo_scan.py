"""Print each character's frame advantage on hit, by move and percent.

Usage::

    uv run python tools/combo_scan.py                      # all four characters
    uv run python tools/combo_scan.py --character rook --percent 0 --percent 45
    uv run python tools/combo_scan.py --character mote --target bramble

See :mod:`isofightr.sim.combo_scan` for the formula. Used to tune comboability (D-059):
change a move's ``faf`` and ``total`` and run it again.
"""

import argparse

from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.sim.combo_scan import DEFAULT_PERCENTS, best, scan, starters, table


def main() -> None:
    """Parse arguments and print one table per character."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--character", action="append", help="repeat for several (default: all)")
    parser.add_argument("--target", default="rook", help="whose weight takes the hit")
    parser.add_argument("--percent", action="append", type=int, help="repeat for several")
    args = parser.parse_args()
    percents = tuple(args.percent or DEFAULT_PERCENTS)
    target = load_character(args.target)
    for character_id in args.character or list_character_ids():
        rows = scan(load_character(character_id), target, percents)
        print(f"\n{character_id} vs {target.id} (advantage on hit, frames)")
        print("\n".join(table(rows, percents)))
        for column, percent in enumerate(percents):
            print(
                f"  at {percent}%: {starters(rows, column)} starters at +3 or better, "
                f"best {best(rows, column):+d}"
            )


if __name__ == "__main__":
    main()
