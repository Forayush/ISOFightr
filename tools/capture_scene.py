"""Capture a scripted battle or a menu screen offscreen as a contact sheet PNG.

Usage::

    uv run python tools/capture_scene.py --screen charselect --ticks 30 --scale 2 --out cs.png
    uv run python tools/capture_scene.py --screen main --script "S@5,S!6,ENTER@20,ENTER!21" \
        --ticks 10,40 --out menu.png

    uv run python tools/capture_scene.py --p1 rook --script "K@2,K!3" --ticks 10,20,30 \
        --out sheet.png
    uv run python tools/capture_scene.py --p1 mote --stage training_grid --p1-at 4,6,0 \
        --p2-at 7,6,0 --script "COMMA@2,K@2,K!3,COMMA!3" --ticks 20,40 --crop 160,60,320,220 \
        --scale 2 --out glyph.png

Player 1's default keys: ``K`` special, ``J`` attack, ``U`` smash, ``L`` grab, ``I`` up,
``COMMA`` down, ``SPACE`` jump, ``LSHIFT`` shield, ``W/A/S/D`` move. ``KEY@tick`` presses and
``KEY!tick`` releases. See :mod:`isofightr.capture`. Needs a display (the window is hidden).

``--screen`` shows a screen of the game's flow instead of a sandbox battle: title, main,
rules, pool, controls, charselect, stageselect, results, hud, loading, settings, pause, training,
kit (the UI kit sheet). The script's keys go to whatever scene is showing; ``--players``
sets how many fighters a screen with fighters has.
"""

import argparse
from dataclasses import replace
from pathlib import Path

from isofightr.app import GameWindow
from isofightr.capture import SCREENS, capture, capture_screen, parse_script
from isofightr.settings import Settings, rules_from_data


def _rules(text: str) -> dict[str, object]:
    """Parse ``name=value`` pairs into a ``[rules]`` table (true/false, whole numbers, or
    a number with a point)."""
    table: dict[str, object] = {}
    for pair in (part.strip() for part in text.split(",") if part.strip()):
        name, _, value = pair.partition("=")
        if value in ("true", "false"):
            table[name] = value == "true"
        else:
            table[name] = float(value) if "." in value else int(value)
    return table


def _numbers(text: str) -> tuple[float, ...]:
    return tuple(float(part) for part in text.split(","))


def main() -> None:
    """Parse arguments, run the capture and save the sheet."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--screen", choices=SCREENS, help="capture a screen, not a battle")
    parser.add_argument("--players", type=int, default=2, help="fighters on a --screen")
    parser.add_argument(
        "--rules",
        default="",
        help='rules for a --screen, e.g. "player_tags=true,score_display=true,stocks=5"',
    )
    parser.add_argument("--p1", default="rook")
    parser.add_argument("--p2", default="rook")
    parser.add_argument("--stage", default="training_grid")
    parser.add_argument("--script", default="", help='key events, e.g. "K@2,K!3"')
    parser.add_argument("--ticks", default="30", help="ticks to capture, e.g. 10,20,30")
    parser.add_argument("--p1-at", default=None, help="x,y,z for player 1")
    parser.add_argument("--p2-at", default=None, help="x,y,z for player 2")
    parser.add_argument("--damage", default="", help="starting damage per player, e.g. 0,80")
    parser.add_argument("--crop", default=None, help="left,top,width,height in native pixels")
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cpu", default="", help="CPU level per player, e.g. 0,9")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    def spot(text: str | None) -> tuple[float, float, float] | None:
        if text is None:
            return None
        x, y, z = _numbers(text)
        return (x, y, z)

    crop = None
    if args.crop:
        left, top, width, height = (int(value) for value in _numbers(args.crop))
        crop = (left, top, width, height)
    window = GameWindow(visible=False, sound=False)
    ticks = [int(value) for value in _numbers(args.ticks)]
    if args.screen:
        sheet = capture_screen(
            window,
            args.screen,
            parse_script(args.script),
            ticks,
            crop=crop,
            scale=args.scale,
            players=args.players,
            seed=args.seed,
            settings=replace(Settings(), rules=rules_from_data(_rules(args.rules))),
        )
    else:
        sheet = capture(
            window,
            [args.p1, args.p2],
            args.stage,
            parse_script(args.script),
            ticks,
            positions=[spot(args.p1_at), spot(args.p2_at)],
            damage=_numbers(args.damage) if args.damage else (),
            crop=crop,
            scale=args.scale,
            seed=args.seed,
            cpus=[int(value) for value in _numbers(args.cpu)] if args.cpu else (),
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    window.close()
    print(f"saved {sheet.width}x{sheet.height} to {args.out}")


if __name__ == "__main__":
    main()
