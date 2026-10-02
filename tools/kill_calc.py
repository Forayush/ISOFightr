"""Print the percent at which each of a character's moves KOs, by running the real sim.

Usage::

    uv run python tools/kill_calc.py                      # every Rook move on Sky Ruins
    uv run python tools/kill_calc.py --move fsmash --stage training_grid
    uv run python tools/kill_calc.py --attacker rook --target rook --facing E

See :mod:`isofightr.sim.kill_calc` for what counts as a KO. Used to calibrate ``PHYS_SCALE``
and blast zones (roadmap M3) and later for balance passes (M9).
"""

import argparse

from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.sim.input_frame import Dir8
from isofightr.sim.kill_calc import kill_percent


def main() -> None:
    """Parse arguments and print one line per move."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--attacker", default="rook")
    parser.add_argument("--target", default="rook")
    parser.add_argument("--stage", default="sky_ruins")
    parser.add_argument("--move", default=None, help="one move id (default: all moves)")
    parser.add_argument("--facing", default="SE", choices=[direction.name for direction in Dir8])
    args = parser.parse_args()

    stage = load_stage(args.stage)
    attacker, target = load_character(args.attacker), load_character(args.target)
    facing = Dir8[args.facing]
    moves = [args.move] if args.move else sorted(attacker.moves)
    print(f"{attacker.id} vs {target.id} from the centre of {stage.id}, facing {facing.name}")
    for move_id in moves:
        percent = kill_percent(stage, attacker, target, move_id, facing=facing)
        print(f"  {move_id:<12} {'does not KO by 300%' if percent is None else f'{percent}%'}")


if __name__ == "__main__":
    main()
