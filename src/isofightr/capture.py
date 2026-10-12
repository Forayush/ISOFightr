"""Capture a scripted battle or a menu screen offscreen as a contact sheet, to review looks.

Plan note "16 - Testing Debug and Tooling" (``capture_scene.py``, decisions D-060 and D-061).
A hidden :class:`~isofightr.app.GameWindow` runs a :class:`~isofightr.scenes.battle.BattleView`
with scripted key presses for player 1 and saves chosen ticks side by side. The match is a
sandbox: fighters may be placed anywhere and given damage, as in the tests.
:func:`capture_screen` does the same for a named screen of the game's flow (title, menus,
character select, the HUD, results...).

Imports ``arcade`` (through the app), so it needs a display.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import arcade
from PIL import Image, ImageDraw

from isofightr.app import GameWindow
from isofightr.config import NATIVE_H, NATIVE_W, TICK_SECONDS
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render.depth_cues import off_stage_twins
from isofightr.render.iso import project
from isofightr.scenes.battle import BattleView
from isofightr.scenes.flow import GameFlow
from isofightr.scenes.results_view import ResultsView
from isofightr.scenes.rules_model import with_saved
from isofightr.scenes.setup import MatchSetup, training_setup
from isofightr.scenes.ui_kit import UiKitView
from isofightr.settings import SavedRules, Settings
from isofightr.sim.input_frame import Dir8, facing_from_move
from isofightr.sim.match import MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage

PRESS, RELEASE = "@", "!"
SCREENS: tuple[str, ...] = (
    "boot",
    "title",
    "main",
    "rules",
    "pool",
    "controls",
    "controls_pad",
    "charselect",
    "stageselect",
    "results",
    "hud",
    "loading",
    "settings",
    "soundtest",
    "pause",
    "training",
    "kit",
)
"""The screens :func:`capture_screen` can show."""
ROSTER: tuple[str, ...] = ("rook", "bramble", "zephyr", "mote")
HUD_DAMAGE: tuple[float, ...] = (37.0, 86.0, 142.0, 12.0)
"""Damage the fighters are given for the HUD capture, so the colour ramp shows."""
HUD_CPU_LEVEL = 5
KEYBOARDS: tuple[str, ...] = ("keyboard:solo", "keyboard:arrows", "", "")
OUT_OF_BOUNDS = Vec3(5.0, 5.0, -90.0)
"""Far below any stage: a fighter put here is knocked out on the next tick."""
RESULTS_TICK_LIMIT = 6000
RESULTS_FIGHT_TICKS = 420
"""How long the CPUs fight before the results capture ends the match."""
STAGE_SHEET_TICKS: tuple[int, ...] = (1, 45, 90)
"""The default ticks of a stage sheet: far enough apart for animation and ambience to show."""
CLOSE_UP: tuple[int, int] = (160, 90)
"""Native pixels a stage sheet's close-up shows; it is drawn at twice that."""
CLOSE_UP_SCALE = 2
CLOSE_UP_COLUMNS = 4
SPAWN_LOOK_HEIGHT = 1.25
"""A spawn's close-up looks this many units above the ground: a fighter's middle."""
EDGE_INSET = 40
"""An edge's close-up looks this many pixels in from the stage's outermost corner."""
UNDERSIDE_INSET = 20
LABEL_COLOUR = (255, 255, 255, 255)
LABEL_SHADE = (0, 0, 0, 255)


@dataclass(frozen=True, slots=True)
class KeyStep:
    """One scripted key event: a key goes down or up on a tick (the first tick is 1)."""

    key: int
    tick: int
    down: bool


def parse_script(text: str) -> list[KeyStep]:
    """Parse a key script such as ``K@2,K!3,I@2``: ``KEY@tick`` presses and ``KEY!tick``
    releases a key, named as in ``arcade.key`` (``K``, ``I``, ``COMMA``, ``SPACE``...)."""
    steps = []
    for token in (part.strip() for part in text.split(",") if part.strip()):
        mark = PRESS if PRESS in token else RELEASE
        name, _, tick = token.partition(mark)
        code = getattr(arcade.key, name.upper(), None)
        if code is None or not tick.isdigit():
            raise ValueError(f"bad key step {token!r}: expected KEY@tick or KEY!tick")
        steps.append(KeyStep(int(code), int(tick), mark == PRESS))
    return steps


def read_frame(window: GameWindow) -> Image.Image:
    """Return the native-resolution frame the view last drew."""
    data = window.pixel_buffer.framebuffer.read(components=4)
    image = Image.frombytes("RGBA", (NATIVE_W, NATIVE_H), bytes(data))
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def capture(
    window: GameWindow,
    characters: Sequence[str],
    stage: str,
    script: Sequence[KeyStep],
    ticks: Sequence[int],
    positions: Sequence[tuple[float, float, float] | None] = (),
    damage: Sequence[float] = (),
    crop: tuple[int, int, int, int] | None = None,
    scale: int = 1,
    seed: int = 0,
    cpus: Sequence[int] = (),
) -> Image.Image:
    """Run the scripted battle and return the frames at ``ticks`` side by side.

    Args:
        window: a (hidden) game window.
        characters: character id per player.
        stage: stage id.
        script: key events for the keyboard (player 1's keys by default).
        ticks: which ticks to capture, in increasing order.
        positions: where to stand each fighter (``x, y, z``), or ``None`` for its spawn.
        damage: starting damage per player.
        crop: ``left, top, width, height`` in native pixels, applied to every frame.
        scale: integer upscale of the sheet.
        seed: the match seed.
        cpus: CPU level per player (0 = scripted or idle).
    """
    window.switch_to()
    view = BattleView(
        window.pixel_buffer,
        load_stage(stage),
        [load_character(name) for name in characters],
        seed=seed,
        cpus=list(cpus) or None,
    )
    view.show_help = False
    window.show_view(view)
    fighters = view.match.fighters
    for fighter, spot in zip(fighters, positions, strict=False):
        if spot is not None:
            fighter.pos = Vec3(*spot)
    for fighter, percent in zip(fighters, damage, strict=False):
        view.match.set_damage(fighter.player_index, percent)
    if len(fighters) >= 2:
        first, second = fighters[0], fighters[1]
        first.facing = facing_from_move((second.pos - first.pos).xy) or first.facing
        second.facing = facing_from_move((first.pos - second.pos).xy) or second.facing
    view.camera.snap_to([fighter.pos for fighter in fighters])

    return _run(window, script, ticks, crop, scale)


def _run(
    window: GameWindow,
    script: Sequence[KeyStep],
    ticks: Sequence[int],
    crop: tuple[int, int, int, int] | None,
    scale: int,
) -> Image.Image:
    """Tick whatever view the window shows (it may change on the way), feeding it the key
    script, and return the frames at ``ticks`` side by side."""
    frames: list[Image.Image] = []
    wanted = sorted(set(ticks))
    for tick in range(1, (wanted[-1] if wanted else 0) + 1):
        for step in script:
            if step.tick == tick:
                view = window.current_view
                (view.on_key_press if step.down else view.on_key_release)(step.key, 0)
        window.current_view.on_update(TICK_SECONDS)
        if tick in wanted:
            window.current_view.on_draw()
            frame = read_frame(window)
            if crop is not None:
                left, top, width, height = crop
                frame = frame.crop((left, top, left + width, top + height))
            frames.append(frame)
    if not frames:
        raise ValueError("no ticks to capture")
    sheet = Image.new("RGBA", (sum(f.width for f in frames), frames[0].height))
    x = 0
    for frame in frames:
        sheet.paste(frame, (x, 0))
        x += frame.width
    if scale > 1:
        sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.Resampling.NEAREST)
    return sheet


def versus_setup(players: int, cpus: bool = False, rules: SavedRules | None = None) -> MatchSetup:
    """Return a versus setup with the roster's first ``players`` characters: the first two
    on the keyboards, or (with ``cpus``) everyone but player 1 a CPU. ``rules`` are the
    rules to play under (the defaults if not given)."""
    count = min(max(players, 2), len(ROSTER))
    return replace(
        with_saved(MatchSetup(), rules or SavedRules()),
        characters=ROSTER[:count],
        devices=("keyboard:solo", *[""] * (count - 1)) if cpus else KEYBOARDS[:count],
        cpus=(0, *[HUD_CPU_LEVEL] * (count - 1)) if cpus else (),
    )


def open_screen(window: GameWindow, flow: GameFlow, screen: str, players: int = 2) -> None:
    """Show one of :data:`SCREENS`, set up so there is something to look at.

    Raises:
        ValueError: the name is unknown, or the screen is not built yet.
    """
    rules = flow.settings.rules
    if screen == "title":
        flow.show_title()
    elif screen == "main":
        flow.show_main_menu()
    elif screen == "rules":
        flow.show_rules()
    elif screen == "pool":
        flow.show_random_pool()
    elif screen == "settings":
        flow.show_settings()
    elif screen == "soundtest":
        flow.show_sound_test()
    elif screen == "controls":
        flow.show_controls()
    elif screen == "controls_pad":
        flow.show_controls(tab=2)
    elif screen == "kit":
        window.show_view(UiKitView(window.pixel_buffer, flow))
    elif screen == "charselect":
        flow.show_character_select(flow.setup)
    elif screen == "stageselect":
        flow.show_stage_select(versus_setup(players, rules=rules))
    elif screen in ("hud", "pause"):
        count = max(players, 4) if screen == "hud" else players
        flow.start_battle(versus_setup(count, cpus=True, rules=rules))
        view = window.current_view
        assert isinstance(view, BattleView)
        view.show_help = False
        for fighter, percent in zip(view.match.fighters, HUD_DAMAGE, strict=False):
            view.match.set_damage(fighter.player_index, percent)
        if screen == "pause":
            view.open_menu()
    elif screen == "training":
        flow.start_battle(training_setup())
        view = window.current_view
        assert isinstance(view, BattleView)
        view.show_help = False
        view.open_menu()
    elif screen == "results":
        flow.start_battle(versus_setup(players, cpus=True, rules=rules))
        view = window.current_view
        assert isinstance(view, BattleView)
        # Level 5 CPUs fight for a while, so the results have numbers to show; then, as in
        # the tests, everyone but player 1 is dropped out of bounds until the match ends.
        for tick in range(RESULTS_TICK_LIMIT):
            if isinstance(window.current_view, ResultsView):
                break
            if tick >= RESULTS_FIGHT_TICKS and view.match.result is None:
                standing = [f for f in view.match.fighters[1:] if f.in_play]
                if standing:
                    standing[-1].pos = OUT_OF_BOUNDS
            window.current_view.on_update(TICK_SECONDS)
        else:
            raise ValueError("the match never reached the results screen")
    elif screen == "loading":
        flow.loading = True
        flow.begin_match(versus_setup(players, cpus=players > 2, rules=rules))
    elif screen == "boot":
        flow.show_boot()
    else:
        raise ValueError(f"unknown screen {screen!r}: expected one of {', '.join(SCREENS)}")


def capture_screen(
    window: GameWindow,
    screen: str,
    script: Sequence[KeyStep] = (),
    ticks: Sequence[int] = (30,),
    crop: tuple[int, int, int, int] | None = None,
    scale: int = 1,
    players: int = 2,
    seed: int = 0,
    settings: Settings | None = None,
) -> Image.Image:
    """Show a screen of the game's flow and return the frames at ``ticks`` side by side.

    Args:
        window: a (hidden) game window.
        screen: one of :data:`SCREENS`.
        script: key events, sent to whatever scene is showing (so a script can walk on).
        ticks: which ticks to capture, counted from when the screen opens.
        crop: ``left, top, width, height`` in native pixels, applied to every frame.
        scale: integer upscale of the sheet.
        players: how many fighters, where the screen has fighters.
        seed: the session seed.
        settings: the user settings to show (the defaults if not given; never saved).
    """
    window.switch_to()
    flow = GameFlow(window, window.pixel_buffer, seed=seed, settings=settings)
    open_screen(window, flow, screen, players)
    return _run(window, script, ticks, crop, scale)


def stage_views(stage: Stage) -> list[tuple[str, tuple[float, float]]]:
    """Return what a stage sheet looks at closely, as (name, world pixel) pairs: the four
    spawns, the stage's left and right edges, its underside and its highest surface."""
    views = []
    for player in range(4):
        spot = stage.spawn_point(player)
        views.append((f"p{player + 1} spawn", project(spot.x, spot.y, spot.z + SPAWN_LOOK_HEIGHT)))
    bottom = stage.underside
    sides: list[tuple[float, float]] = []
    tops: list[tuple[float, tuple[float, float]]] = []
    unders: list[tuple[float, float]] = []
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell is None:
                continue
            for x, y in ((cx, cy), (cx + 1, cy), (cx, cy + 1), (cx + 1, cy + 1)):
                sides.append(project(x, y, (cell.top + bottom) / 2))
                unders.append(project(x, y, bottom))
            tops.append((cell.top, project(cx + 0.5, cy + 0.5, cell.top)))
    for platform in stage.soft_platforms:
        middle_x, middle_y = (platform.x0 + platform.x1) / 2, (platform.y0 + platform.y1) / 2
        tops.append((platform.z, project(middle_x, middle_y, platform.z)))
    # Each is framed with the stage filling most of the picture, not half of it.
    left, right = min(sides), max(sides)
    under = min(unders, key=lambda point: point[1])
    views.append(("left edge", (left[0] + EDGE_INSET, left[1])))
    views.append(("right edge", (right[0] - EDGE_INSET, right[1])))
    views.append(("underside", (under[0], under[1] + UNDERSIDE_INSET)))
    views.append(("top", max(tops, key=lambda top: (top[0], top[1][1]))[1]))
    return views


def _label(image: Image.Image, text: str) -> None:
    """Write a small caption in the image's top left corner."""
    draw = ImageDraw.Draw(image)
    draw.text((5, 4), text, fill=LABEL_SHADE)
    draw.text((4, 3), text, fill=LABEL_COLOUR)


def _hazard_rules(hazards: bool) -> MatchRules:
    """Return the rules for a stage sheet: the sandbox's, with the stage's mechanics on or
    off (decision D-063)."""
    return replace(MatchRules(), stage_hazards=hazards)


DEPTH_LAB_CROP: tuple[int, int] = (200, 150)
"""Native pixels of each depth-lab picture: the fighter and the ground around its marker."""
DEPTH_LAB_SCALE = 2
DEPTH_LAB_PAIRS = 4


def capture_depth_lab(
    window: GameWindow,
    stage_id: str,
    pairs: int = DEPTH_LAB_PAIRS,
    character: str = "rook",
    seed: int = 0,
    scale: int = 1,
) -> Image.Image:
    """Return a stage's depth-lab sheet (decision D-065): one row per pair of
    :func:`isofightr.render.depth_cues.off_stage_twins`, with a fighter standing on the
    ground on the left and the same fighter in the air off the stage, on the same pixels, on
    the right. Each picture is the same crop of the screen at twice the size, with the HUD
    off, so the two differ only in what the game draws to tell the places apart.

    The other fighter of the match waits on the spawn furthest from the pair.
    """
    window.switch_to()
    stage = load_stage(stage_id)
    twins = off_stage_twins(stage, pairs)
    if not twins:
        raise ValueError(f"{stage_id} has no ground point with a twin over the void")
    view = BattleView(window.pixel_buffer, stage, [load_character(character)] * 2, seed=seed)
    view.show_help = False
    view.hud_display = False
    window.show_view(view)
    view.on_update(TICK_SECONDS)
    camera = view.camera
    camera.clamped = False
    first, second = view.match.fighters[0], view.match.fighters[1]
    wide, tall = DEPTH_LAB_CROP[0] * DEPTH_LAB_SCALE, DEPTH_LAB_CROP[1] * DEPTH_LAB_SCALE
    sheet = Image.new("RGBA", (2 * wide, len(twins) * tall), LABEL_SHADE)
    spawns = [stage.spawn_point(index) for index in range(len(stage.spawns))]
    for row, pair in enumerate(twins):
        ground = Vec3(*pair.ground)
        away = max(spawns, key=lambda spawn: (spawn - ground).length())
        world_x, world_y = project(*pair.ground)
        for column, (spot, where) in enumerate(
            ((pair.ground, "on the ground"), (pair.air, "in the air, off the stage"))
        ):
            first.pos, second.pos = Vec3(*spot), away
            first.vel = second.vel = Vec3(0.0, 0.0, 0.0)
            first.facing = second.facing = Dir8.SE
            camera.x, camera.y = world_x, world_y + DEPTH_LAB_CROP[1] // 6
            view.on_draw()
            centre_x, centre_y = view.view_centre()
            at_x = NATIVE_W // 2 + round(world_x - centre_x)
            at_y = NATIVE_H // 2 - round(world_y - centre_y)
            left = min(max(at_x - DEPTH_LAB_CROP[0] // 2, 0), NATIVE_W - DEPTH_LAB_CROP[0])
            upper = min(max(at_y - DEPTH_LAB_CROP[1] * 2 // 3, 0), NATIVE_H - DEPTH_LAB_CROP[1])
            frame = read_frame(window).crop(
                (left, upper, left + DEPTH_LAB_CROP[0], upper + DEPTH_LAB_CROP[1])
            )
            frame = frame.resize((wide, tall), Image.Resampling.NEAREST)
            place = ", ".join(f"{value:g}" for value in spot)
            _label(frame, f"{stage_id}  {where}  ({place})")
            sheet.paste(frame, (column * wide, row * tall))
    if scale > 1:
        sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.Resampling.NEAREST)
    return sheet


def capture_stage_sheet(
    window: GameWindow,
    stage_id: str,
    ticks: Sequence[int] = STAGE_SHEET_TICKS,
    hazards: bool = True,
    characters: Sequence[str] = ROSTER,
    seed: int = 0,
    scale: int = 1,
) -> Image.Image:
    """Return a stage's review sheet (decision D-063): one row per tick, each the whole
    screen as a match shows it (four idle fighters on the spawns, the HUD in place) followed
    by close-ups, at twice the size and without the HUD, of each of :func:`stage_views`.

    The close-ups move only the camera, between two ticks, and put it back.

    Args:
        window: a (hidden) game window.
        stage_id: the stage to show.
        ticks: which ticks to capture, in increasing order.
        hazards: whether the stage's hazards and mechanics are on.
        characters: who stands on the spawns.
        seed: the match seed.
        scale: integer upscale of the whole sheet.
    """
    window.switch_to()
    stage = load_stage(stage_id)
    view = BattleView(
        window.pixel_buffer,
        stage,
        [load_character(name) for name in characters],
        seed=seed,
        rules=_hazard_rules(hazards),
    )
    view.show_help = False
    window.show_view(view)
    views = stage_views(stage)
    wide, tall = CLOSE_UP[0] * CLOSE_UP_SCALE, CLOSE_UP[1] * CLOSE_UP_SCALE
    rows_of_close_ups = -(-len(views) // CLOSE_UP_COLUMNS)
    row_height = max(NATIVE_H, rows_of_close_ups * tall)
    wanted = sorted(set(ticks))
    if not wanted:
        raise ValueError("no ticks to capture")
    sheet = Image.new(
        "RGBA", (NATIVE_W + CLOSE_UP_COLUMNS * wide, row_height * len(wanted)), LABEL_SHADE
    )
    camera = view.camera
    for tick in range(1, wanted[-1] + 1):
        view.on_update(TICK_SECONDS)
        if tick not in wanted:
            continue
        top = wanted.index(tick) * row_height
        view.on_draw()
        overview = read_frame(window)
        state = "on" if hazards else "off"
        _label(overview, f"{stage_id}  tick {tick}  hazards {state}")
        sheet.paste(overview, (0, top))
        kept = (camera.x, camera.y, camera.clamped, view.hud_display)
        camera.clamped, view.hud_display = False, False
        for index, (name, (world_x, world_y)) in enumerate(views):
            camera.x, camera.y = world_x, world_y
            centre_x, centre_y = view.view_centre()
            # Where the point lands in the frame (rows count down), whatever the lift is.
            at_x = NATIVE_W // 2 + round(world_x - centre_x)
            at_y = NATIVE_H // 2 - round(world_y - centre_y)
            view.on_draw()
            left = min(max(at_x - CLOSE_UP[0] // 2, 0), NATIVE_W - CLOSE_UP[0])
            upper = min(max(at_y - CLOSE_UP[1] // 2, 0), NATIVE_H - CLOSE_UP[1])
            close = read_frame(window).crop((left, upper, left + CLOSE_UP[0], upper + CLOSE_UP[1]))
            close = close.resize((wide, tall), Image.Resampling.NEAREST)
            _label(close, name)
            column, row = index % CLOSE_UP_COLUMNS, index // CLOSE_UP_COLUMNS
            sheet.paste(close, (NATIVE_W + column * wide, top + row * tall))
        camera.x, camera.y, camera.clamped, view.hud_display = kept
    if scale > 1:
        sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.Resampling.NEAREST)
    return sheet
