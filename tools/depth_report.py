"""Check that every stage's backdrop reads as behind the stage, and print the table.

Usage::

    uv run python tools/depth_report.py sky_ruins      # one stage
    uv run python tools/depth_report.py                # every stage in assets/stages

For each backdrop layer but the sky: the share of its pixels in an exact colour of the
playfield (at most 10%), its contrast against the playfield's (at most 0.7 times), and how
far its colour is from the sky against how far the playfield's is (at most 1.0 times, 0.7
for a far layer). Exits 1 if any layer fails. The rules are in
``isofightr.data.backdrop_rules`` (decision D-065; plan note "09 - Art Direction").
"""

import argparse
import sys

from isofightr.data.backdrop_rules import check_stage, report_lines
from isofightr.data.stage_loader import list_stage_ids, load_stage


def main() -> None:
    """Parse arguments, measure the stages and print the report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stages", nargs="*", help="stage ids (default: every stage)")
    args = parser.parse_args()
    layers = failed = 0
    for stage_id in args.stages or list_stage_ids():
        stage = load_stage(stage_id)
        reports = check_stage(stage)
        print(f"{stage.display_name} ({stage_id})")
        for line in report_lines(reports):
            print(line)
        layers += sum(not each.sky for each in reports)
        failed += sum(not each.passed for each in reports)
    print(f"{failed} of {layers} layers fail")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
