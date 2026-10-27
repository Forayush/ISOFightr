"""Print which non-aerial moves can hit a standing and a crouching target, from the real sim.

Usage::

    uv run python tools/crouch_report.py                    # all four characters
    uv run python tools/crouch_report.py --character bramble --distances 1.0,1.5,2.0
    uv run python tools/crouch_report.py --share 0.55       # preview another crouch capsule

One table per character: for every jab, tilt, dash attack, smash, special and grab, whether
it reaches a same-character target standing and crouching at each distance (``yes`` with its
first hitbox window, ``later`` only afterwards, ``-`` never) and how high its volumes reach.
``*`` marks D-069's guard list (jab1, ftilt, dtilt, dash attack, fsmash, dsmash, grabs), which
must reach a crouching target wherever its first window reaches a standing one; the exit
status is 1 if one does not. See :mod:`isofightr.sim.crouch_report` (decision D-069).
"""

import argparse
import sys

from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.crouch_report import findings, scan, table


def main() -> None:
    """Parse arguments and print one table per character."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--character", action="append", help="repeat for several (default: all)")
    parser.add_argument("--distances", default="1.0,1.5", help="target distances in units")
    parser.add_argument(
        "--share",
        type=float,
        default=None,
        help="preview a crouch capsule whose top is this share of the standing height "
        "(default: each character's own crouch_hurtbox)",
    )
    parser.add_argument("--stage", default="training_grid")
    args = parser.parse_args()
    distances = tuple(float(value) for value in args.distances.split(","))
    stage = load_stage(args.stage)
    failed = False
    for character_id in args.character or list_character_ids():
        character = load_character(character_id)
        standing = character.body.hurtbox
        crouch = character.body.crouch_hurtbox
        if args.share is not None:
            crouch = standing.lowered(args.share)
        rows = scan(stage, character, crouch, distances)
        print(
            f"\n{character_id}: standing z {standing.z0:g}-{standing.z1:g}, crouching z "
            f"{crouch.z0:g}-{crouch.z1:.2f}, radius {standing.radius:g}"
        )
        print("\n".join(table(rows, distances)))
        lines = findings(rows)
        print("\n".join(f"  {line}" for line in lines) or "  reaches a crouch wherever it reaches")
        failed = failed or any(row.guard_failure for row in rows)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
