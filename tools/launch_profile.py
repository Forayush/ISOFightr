"""Print how a hit freezes and launches its target, frame by frame, from the real sim.

Usage::

    uv run python tools/launch_profile.py           # Rook's fsmash at 0, 60, 100 and 150%
    uv run python tools/launch_profile.py --attacker mote --move fsmash --percents 60,100
    uv run python tools/launch_profile.py --target bramble --stage sky_ruins --facing E

For each percent: the freeze (hitlag) in frames and ms, the hitstun, the peak speed in units
per frame and body heights per second, the share of the 90-frame travel done in the first
20 frames, the frame the knockback falls below 10% of its peak, how high the target rises,
and the table of speed, distance and height after the launch. See
:mod:`isofightr.sim.launch_profile` (decision D-066).
"""

import argparse

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat import constants as c
from isofightr.sim.input_frame import Dir8
from isofightr.sim.launch_profile import launch_profile, profile_lines


def constants_line() -> str:
    """Return the launch constants in force, for the top of the output."""
    return (
        f"PHYS_SCALE={c.PHYS_SCALE:g}  LAUNCH_SNAP={c.LAUNCH_SNAP:g}  "
        f"HITSTUN_GRAVITY_MULT={c.HITSTUN_GRAVITY_MULT:g}  "
        f"HITLAG_SCALE={c.HITLAG_SCALE:g}  HITSTUN_BONUS={c.HITSTUN_BONUS_FRAMES}  "
        f"KB_DECAY={c.KB_DECAY:.5f}"
    )


def main() -> None:
    """Parse arguments and print one profile per percent."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--attacker", default="rook")
    parser.add_argument("--target", default="rook")
    parser.add_argument("--move", default="fsmash")
    parser.add_argument("--percents", default="0,60,100,150")
    parser.add_argument("--stage", default="training_grid")
    parser.add_argument("--facing", default="SE", choices=[direction.name for direction in Dir8])
    args = parser.parse_args()

    stage = load_stage(args.stage)
    attacker, target = load_character(args.attacker), load_character(args.target)
    print(constants_line())
    print(f"{attacker.id} {args.move} on {target.id}, {stage.id}, facing {args.facing}")
    for percent in (float(value) for value in args.percents.split(",")):
        print()
        profile = launch_profile(stage, attacker, target, args.move, percent, Dir8[args.facing])
        print("\n".join(profile_lines(profile)))


if __name__ == "__main__":
    main()
