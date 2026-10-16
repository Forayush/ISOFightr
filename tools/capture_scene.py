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

``--stage-sheet ID`` makes a stage's review sheet instead (decision D-063): one row per tick
(``--ticks``, default 1,45,90) with the whole screen and close-ups of the four spawns, both
edges, the underside and the top; ``--hazards on|off`` switches the stage's mechanics::

    uv run python tools/capture_scene.py --stage-sheet sky_ruins --out sky_ruins.png

``--hit-strip MOVE`` shows one hit up close (decision D-066): ``--p1`` performs the move on
``--p2`` at ``--percent``, set up as ``tools/kill_calc.py`` does, and each picture is a crop
(``--follow W,H``, default 160,120) centred on the target. ``--ticks`` counts from the tick
the hit lands (0) and takes ranges ``first:last:step`` (write ``--ticks=-2:40:2`` when the
first is negative)::

    uv run python tools/capture_scene.py --hit-strip fsmash --percent 100 --ticks=-2:40:2 \
        --scale 2 --out hit.png

For D-067's hit poses: ``--lift U`` holds the target U units up until the hit (an air hit),
``--delay N`` starts the move N ticks later (another hit frame: the reeling roll is a hash of
it), ``--effect electric`` makes the move's hitboxes electric.

``--screen`` shows a screen of the game's flow instead of a sandbox battle: title, main,
rules, pool, controls, charselect, stageselect, results, hud, loading, settings, soundtest, pause,
training,
kit (the UI kit sheet). The script's keys go to whatever scene is showing; ``--players``
sets how many fighters a screen with fighters has.
"""

import argparse
from dataclasses import replace
from pathlib import Path

from isofightr.app import GameWindow
from isofightr.capture import (
    SCREENS,
    STAGE_SHEET_TICKS,
    capture,
    capture_depth_lab,
    capture_hit_strip,
    capture_screen,
    capture_stage_sheet,
    parse_script,
)
from isofightr.settings import Settings, rules_from_data
from isofightr.sim.input_frame import Dir8
from isofightr.sim.move_def import Effect


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


def _ticks(text: str) -> list[int]:
    """Parse ticks such as ``10,20,30`` or ranges ``first:last:step`` (``0:40:2``), mixed."""
    ticks: list[int] = []
    for part in (part.strip() for part in text.split(",") if part.strip()):
        if ":" in part:
            first, last, *step = (int(value) for value in part.split(":"))
            ticks.extend(range(first, last + 1, step[0] if step else 1))
        else:
            ticks.append(int(part))
    return ticks


def main() -> None:
    """Parse arguments, run the capture and save the sheet."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--screen", choices=SCREENS, help="capture a screen, not a battle")
    parser.add_argument("--players", type=int, default=2, help="fighters on a --screen")
    parser.add_argument("--stage-sheet", default="", metavar="ID", help="a stage's review sheet")
    parser.add_argument(
        "--depth-lab",
        action="store_true",
        help="the --stage's depth lab: ground points and their off-stage twins, side by side",
    )
    parser.add_argument("--hit-strip", default="", metavar="MOVE", help="one hit, up close")
    parser.add_argument("--percent", type=float, default=60.0, help="the target's damage")
    parser.add_argument("--facing", default="SE", choices=[direction.name for direction in Dir8])
    parser.add_argument("--follow", default="160,120", help="hit-strip picture size W,H")
    parser.add_argument("--columns", type=int, default=8, help="hit-strip pictures per row")
    parser.add_argument("--lift", type=float, default=0.0, help="hit-strip: target this high")
    parser.add_argument("--delay", type=int, default=0, help="hit-strip: ticks before the move")
    parser.add_argument(
        "--effect", default="", choices=["", *(e.value for e in Effect)], help="hit-strip effect"
    )
    parser.add_argument(
        "--hazards", choices=("on", "off"), default="on", help="stage mechanics on a --stage-sheet"
    )
    parser.add_argument(
        "--rules",
        default="",
        help='rules for a --screen, e.g. "player_tags=true,score_display=true,stocks=5"',
    )
    parser.add_argument("--p1", default="rook")
    parser.add_argument("--p2", default="rook")
    parser.add_argument("--stage", default="training_grid")
    parser.add_argument("--script", default="", help='key events, e.g. "K@2,K!3"')
    parser.add_argument("--ticks", default="", help="ticks to capture, e.g. 10,20,30 or 0:40:2")
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
    ticks = _ticks(args.ticks) if args.ticks else [30]
    if args.hit_strip:
        wide, tall = (int(value) for value in _numbers(args.follow))
        sheet = capture_hit_strip(
            window,
            args.p1,
            args.p2,
            args.hit_strip,
            args.percent,
            _ticks(args.ticks) if args.ticks else list(range(0, 41, 2)),
            stage_id=args.stage,
            facing=Dir8[args.facing],
            crop=(wide, tall),
            columns=args.columns,
            scale=args.scale,
            lift=args.lift,
            delay=args.delay,
            effect=Effect(args.effect) if args.effect else None,
        )
    elif args.depth_lab:
        sheet = capture_depth_lab(window, args.stage, character=args.p1, scale=args.scale)
    elif args.stage_sheet:
        sheet = capture_stage_sheet(
            window,
            args.stage_sheet,
            ticks if args.ticks else STAGE_SHEET_TICKS,
            hazards=args.hazards == "on",
            seed=args.seed,
            scale=args.scale,
        )
    elif args.screen:
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
