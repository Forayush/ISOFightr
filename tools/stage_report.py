"""Check a stage against the design rules and print pass or fail for each.

Usage::

    uv run python tools/stage_report.py sky_ruins      # one stage
    uv run python tools/stage_report.py                # every stage in assets/stages

Exits 1 if any rule fails. The rules are in ``isofightr.data.stage_rules`` (plan note
"11 - Stages", "Design rules", and decision D-063).
"""

import argparse
import sys

from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.data.stage_rules import check_stage


def main() -> None:
    """Parse arguments, run the checks and print the report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stages", nargs="*", help="stage ids (default: every stage)")
    args = parser.parse_args()
    roster = [load_character(name) for name in list_character_ids()]
    failed = False
    for stage_id in args.stages or list_stage_ids():
        stage = load_stage(stage_id)
        print(f"{stage.display_name} ({stage_id})")
        for check in check_stage(stage, roster):
            failed |= not check.passed
            print(f"  {'pass' if check.passed else 'FAIL'}  {check.rule:20s} {check.detail}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
