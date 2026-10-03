"""Generate a stage's parallax backdrop layers as PNGs in its asset folder.

Usage::

    uv run python tools/build_backdrop.py sky_ruins            # the day backdrop

Writes ``bg_0_sky.png`` .. ``bg_3_near_clouds.png`` into ``assets/stages/<id>/``. The stage's
``stage.toml`` lists them as ``[[background]]`` layers with their parallax. Plan notes
"09 - Art Direction" ("Environments") and "11 - Stages".
"""

import argparse

from isofightr.data.paths import STAGES_DIR
from isofightr.render.backdrop import MOODS, clouds, islands, sky


def main() -> None:
    """Parse arguments and write the layers."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage")
    parser.add_argument("--mood", default="day", choices=sorted(MOODS))
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    mood = MOODS[args.mood]
    folder = STAGES_DIR / args.stage
    layers = {
        "bg_0_sky.png": sky(mood),
        "bg_1_far_clouds.png": clouds(mood, args.seed, 8, (250, 300), (10, 16)),
        "bg_2_islands.png": islands(mood, args.seed + 1, 6, (50, 150), (9, 18)),
        "bg_3_near_clouds.png": clouds(mood, args.seed + 2, 5, (318, 350), (18, 26)),
    }
    for name, image in layers.items():
        image.save(folder / name, optimize=True)
        print(folder / name)


if __name__ == "__main__":
    main()
