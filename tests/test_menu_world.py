"""The Isle, the island every menu is drawn on: its stage, its stations and its camera
(decision D-072, M21). Pure: no window.
"""

import itertools

import pytest
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.backdrop_rules import check_stage, failures
from isofightr.data.character_loader import list_character_ids
from isofightr.data.paths import ASSETS_DIR
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.data.stage_loader import list_stage_ids
from isofightr.render.backdrop import MOODS, PAINTERS
from isofightr.scenes.menu_world_model import (
    DROP_HEIGHT,
    DROP_TICKS,
    GLIDE_TICKS,
    ISLE_DIR,
    LAND_TICKS,
    READY_TICKS,
    REST_ZOOMS,
    RING_LINE,
    RING_SPOTS,
    STATIONS,
    STROLL_BOUNDS,
    WORKSHOP_SPOT,
    Mood,
    Pose,
    StandIn,
    camera_at,
    load_isle,
    rest_pose,
    ring_look,
    ring_pose,
    screen_point,
)

TALL_PROPS = {"arch", "arch_broken", "arch_broken_r", "column", "cypress", "banner", "support"}
"""Props tall enough to cover a fighter standing behind them."""
FIGHTER_HALF_WIDTH = 0.75
"""Half the width of the widest fighter, in tiles (Bramble), with a little room."""


def test_the_isle_is_a_stage_nobody_can_pick() -> None:
    isle = load_isle()
    assert isle.id == "isle"
    assert "isle" not in list_stage_ids()
    assert not isle.soft_platforms and not isle.hazards, "nothing on it moves or hurts"


def test_the_isles_backdrop_stays_behind_it() -> None:
    reports = check_stage(load_isle(), stages_dir=ASSETS_DIR / "ui")
    assert reports and reports[0].sky
    assert not failures(reports)


def test_the_isles_backdrop_is_what_its_painter_draws() -> None:
    layers = PAINTERS["cloud_sea"](MOODS["day"], 21)
    assert list(layers) == [layer.image for layer in load_isle().backgrounds]
    for name, image in layers.items():
        committed = Image.open(ISLE_DIR / name).convert("RGBA")
        assert committed.tobytes() == image.convert("RGBA").tobytes(), name
    assert {path.name for path in ISLE_DIR.glob("bg_*.png")} == set(layers)


def test_the_ring_is_a_row_across_the_screen_on_solid_ground() -> None:
    isle = load_isle()
    assert len(RING_SPOTS) == 4
    for x, y in RING_SPOTS:
        assert x + y == pytest.approx(RING_LINE), "side by side on screen"
        assert isle.surface_top(x, y) == 0.0
    across = [x - y for x, y in RING_SPOTS]
    assert across == sorted(across), "left to right"
    pose = rest_pose(STATIONS["ring"])
    columns = [screen_point(pose, x, y)[0] for x, y in RING_SPOTS]
    assert columns == [80, 240, 400, 560], "a quarter of the screen each"
    assert len({screen_point(pose, x, y)[1] for x, y in RING_SPOTS}) == 1


def test_no_tall_prop_stands_in_front_of_a_ring_spot() -> None:
    isle = load_isle()
    for prop in isle.props:
        if prop.sprite not in TALL_PROPS:
            continue
        for x, y in RING_SPOTS:
            in_front = prop.x + prop.y > x + y
            same_column = abs((prop.x - prop.y) - (x - y)) < 2 * FIGHTER_HALF_WIDTH
            assert not (in_front and same_column), f"{prop.sprite} covers the spot at {x}, {y}"


def test_the_workshop_spot_and_the_plaza_are_open_ground() -> None:
    isle = load_isle()
    assert isle.surface_top(*WORKSHOP_SPOT) == 0.0
    for depth in (0.0, 0.5, 1.0):
        for across in (0.0, 0.5, 1.0):
            x, y = STROLL_BOUNDS.point(depth, across)
            assert STROLL_BOUNDS.holds(x, y)
            assert isle.surface_top(x, y) == 0.0, "the plaza is solid to its corners"
    for prop in isle.props:
        assert not STROLL_BOUNDS.holds(prop.x, prop.y), f"{prop.sprite} stands in the plaza"
    assert not any(STROLL_BOUNDS.holds(x, y) for x, y in RING_SPOTS)
    for spawn in isle.spawns:
        assert STROLL_BOUNDS.holds(spawn.x, spawn.y), "the strollers start in the plaza"


@pytest.mark.parametrize("name", list(STATIONS))
def test_a_station_rests_on_whole_pixels_and_shows_its_point_at_its_anchor(name: str) -> None:
    station = STATIONS[name]
    pose = rest_pose(station)
    assert station.zoom in REST_ZOOMS
    assert pose.resting
    assert screen_point(pose, *station.look_at) == station.anchor
    assert 0 <= station.anchor[0] < NATIVE_W and 0 <= station.anchor[1] < NATIVE_H


def test_only_the_ring_sends_the_strollers_away() -> None:
    assert [name for name, station in STATIONS.items() if not station.strollers] == ["ring"]


def test_the_glide_starts_at_one_pose_ends_at_the_other_and_never_overshoots() -> None:
    start, goal = rest_pose(STATIONS["gate"]), rest_pose(STATIONS["ring"])
    assert camera_at(0, start, goal) == start
    assert camera_at(GLIDE_TICKS, start, goal) == goal
    assert camera_at(GLIDE_TICKS + 500, start, goal) == goal
    low, high = sorted((start.zoom, goal.zoom))
    last = start
    for tick in range(GLIDE_TICKS + 1):
        pose = camera_at(tick, start, goal)
        assert low <= pose.zoom <= high
        assert min(start.x, goal.x) <= pose.x <= max(start.x, goal.x)
        assert min(start.y, goal.y) <= pose.y <= max(start.y, goal.y)
        assert abs(pose.zoom - goal.zoom) <= abs(last.zoom - goal.zoom), "always nearer"
        last = pose


def test_only_a_glide_has_a_fraction_of_a_zoom() -> None:
    start, goal = rest_pose(STATIONS["plaza"]), rest_pose(STATIONS["workshop"])
    moving = [camera_at(tick, start, goal) for tick in range(1, GLIDE_TICKS)]
    assert any(not pose.resting for pose in moving)
    assert camera_at(GLIDE_TICKS, start, goal).resting
    same = rest_pose(STATIONS["gate"])
    assert camera_at(5, same, same) == same


def test_a_pose_gives_the_renderer_whole_pixels() -> None:
    pose = Pose(10.4, -3.6, 1.5)
    assert pose.centre == (10, -4)
    assert not pose.resting


# --- the ring's stand-ins ----------------------------------------------------------------------


def test_a_fighter_drops_onto_its_spot_lands_and_then_stands() -> None:
    assert (
        ring_pose(Mood.DROP_IN, 0).lift == DROP_HEIGHT and ring_pose(Mood.DROP_IN, 0).anim == "fall"
    )
    lifts = [ring_pose(Mood.DROP_IN, tick).lift for tick in range(DROP_TICKS + 1)]
    assert lifts == sorted(lifts, reverse=True) and lifts[-1] == 0.0, "down, never up"
    steps = [high - low for high, low in itertools.pairwise(lifts)]
    assert steps[-2] > steps[0], "it speeds up as it falls"
    landing = ring_pose(Mood.DROP_IN, DROP_TICKS)
    assert (landing.lift, landing.anim, landing.frame) == (0.0, "land", 1)
    after = ring_pose(Mood.DROP_IN, DROP_TICKS + LAND_TICKS)
    assert (after.anim, after.frame) == ("idle", 1), "then it stands easy"
    assert ring_pose(Mood.DROP_IN, -5) == ring_pose(Mood.DROP_IN, 0)


def test_the_other_moods_stand_on_the_ground() -> None:
    assert ring_pose(Mood.IDLE, 30) == ring_pose(Mood.IDLE, 30)
    assert ring_pose(Mood.IDLE, 7).anim == "idle" and not ring_pose(Mood.IDLE, 7).dim
    assert ring_pose(Mood.READY, 0).anim == "taunt"
    assert ring_pose(Mood.READY, READY_TICKS).anim == "idle", "the pose ends; ready stays"
    assert ring_pose(Mood.WIN, 400).anim == "victory", "a winner goes on celebrating"
    lost = ring_pose(Mood.LOST, 3)
    assert lost.anim == "idle" and lost.dim
    for mood in Mood:
        if mood is not Mood.DROP_IN:
            assert all(ring_pose(mood, tick).lift == 0.0 for tick in (0, 9, 300))


@pytest.mark.parametrize("character", list_character_ids())
def test_every_character_has_what_the_ring_shows(character: str) -> None:
    sprite_set = load_sprite_set(character)
    assert sprite_set is not None
    anims = sprite_set.anims
    for mood in Mood:
        for tick in (0, DROP_TICKS, DROP_TICKS + LAND_TICKS, 500):
            pose = ring_pose(mood, tick)
            assert pose.anim in anims, f"{character} has no {pose.anim!r}"
            look = ring_look(character, anims, pose, costume=2)
            assert look.sprite is not None and look.sprite.exact
            assert look.sprite.anim == pose.anim and 0 <= look.sprite.pose < anims[pose.anim].poses
            assert (look.character, look.costume, look.dim) == (character, 2, pose.dim)


def test_a_look_falls_back_to_idle_and_then_to_the_capsule() -> None:
    anims = load_sprite_set("rook").anims
    only_idle = {"idle": anims["idle"]}
    look = ring_look("rook", only_idle, ring_pose(Mood.WIN, 0), 0)
    assert look.sprite is not None and look.sprite.anim == "idle" and not look.sprite.exact
    bare = ring_look("nobody", {}, ring_pose(Mood.LOST, 0), 0)
    assert bare.sprite is None and bare.dim, "no sheets: the placeholder capsule, still dimmed"


def test_a_stand_in_is_an_entity_the_renderer_can_draw() -> None:
    stand_in = StandIn(2, "mote", costume=3, color_index=1, mood=Mood.DROP_IN, since=100)
    assert stand_in.entity_id >= 100 and stand_in.player_index == 2 and stand_in.color_index == 1
    assert not stand_in.invincible and not stand_in.on_revival_platform
    x, y = RING_SPOTS[2]
    high = stand_in.pos_at(100)
    assert (high.x, high.y, high.z) == (x, y, DROP_HEIGHT)
    assert stand_in.pos_at(100 + DROP_TICKS).z == 0.0
    assert stand_in.pose(100 + DROP_TICKS).anim == "land"
    ids = {StandIn(index, "rook").entity_id for index in range(4)}
    assert len(ids) == 4 and not ids & {0, 1, 2, 3}, "clear of the strolling fighters' ids"
    assert stand_in.facing.name == "S", "it faces out of the screen"
