"""Render tests for the isometric world: need a real OpenGL window (``pytest -m gl``).

These check the M1 exit criterion mechanically: "the placeholder renders correctly in front
of, behind and below every edge of Sky Ruins, and its shadow and ring are always correct".

The occlusion test sweeps a fighter through a grid of positions around and inside each
stage, renders every one, and compares two body pixels against a geometric oracle that knows
nothing about draw order: a pixel is visible exactly when no stage geometry lies between
that point of the fighter and the camera.
"""

import itertools
from typing import Any

import pytest

from isofightr.config import DECK_THICKNESS, ISLAND_THICKNESS, NATIVE_H, NATIVE_W, TILE_H, Z_PX
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render import placeholder_art as art
from isofightr.render.camera import snap
from isofightr.render.iso import HALF_TILE_W, project
from isofightr.sim.input_frame import Dir8
from isofightr.sim.math3d import Vec2, Vec3
from isofightr.sim.stage import SoftPlatform, Stage, build_stage

pytestmark = pytest.mark.gl

RAY_START = 1e-6
STABILITY_MARGIN_PX = 1.25
"""A sample only counts when the oracle agrees this far around it, so tile-edge pixels,
where the sprite's stair-step outline differs from the ideal edge, are skipped."""
LEG_SAMPLE_ABOVE_FEET = 4
HEAD_SAMPLE_ABOVE_FEET = 34
FAR_AWAY = Vec3(200.0, 200.0, 0.0)
BODY_HEIGHT_UNITS = art.BODY_HEIGHT / Z_PX

P1_BODY = art.player_color(0)
P1_HEAD = art.shade(P1_BODY, art.HEAD_SHADE)


def blocks_stage() -> Stage:
    """A synthetic stage with raised blocks of several heights and a platform."""
    return build_stage(
        id="blocks",
        display_name="Blocks",
        tileset="grid",
        grid_rows=[
            "0000000",
            "0200010",
            "0000000",
            "0003000",
            "0000000",
            "0100020",
            "0000000",
        ],
        legend={},
        soft_platforms=[SoftPlatform(0, 0, 2, 2, 3.5)],
        spawns=[Vec2(0.5, 2.5)] * 4,
        respawn=Vec2(0.5, 2.5),
        blast_side=7.0,
        blast_top=14.0,
        blast_bottom=-8.0,
        camera_margin=4.0,
    )


STAGES = {
    "sky_ruins": lambda: load_stage("sky_ruins"),
    "training_grid": lambda: load_stage("training_grid"),
    "blocks": blocks_stage,
}


# --- the oracle ---------------------------------------------------------------------------


def _ray_hits_box(
    origin: Vec3, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float
) -> bool:
    """Whether the view ray from ``origin`` toward the camera passes through a box.

    Toward the camera, x, y and z all grow at the same rate, so the ray is origin + t(1,1,1).
    """
    enter = max(x0 - origin.x, y0 - origin.y, z0 - origin.z, RAY_START)
    leave = min(x1 - origin.x, y1 - origin.y, z1 - origin.z)
    return enter < leave


def hidden_by_stage(stage: Stage, point: Vec3) -> bool:
    """Whether any stage geometry lies between a world point and the camera."""
    bottom = stage.bounds.z_min - ISLAND_THICKNESS
    for cy, row in enumerate(stage.cells):
        for cx, cell in enumerate(row):
            if cell and _ray_hits_box(point, cx, cx + 1, cy, cy + 1, bottom, cell.top):
                return True
    return any(
        _ray_hits_box(point, p.x0, p.x1, p.y0, p.y1, p.z - DECK_THICKNESS, p.z)
        for p in stage.soft_platforms
    )


def billboard_point(depth_key: float, screen_x: float, screen_y: float) -> Vec3:
    """The world point at a screen position on the upright sprite plane at ``depth_key``."""
    difference = screen_x / HALF_TILE_W
    return Vec3(
        (depth_key + difference) / 2,
        (depth_key - difference) / 2,
        (screen_y + depth_key * TILE_H / 2) / Z_PX,
    )


def stable_verdict(stage: Stage, depth_key: float, screen_x: float, screen_y: float) -> bool | None:
    """Return whether a sprite pixel is hidden, or ``None`` if it is too close to an edge."""
    offsets = [(0.0, 0.0)] + [
        (dx * STABILITY_MARGIN_PX, dy * STABILITY_MARGIN_PX)
        for dx, dy in itertools.product((-1, 1), repeat=2)
    ]
    verdicts = {
        hidden_by_stage(stage, billboard_point(depth_key, screen_x + dx, screen_y + dy))
        for dx, dy in offsets
    }
    return verdicts.pop() if len(verdicts) == 1 else None


def is_physical(stage: Stage, pos: Vec3) -> bool:
    """Skip positions the game can never produce: inside solid ground, or half-way through a
    platform the fighter is inside the footprint of (the one documented approximation)."""
    top = stage.surface_top(pos.x, pos.y)
    if top is not None and pos.z < top:
        return False
    return not any(
        platform.contains(pos.x, pos.y) and pos.z < platform.z < pos.z + BODY_HEIGHT_UNITS + 0.5
        for platform in stage.soft_platforms
    )


# --- rendering helpers --------------------------------------------------------------------


def make_view(window: Any, stage: Stage) -> Any:
    from isofightr.scenes.battle import BattleView

    window.switch_to()
    view = BattleView(window.pixel_buffer, stage, [load_character("rook")] * 2)
    window.show_view(view)
    view.camera.clamped = False
    view.match.fighters[1].pos = FAR_AWAY
    return view


def render(view: Any, pos: Vec3, facing: Dir8 = Dir8.N) -> tuple[int, int]:
    """Place P1, centre the camera on it, draw, and return the camera centre.

    Only the fighter's position and facing are set: rendering reads nothing else, and no
    tick runs, so it does not matter that the position may be in mid-air.
    """
    fighter = view.match.fighters[0]
    fighter.pos, fighter.facing = pos, facing
    view.camera.snap_to([pos])
    view.on_draw()
    return view.camera.pixel_centre


def read_pixel(
    window: Any, camera_centre: tuple[int, int], world_x: int, world_y: int
) -> tuple[int, ...]:
    """Read the native-buffer pixel that covers a whole world-pixel coordinate."""
    native_x = world_x - camera_centre[0] + NATIVE_W // 2
    native_y = world_y - camera_centre[1] + NATIVE_H // 2
    data = window.pixel_buffer.framebuffer.read(viewport=(native_x, native_y, 1, 1), components=4)
    return tuple(data)


def same_color(pixel: tuple[int, ...], color: tuple[int, ...]) -> bool:
    """Compare the RGB of two colors, allowing one 8-bit level per channel.

    The faint "x-ray" copy of a partly hidden fighter is blended over the fighter itself.
    That leaves the color alone (give or take GPU rounding) but lowers the buffer's alpha,
    which never reaches the screen: the upscale forces alpha to 1.
    """
    return all(abs(a - b) <= 1 for a, b in zip(pixel[:3], color[:3], strict=True))


def frange(start: float, stop: float, step: float) -> list[float]:
    count = int((stop - start) / step) + 1
    return [round(start + index * step, 4) for index in range(count)]


# --- occlusion ----------------------------------------------------------------------------


@pytest.mark.parametrize("stage_name", list(STAGES))
def test_fighter_is_hidden_exactly_where_stage_geometry_is_in_front(
    window: Any, stage_name: str
) -> None:
    stage = STAGES[stage_name]()
    view = make_view(window, stage)
    xs = frange(stage.bounds.x_min - 2.3, stage.bounds.x_max + 2.3, 0.65)
    ys = frange(stage.bounds.y_min - 2.3, stage.bounds.y_max + 2.3, 0.65)
    zs = [-3.0, -1.2, -0.4, 0.0, 0.9, 2.0, 2.5, 3.5, 4.5, 6.0]

    checked = hidden = 0
    failures: list[str] = []
    for x, y, z in itertools.product(xs, ys, zs):
        pos = Vec3(x, y, z)
        if not is_physical(stage, pos):
            continue
        centre = render(view, pos)
        feet_x, feet_y = (snap(value) for value in project(x, y, z))
        for above_feet, color in [
            (LEG_SAMPLE_ABOVE_FEET, P1_BODY),
            (HEAD_SAMPLE_ABOVE_FEET, P1_HEAD),
        ]:
            pixel_x, pixel_y = feet_x - 1, feet_y + above_feet
            expect_hidden = stable_verdict(stage, x + y, pixel_x + 0.5, pixel_y + 0.5)
            if expect_hidden is None:
                continue
            checked += 1
            hidden += expect_hidden
            shows_fighter = same_color(read_pixel(window, centre, pixel_x, pixel_y), color)
            if shows_fighter == expect_hidden:
                failures.append(
                    f"({x}, {y}, {z}) +{above_feet}px: expected "
                    f"{'hidden' if expect_hidden else 'visible'}"
                )

    assert checked > 1000, "the sweep should exercise plenty of positions"
    assert 0 < hidden < checked, "the sweep should include both hidden and visible samples"
    assert not failures, f"{len(failures)} of {checked} wrong, e.g. {failures[:12]}"


def test_two_fighters_nearer_one_is_drawn_on_top(window: Any) -> None:
    stage = load_stage("training_grid")
    view = make_view(window, stage)
    near, far = view.match.fighters
    # Same screen column, half a unit apart in depth: the sprites overlap almost fully.
    far.pos, far.facing = Vec3(5.0, 5.0, 0.0), Dir8.N
    centre = render(view, Vec3(5.25, 5.25, 0.0))
    feet_x, feet_y = (snap(value) for value in project(near.pos.x, near.pos.y, near.pos.z))
    assert read_pixel(window, centre, feet_x - 1, feet_y + 20) != art.player_color(1)
    assert read_pixel(window, centre, feet_x - 1, feet_y + LEG_SAMPLE_ABOVE_FEET) == P1_BODY
    # Swap which one is nearer: now the blue fighter covers the red one's legs.
    far.pos = Vec3(5.5, 5.5, 0.0)
    centre = render(view, Vec3(5.25, 5.25, 0.0))
    blue_x, blue_y = (snap(value) for value in project(5.5, 5.5, 0.0))
    assert read_pixel(window, centre, blue_x - 1, blue_y + 8) == art.player_color(1)


# --- shadow and ring ----------------------------------------------------------------------


def ring_pixels(
    window: Any, centre: tuple[int, int], pos: Vec3, surface: float
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return the leftmost and rightmost pixels of the player ring on ``surface``."""
    ring_x, ring_y = (snap(value) for value in project(pos.x, pos.y, surface))
    half = art.SHADOW_WIDTH // 2
    return (
        read_pixel(window, centre, ring_x - half, ring_y),
        read_pixel(window, centre, ring_x + half - 1, ring_y),
    )


def test_ring_surrounds_a_fighter_standing_on_the_ground(window: Any) -> None:
    view = make_view(window, load_stage("sky_ruins"))
    pos = Vec3(6.5, 1.5, 0.0)
    left, right = ring_pixels(window, render(view, pos), pos, 0.0)
    assert left == right == P1_BODY


def test_shadow_stays_on_the_ground_while_the_fighter_jumps(window: Any) -> None:
    stage = load_stage("sky_ruins")
    view = make_view(window, stage)
    pos = Vec3(6.5, 1.5, 3.0)
    centre = render(view, pos)
    left, right = ring_pixels(window, centre, pos, 0.0)
    assert left == right == P1_BODY
    # The blob darkens the grass at the middle of the ring, well below the airborne body.
    ring_x, ring_y = (snap(value) for value in project(pos.x, pos.y, 0.0))
    under = read_pixel(window, centre, ring_x - 1, ring_y - 1)
    grass = {art.tile_palette("grass").top_light, art.tile_palette("grass").top_dark}
    assert under not in grass
    assert sum(under[:3]) < min(sum(color[:3]) for color in grass)


def test_shadow_lands_on_a_platform_the_fighter_is_above(window: Any) -> None:
    # The screen-right low platform (x 8..11, y 0..3, z 2.5).
    view = make_view(window, load_stage("sky_ruins"))
    on_deck = Vec3(9.5, 1.5, 2.5)
    left, right = ring_pixels(window, render(view, on_deck), on_deck, 2.5)
    assert left == right == P1_BODY
    # Under the platform instead, the ring is on the ground, not on the deck.
    under_deck = Vec3(9.5, 1.5, 0.0)
    centre = render(view, under_deck)
    assert ring_pixels(window, centre, under_deck, 0.0) == (P1_BODY, P1_BODY)
    assert P1_BODY not in ring_pixels(window, centre, under_deck, 2.5)


def test_no_shadow_over_the_void(window: Any) -> None:
    view = make_view(window, load_stage("sky_ruins"))
    pos = Vec3(15.0, 4.5, 1.0)
    centre = render(view, pos)
    for surface in (0.0, 1.0):
        assert P1_BODY not in ring_pixels(window, centre, pos, surface)


def test_shadow_is_clipped_at_the_island_edge(window: Any) -> None:
    view = make_view(window, load_stage("sky_ruins"))
    # 0.2 units from the +x (south-east) edge at x = 13: the ring's right end is over the void.
    pos = Vec3(12.8, 4.5, 0.0)
    left, right = ring_pixels(window, render(view, pos), pos, 0.0)
    assert left == P1_BODY
    assert right != P1_BODY


def test_shadow_is_clipped_at_a_platform_edge(window: Any) -> None:
    view = make_view(window, load_stage("sky_ruins"))
    # Standing on the screen-right low platform 0.2 units from its +x edge at x = 11.
    pos = Vec3(10.8, 1.5, 2.5)
    left, right = ring_pixels(window, render(view, pos), pos, 2.5)
    assert left == P1_BODY
    assert right != P1_BODY


def test_no_platform_hides_a_fighter_standing_on_another(window: Any) -> None:
    """The Sky Ruins platforms are spread along the screen-horizontal diagonal so that none of
    them covers a fighter standing on another (the plan's first layout did, decision D-023)."""
    view = make_view(window, load_stage("sky_ruins"))
    stage = view.stage
    for platform in stage.soft_platforms:
        pos = Vec3((platform.x0 + platform.x1) / 2, (platform.y0 + platform.y1) / 2, platform.z)
        left, right = ring_pixels(window, render(view, pos), pos, platform.z)
        assert left == right == P1_BODY, platform


# --- camera and overlay -------------------------------------------------------------------


def test_camera_centres_the_fighter_in_the_native_buffer(window: Any) -> None:
    view = make_view(window, load_stage("training_grid"))
    pos = Vec3(4.0, 7.0, 0.0)
    centre = render(view, pos)
    assert centre == tuple(snap(value) for value in project(pos.x, pos.y, pos.z))
    data = window.pixel_buffer.framebuffer.read(
        viewport=(NATIVE_W // 2 - 1, NATIVE_H // 2 + LEG_SAMPLE_ABOVE_FEET, 1, 1), components=4
    )
    assert tuple(data) == P1_BODY


def test_debug_overlay_and_fighter_info_draw(window: Any) -> None:
    view = make_view(window, load_stage("sky_ruins"))
    render(view, Vec3(6.5, 1.5, 0.0))
    plain = window.pixel_buffer.framebuffer.read(components=4)
    view.show_overlay = True
    view.on_draw()
    assert window.pixel_buffer.framebuffer.read(components=4) != plain
    assert view._info_lines[0].text.startswith("P1 idle f1 pos 6.50 1.50 0.00 vel +0.000")
    assert view._info_lines[4].text == "frame 0  camera clamp off"
    view.show_overlay = False
    view.on_draw()
    assert view._info_lines[0].text == ""
    view.show_fighter_info = True
    view.on_draw()
    assert view._info_lines[0].text.startswith("P1 idle") and view._info_lines[4].text == ""


def test_keys_drive_the_match_through_the_fixed_loop(window: Any) -> None:
    import arcade

    from isofightr.config import TICK_SECONDS
    from isofightr.sim.fighter import StateId

    view = make_view(window, load_stage("training_grid"))
    view.match.fighters[1].pos = view.stage.spawn_point(1)
    rook = view.match.fighters[0]
    start = rook.pos
    view.on_key_press(arcade.key.D, 0)
    view.on_update(TICK_SECONDS * 5)
    assert view.tick_count == view.match.frame == 5
    assert rook.state is StateId.DASH
    moved = rook.pos - start
    assert project(moved.x, moved.y)[0] > 0 and project(moved.x, moved.y)[1] == pytest.approx(0)
    view.on_key_release(arcade.key.D, 0)
    view.on_key_press(arcade.key.SPACE, 0)
    view.on_update(TICK_SECONDS * 4)
    assert rook.state is StateId.JUMP
    view.on_key_press(arcade.key.F8, 0)
    assert view.match.frame == 0 and view.match.fighters[0].pos == start


def test_a_fighter_behind_a_platform_shows_through_it(window: Any) -> None:
    """The x-ray copy: a body pixel hidden by a deck is drawn faintly over the deck."""
    import isofightr.render.world_renderer as world_renderer

    stage = load_stage("sky_ruins")
    # On the ground just behind the screen-left low platform (x 2..5, y 6..9, z 2.5).
    pos = Vec3(3.5, 5.5, 0.0)
    feet_x, feet_y = (snap(value) for value in project(pos.x, pos.y, pos.z))
    sample = (feet_x + 3, feet_y + 24)  # beside the arrow, 1.5 units up: behind the deck
    assert stable_verdict(stage, pos.x + pos.y, sample[0] + 0.5, sample[1] + 0.5) is True

    view = make_view(window, stage)
    with_xray = read_pixel(window, render(view, pos), *sample)
    world_renderer.OCCLUDED_FIGHTER_ALPHA = 0
    try:
        without_xray = read_pixel(window, render(view, pos), *sample)
    finally:
        world_renderer.OCCLUDED_FIGHTER_ALPHA = 96

    deck_colors = {art.DECK_PALETTE.top_light, art.DECK_PALETTE.top_dark}
    assert without_xray in deck_colors, "without the x-ray copy only the deck is seen"
    assert with_xray not in deck_colors
    assert not same_color(with_xray, P1_BODY), "it is a faint copy, not the fighter in front"
    # Pulled from the deck color toward the fighter's red: less green and blue.
    assert with_xray[1] < without_xray[1] and with_xray[2] < without_xray[2]


def test_invincible_fighter_blinks(window: Any) -> None:
    from isofightr.config import INVINCIBLE_BLINK_FRAMES

    view = make_view(window, load_stage("training_grid"))
    rook = view.match.fighters[0]
    pos = Vec3(6.0, 6.0, 0.0)
    rook.invincible_frames = 100
    feet_x, feet_y = (snap(value) for value in project(pos.x, pos.y, pos.z))
    seen = []
    for frame in range(4 * INVINCIBLE_BLINK_FRAMES):
        view.match.frame = frame
        centre = render(view, pos)
        # The head, not the legs: the ring around the feet has the same color as the body.
        pixel = read_pixel(window, centre, feet_x - 1, feet_y + HEAD_SAMPLE_ABOVE_FEET)
        seen.append(pixel == P1_HEAD)
    on, off = [True] * INVINCIBLE_BLINK_FRAMES, [False] * INVINCIBLE_BLINK_FRAMES
    assert seen == on + off + on + off


def test_revival_platform_is_drawn_under_a_respawning_fighter(window: Any) -> None:
    from isofightr.sim.fighter import GroundKind

    view = make_view(window, load_stage("training_grid"))
    rook = view.match.fighters[0]
    pos = Vec3(6.0, 6.0, 5.0)
    feet_x, feet_y = (snap(value) for value in project(pos.x, pos.y, pos.z))
    centre = render(view, pos)
    below_feet = read_pixel(window, centre, feet_x - 1, feet_y - 2)
    assert below_feet != art.REVIVAL_PALETTE.top_light
    rook.ground = GroundKind.REVIVAL
    centre = render(view, pos)
    assert read_pixel(window, centre, feet_x - 1, feet_y - 2) == art.REVIVAL_PALETTE.top_light


def test_keyboard_presets_do_not_collide(window: Any) -> None:
    """Needs arcade for the real key codes, hence a ``gl`` test."""
    from isofightr.input.devices import ARROWS_NUMPAD, LEFT_CLUSTER, SOLO_KEYBOARD

    for preset in (SOLO_KEYBOARD, LEFT_CLUSTER, ARROWS_NUMPAD):
        assert len(set(preset.keys())) == len(preset.keys()), preset.name
    # Either player-1 layout can share a keyboard with player 2's.
    assert not set(SOLO_KEYBOARD.keys()) & set(ARROWS_NUMPAD.keys())
    assert not set(LEFT_CLUSTER.keys()) & set(ARROWS_NUMPAD.keys())
