"""Draw a character's packed sprites as a contact sheet PNG, for reviewing art.

Usage::

    uv run python tools/sprite_preview.py rook                      # pose 0 of every animation
    uv run python tools/sprite_preview.py rook --anim idle --poses  # every pose of one animation
    uv run python tools/sprite_preview.py rook --costumes           # pose 0 of idle, all costumes

Rows are animations (or poses, or costumes), columns the eight directions, over a mid-grey tile
so outlines read. Plan note "10 - Animation and Asset Pipeline".
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from isofightr.data.paths import CHARACTERS_DIR
from isofightr.sim.input_frame import Dir8

CELL = 96
FEET_FROM_TOP = 76
BACKGROUND = (58, 64, 92)
GROUND = (88, 98, 128)
ORDER = (Dir8.SE, Dir8.S, Dir8.SW, Dir8.W, Dir8.NW, Dir8.N, Dir8.NE, Dir8.E)


def main() -> None:
    """Parse arguments and write the PNG."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("character")
    parser.add_argument("--anim", default=None)
    parser.add_argument("--poses", action="store_true", help="one row per pose")
    parser.add_argument("--costumes", action="store_true", help="one row per costume")
    parser.add_argument("--costume", type=int, default=0)
    parser.add_argument("--scale", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("build/preview.png"))
    args = parser.parse_args()

    folder = CHARACTERS_DIR / args.character / "sprites"
    data = json.loads((folder / "sprites.json").read_text(encoding="utf-8"))
    sheets = [Image.open(folder / name) for name in data["sheets"]]
    anims = [args.anim] if args.anim else sorted(data["anims"])

    rows: list[tuple[str, int, int]] = []  # (anim, pose, costume)
    if args.costumes:
        rows = [(anims[0], 0, index) for index in range(len(data["costumes"]))]
    elif args.poses:
        rows = [(anims[0], pose, args.costume) for pose in range(data["anims"][anims[0]]["poses"])]
    else:
        rows = [(anim, 0, args.costume) for anim in anims]

    image = Image.new("RGB", (CELL * len(ORDER), CELL * len(rows)), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for row, (anim, pose, costume) in enumerate(rows):
        colors = data["costumes"][costume]["colors"]
        flat = [int(color[i : i + 2], 16) for color in colors for i in (0, 2, 4)]
        for column, facing in enumerate(ORDER):
            sheet, x, y, w, h, pivot_x, pivot_y = data["frames"][f"{anim}/{pose}/{facing.name}"]
            frame = sheets[sheet].crop((x, y, x + w, y + h))
            frame.putpalette(flat + [0] * (768 - len(flat)))
            feet = (column * CELL + CELL // 2, row * CELL + FEET_FROM_TOP)
            draw.polygon(
                [
                    (feet[0], feet[1] - 8),
                    (feet[0] + 16, feet[1]),
                    (feet[0], feet[1] + 8),
                    (feet[0] - 16, feet[1]),
                ],
                fill=GROUND,
            )
            rgba = frame.convert("RGBA")
            image.paste(rgba, (feet[0] - pivot_x, feet[1] - pivot_y), rgba)
        draw.text((2, row * CELL + 2), f"{anim} {pose} {data['costumes'][costume]['name']}")
    image = image.resize((image.width * args.scale, image.height * args.scale), Image.NEAREST)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
