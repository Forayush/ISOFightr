"""Stage mechanics beyond the sim's own rules (decision D-063, M14 group 4): how they look and
sound, the depth sorter's moving blocks, the stage report, the CPU on a mechanic stage, and
recovery on every stage. Pure: no window (the screen is in ``test_stage_mechanics_gl.py``).
"""

from dataclasses import replace

import pytest
from PIL import Image

from helpers import hold, place, run
from isofightr.art.palettes import load_master
from isofightr.audio.cues import HAZARD_SOUNDS, event_cues, hazard_cues, required_sounds
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.data.stage_rules import check_stage, screen_extent
from isofightr.headless import run_cpu_match
from isofightr.render import hazard_art as art
from isofightr.render.depth import (
    PLATFORM_ITEM_BASE,
    DepthSorter,
    DynamicItem,
    dynamic_goes_first,
    moving_blocks,
    sprite_rect,
    static_hides,
)
from isofightr.render.effects import BattleEffects
from isofightr.render.hazard_look import (
    HAZARD_DECAL_BASE,
    STREAKS_ACTIVE,
    STREAKS_WARN,
    ground_marks,
    hazard_sprites,
)
from isofightr.scenes.rules_model import RULE_ROWS, with_default_rules
from isofightr.scenes.setup import MatchSetup
from isofightr.settings import SavedRules, Settings, rules_from_data
from isofightr.sim.events import BounceEvent, HazardHitEvent
from isofightr.sim.fighter import StateId
from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect
from isofightr.ui.hud_state import HudState
from test_stage_mechanics import BRIDGE, GEYSER, LIFT, ON, WIND, build, start, wait

MASTER = load_master("resurrect64")
ROSTER = [load_character(name) for name in list_character_ids()]
BOLT = {
    "kind": "lightning",
    "at": [7.0, 3.0],
    "radius": 1.0,
    "rest": 200,
    "warn": 60,
    "active": 6,
    "damage": 14.0,
}
VERTICAL_UP = 1


def colours(image: Image.Image) -> set[tuple[int, int, int]]:
    return {pixel[:3] for pixel in image.convert("RGBA").getdata() if pixel[3]}


# --- the rule in the game's own rules ------------------------------------------------------


def test_the_rule_is_on_in_the_game_saved_and_has_a_row() -> None:
    assert MatchSetup().stage_hazards and SavedRules().stage_hazards
    assert MatchSetup().rules().stage_hazards
    assert not MatchSetup(stage_hazards=False).rules().stage_hazards
    assert MatchSetup(training=True).rules().stage_hazards, "training plays with them too"
    assert not rules_from_data({"stage_hazards": False}).stage_hazards
    assert rules_from_data({}).stage_hazards, "an older settings file gets the default"
    row = next(row for row in RULE_ROWS if row.key == "stage_hazards")
    assert row.label == "STAGE HAZARDS" and row.has_switch and "plain" in row.help.lower()
    off = replace(MatchSetup(), stage_hazards=False)
    assert with_default_rules(off).stage_hazards
    assert (
        "stage_hazards = true" in Settings().to_toml() if hasattr(Settings(), "to_toml") else True
    )


# --- how hazards look ----------------------------------------------------------------------


def test_hazard_art_is_in_palette_and_sized_from_the_hazard() -> None:
    assert art.mark_size(1.0) == (47, 23), "a circle on the ground is an ellipse 2 to 1"
    for kind in art.MARK_COLOURS:
        lit = []
        for level in range(art.ACTIVE_LEVEL + 1):
            mark = art.build_mark(kind, 1.0, level)
            assert mark.size == art.mark_size(1.0) and colours(mark) <= MASTER
            lit.append(sum(1 for pixel in mark.getdata() if pixel[3]))
        assert lit == sorted(lit) and lit[0] < lit[-1], "a warning fills in as it nears"
        assert (
            art.build_mark(kind, 1.0, 1, 0).tobytes() != art.build_mark(kind, 1.0, 1, 1).tobytes()
        )
    for frame in range(art.JET_FRAMES):
        jet = art.build_jet(0.8, 5.0, frame)
        assert colours(jet) <= MASTER and 78 <= jet.height <= 86
        assert jet.tobytes() != art.build_jet(0.8, 5.0, (frame + 1) % art.JET_FRAMES).tobytes()
    assert art.build_jet(0.8, 5.0, 0, 0.4).height < art.build_jet(0.8, 5.0, 0, 1.0).height
    for frame in range(art.BOLT_FRAMES):
        bolt = art.build_bolt(9.0, frame)
        assert colours(bolt) <= MASTER and bolt.height == 144
    for direction in range(art.STREAK_DIRECTIONS):
        for size in range(len(art.STREAK_LENGTHS)):
            assert colours(art.build_streak(direction, size)) <= MASTER
    assert art.streak_direction(1.0, 0.0) == 0 and art.streak_direction(0.0, 1.0) == 4
    assert art.streak_direction(-1.0, 0.0) == 8


def test_marks_and_effects_follow_the_hazards_cycle() -> None:
    stage = build(hazards=[GEYSER, BOLT, WIND])
    assert ground_marks(stage, 100) == [] and hazard_sprites(stage, 100) == []
    warning = ground_marks(stage, 205)
    assert [mark.item_id for mark in warning] == [HAZARD_DECAL_BASE, HAZARD_DECAL_BASE + 1]
    assert (warning[0].x, warning[0].y, warning[0].surface) == (5.0, 5.0, 0.0)
    levels = [ground_marks(stage, frame)[0].key[3] for frame in (200, 215, 230, 245, 259, 260)]
    assert levels == [0, 1, 2, 3, 3, art.ACTIVE_LEVEL]
    assert len(hazard_sprites(stage, 205)) == STREAKS_WARN, "only the wind shows before it blows"
    going = hazard_sprites(stage, 262)
    kinds = [sprite.key[0] for sprite in going]
    assert kinds.count("hazard-jet") == 1 and kinds.count("hazard-bolt") == 1
    assert kinds.count("hazard-streak") == STREAKS_ACTIVE
    jet = next(sprite for sprite in going if sprite.key[0] == "hazard-jet")
    assert (jet.x, jet.bottom) == (0.0, -80.0), "its foot is on the hazard's place"
    assert ground_marks(stage, 262)[1].key[1] == "lightning"
    assert not [s for s in hazard_sprites(stage, 268) if s.key[0] == "hazard-bolt"], "6 frames"
    grown = [
        next(s for s in hazard_sprites(stage, frame) if s.key[0] == "hazard-jet").key[4]
        for frame in (260, 262, 266, 275, 288, 289)
    ]
    assert grown == [1, 3, 5, 5, 2, 1], "it rises, stands and falls"

    def shown(frame: int) -> list[tuple[object, ...]]:
        return [(sprite.key, sprite.x, sprite.bottom) for sprite in hazard_sprites(stage, frame)]

    assert shown(262) == shown(262), "a function of the frame"
    assert shown(262) != shown(263)


def test_reduce_flashing_holds_hazards_still() -> None:
    stage = build(hazards=[GEYSER, BOLT])
    steps = set()
    for frame in range(260, 266):
        steps |= {sprite.key for sprite in hazard_sprites(stage, frame, calm=True)}
    assert len({key for key in steps if key[0] == "hazard-bolt"}) == 1, "the bolt does not flicker"
    lively = set()
    for frame in range(260, 266):
        lively |= {s.key for s in hazard_sprites(stage, frame) if s.key[0] == "hazard-bolt"}
    assert len(lively) == art.BOLT_FRAMES
    assert {ground_marks(stage, frame, calm=True)[0].key[4] for frame in range(200, 230)} == {0}


# --- how they sound and what the HUD and effects make of a hit ------------------------------


def test_hazards_warn_and_go_off_with_a_sound() -> None:
    stage = build(hazards=[GEYSER, BOLT, WIND])
    assert hazard_cues(stage, 150) == []
    assert [cue.name for cue in hazard_cues(stage, 200)] == ["hazard_warn"] * 3
    assert [cue.name for cue in hazard_cues(stage, 260)] == ["geyser", "thunder", "gust"]
    assert hazard_cues(stage, 261) == [], "once, not every frame"
    assert hazard_cues(stage, 260)[0].position == Vec3(5.0, 5.0, 0.0)
    assert set(HAZARD_SOUNDS.values()) | {"hazard_warn", "spring"} <= required_sounds()
    hit = HazardHitEvent(0, "geyser", 1, 12.0, 60.0, Vec3(1, 1, 1), Effect.FIRE, 11, False)
    blocked = replace(hit, blocked=True, knockback=0.0)
    names = [cue.name for cue in event_cues([hit, blocked, BounceEvent(0, Vec3(), 0.4)])]
    assert names[0].endswith("_fire") and names[1:] == ["shield_hit", "spring"]


def test_a_hazard_hit_sparks_shakes_and_shows_its_damage() -> None:
    hit = HazardHitEvent(0, "geyser", 1, 12.0, 90.0, Vec3(1, 1, 1), Effect.FIRE, 11, False)
    effects = BattleEffects()
    effects.consume([hit])
    assert len(effects.sparks) == 1 and effects.flash[1] > 0 and effects.shake.current() > 0
    shield = BattleEffects()
    shield.consume([replace(hit, blocked=True)])
    assert len(shield.sparks) == 1 and 1 not in shield.flash, "a blocked one only sparks"
    bounce = BattleEffects()
    bounce.consume([BounceEvent(0, Vec3(), 0.4)])
    assert bounce.puffs and bounce.rings
    match = start(build(hazards=[GEYSER]))
    hud = HudState()
    hud.step(match.fighters, [hit], False)
    assert [popup.damage for popup in hud.popups] == [12.0] and hud.flash[1] > 0
    quiet = HudState()
    quiet.step(match.fighters, [replace(hit, blocked=True)], False)
    assert not quiet.popups


# --- the depth sorter's moving blocks ------------------------------------------------------


def test_a_moving_platform_is_dynamic_blocks_not_static_decks() -> None:
    rest = build(soft_platforms=[BRIDGE, {"rect": [1, 1, 3, 3], "z": 2.5}])
    sorter = DepthSorter(rest)
    decks = [item for item in sorter.statics if item.platform_index == 0]
    assert not decks, "the moving one has no static cells (nor a painted shadow)"
    assert len([item for item in sorter.statics if item.platform_index == 1]) == 8
    blocks = moving_blocks(rest, rest.at(60))
    assert len(blocks) == 4 and all(block.block for block in blocks)
    assert [block.item_id for block in blocks] == [PLATFORM_ITEM_BASE + n for n in range(4)]
    first = blocks[0]
    assert (first.x, first.y) == pytest.approx((5.5, 4.0)) and first.z == 2.25
    assert first.rect.right - first.rect.left == 32 and first.rect.top - first.rect.bottom == 20
    assert first.rect.left == int(first.rect.left), "drawn on whole pixels"
    assert moving_blocks(rest, rest)[0].x == 4.0
    order = [entry.index for entry in sorter.draw_order(blocks) if not entry.is_static]
    assert order == sorted(order), "its cells are drawn back to front"


def test_fighters_sort_against_a_moving_block_like_against_a_deck() -> None:
    block = DynamicItem(
        900, 0, 4.4, 4.2, 2.25, 0.25, sprite_rect(4.4, 4.2, 2.5, 16, 20, 0), block=True
    )

    def body(x: float, y: float, z: float) -> DynamicItem:
        return DynamicItem(8, 2, x, y, z, 2.5, sprite_rect(x, y, z, 10, 0, 40))

    assert dynamic_goes_first(block, body(4.9, 4.7, 2.5)), "standing on it: drawn after it"
    assert dynamic_goes_first(body(4.9, 4.7, -1.0), block), "wholly below it: drawn before"
    assert dynamic_goes_first(body(4.9, 4.7, 1.0), block), "behind it on both axes: hidden"
    assert dynamic_goes_first(block, body(5.6, 4.7, 1.0)), "past it on one axis: in front"
    assert not dynamic_goes_first(body(5.6, 4.7, 1.0), block)
    other = replace(block, item_id=901, x=5.4)
    assert dynamic_goes_first(block, other) and not dynamic_goes_first(other, block)
    sorter = DepthSorter(
        build(grid="\n".join(["0000000000"] * 4 + ["0000200000"] + ["0000000000"] * 5))
    )
    wall = next(item for item in sorter.statics if (item.cx, item.cy) == (4, 4))
    assert static_hides(wall, replace(block, x=3.6, y=3.8, z=1.0)), "a block behind a wall"
    assert not static_hides(wall, replace(block, x=4.6, y=3.8, z=1.0))
    assert not static_hides(wall, block), "above the wall's top"


# --- the stage report ----------------------------------------------------------------------


def test_the_stage_report_describes_and_checks_mechanics() -> None:
    plain = check_stage(build(), ROSTER)[-1]
    assert (plain.rule, plain.passed, plain.detail) == ("mechanics", True, "none: plain ground")
    stage = build(soft_platforms=[BRIDGE], hazards=[GEYSER])
    check = check_stage(stage, ROSTER)[-1]
    assert check.passed and "ping_pong every 240" in check.detail
    assert "geyser first active on frame 260" in check.detail
    hasty = check_stage(build(hazards=[GEYSER | {"warn": 20, "rest": 240}]), ROSTER)[-1]
    assert not hasty.passed and "warns for only 20 frames" in hasty.detail
    far = BRIDGE | {"motion": {"kind": "ping_pong", "to": [9.0, 0.0, 0.0], "period": 900}}
    edge = check_stage(build(soft_platforms=[far]), ROSTER)[-1]
    assert not edge.passed and "side blast zone" in edge.detail
    icy = build(
        "\n".join(["0000000000"] * 5 + ["0000i00000"] + ["0000000000"] * 4),
        {"i": {"height": 0, "traction": 0.3}},
    )
    assert check_stage(icy, ROSTER)[-1].detail == "ice"
    still = build(soft_platforms=[{"rect": [4, 4, 6, 6], "z": 2.5}])
    lifted = build(soft_platforms=[LIFT])
    assert screen_extent(lifted)[1] >= screen_extent(still)[1], "a trip counts toward the fit"
    assert screen_extent(build(soft_platforms=[far]))[0] > screen_extent(still)[0]


# --- the CPU -------------------------------------------------------------------------------


def test_cpus_play_a_whole_match_on_a_mechanic_stage() -> None:
    stage = build(
        soft_platforms=[BRIDGE, LIFT | {"rect": [1, 6, 3, 8]}], hazards=[GEYSER, BOLT, WIND]
    )
    rules = replace(ON, stocks=2, time_frames=3 * 3600)
    reports = [run_cpu_match(stage, ROSTER, [9, 7, 5, 3], 4, rules, 4 * 3600) for _ in range(2)]
    report = reports[0]
    assert report.ticks == reports[1].ticks and report.state_hash == reports[1].state_hash
    assert report.ended, "the match ended: nobody got stuck on a platform or in the wind"
    assert report.knockouts >= 3
    assert report.self_destructs <= report.knockouts // 2 + 1, (
        f"{report.self_destructs} of {report.knockouts} KOs were self-destructs"
    )


def test_a_cpu_stands_on_a_moving_platform_without_thinking_it_is_falling() -> None:
    from isofightr.ai.controller import CpuController
    from isofightr.ai.terrain import over_ground, regions

    stage = build(soft_platforms=[BRIDGE])
    assert len(regions(stage)) == 1, "a moving platform is no place to plan a route to"
    match = start(stage)
    rider, rival = match.fighters
    place(match, rider, 5.0, 5.0)
    place(match, rival, 8.5, 8.5)
    cpu = CpuController(0, 9, 3, stage)
    for _ in range(100):
        match.tick([cpu.think(match), hold(frames=1)[0]])
    cpu.think(match)
    assert cpu.live is match.stage and cpu.stage is stage
    deck = match.stage.soft_platforms[0]
    assert deck.x0 > 5.5, "the platform is well away from where it rests"
    assert rider.grounded and over_ground(cpu.live, rider.pos), "it knows it stands on something"


# --- recovery on every stage ---------------------------------------------------------------


def toward(normal_x: float, normal_y: float) -> Dir8:
    """The stick direction that heads back in across a ledge with this outward normal."""
    return max(Dir8, key=lambda way: -(way.world.x * normal_x + way.world.y * normal_y))


@pytest.mark.parametrize("stage_id", list_stage_ids())
def test_everyone_recovers_on_every_stage_with_its_mechanics_on(stage_id: str) -> None:
    """Knocked 3 units out past a ledge and 1 below it, every character gets back with an
    air jump and its up special, at each ledge of every stage, with the stage's mechanics
    on and at several moments of its moving platforms' trips (decision D-063)."""
    stage = load_stage(stage_id)
    periods = [p.motion.period for p in stage.soft_platforms if p.motion is not None]
    starts = [0] if not periods else [0, *(max(periods) * part // 4 for part in (1, 2, 3))]
    # ...and with every hazard going off as the fighter starts back (a wind against it).
    starts += [hazard.first_active() for hazard in stage.hazards]
    tested = 0
    for character in ROSTER:
        for ledge in stage.ledges:
            middle = (ledge.start + ledge.end) * 0.5
            way = toward(ledge.normal.x, ledge.normal.y)
            # Only where "3 units out" is open air: across a narrow gap it is the next island.
            if any(
                stage.cell_at(middle.x + ledge.normal.x * out, middle.y + ledge.normal.y * out)
                for out in (0.5, 1.5, 2.5, 3.0)
            ):
                continue
            tested += 1
            for first in starts:
                match = Match.create(stage, [character, character], seed=1, rules=ON)
                fighter, rival = match.fighters
                match.frame = first
                place(match, rival, stage.respawn.x, stage.respawn.y)
                out = middle + ledge.normal * 3.0
                place(match, fighter, out.x, out.y, z=ledge.z - 1.0, facing=way)
                aim = middle - ledge.normal * 0.5

                def steer(buttons: int = 0, vertical: int = 0) -> list[InputFrame]:
                    """One frame of stick toward the ledge from where the fighter is now: a
                    gust that blows it sideways is steered against, as a player would."""
                    gap = aim - fighter.pos.xy  # noqa: B023 (used at once, in this loop turn)
                    return hold(toward(-gap.x, -gap.y), buttons, frames=1, vertical=vertical)

                run(match, steer(Button.JUMP))
                for _ in range(12):
                    run(match, steer())
                run(match, steer(Button.SPECIAL, VERTICAL_UP))
                for _ in range(10):
                    run(match, steer(vertical=VERTICAL_UP))
                back = False
                for _ in range(150):
                    # Back means on the ground, on the ledge, or above the stage's ground
                    # (where it goes from there is piloting: on a tip one cell wide, a
                    # strong recovery held all the way carries clean over).
                    top = match.stage.surface_top(fighter.pos.x, fighter.pos.y)
                    above = top is not None and fighter.pos.z >= top
                    if fighter.state is StateId.LEDGE_HANG or fighter.grounded or above:
                        back = True
                        break
                    run(match, steer())
                assert back, f"{character.id} fell at {stage_id} ledge {middle} from frame {first}"
    assert tested >= 4 * len(ROSTER), "every side of the stage was tried"


def test_wait_helper_and_rules_are_what_the_other_tests_assume() -> None:
    match = start(build(), MatchRules(stocks=None))
    wait(match, 3)
    assert match.frame == 3 and not match.rules.stage_hazards


# --- the shadows of moving platforms -------------------------------------------------------


def test_a_moving_platform_shades_only_the_ground_under_it() -> None:
    from isofightr.render.ground_items import PLATFORM_SHADOW_BASE, platform_shadows
    from isofightr.render.placeholder_art import build_moving_shadow
    from isofightr.render.props import GROUND_PROP_BASE

    rest = load_stage("frostpeak")
    assert len(platform_shadows(rest, rest)) == 2, "at rest too: the rule off changes nothing"
    still = load_stage("sky_ruins")
    assert platform_shadows(still, still) == [], "platforms that never move have theirs painted"

    for frame in (0, 120, 240, 400):
        live = rest.at(frame)
        shadows = platform_shadows(rest, live)
        ids = [item.item_id for item in shadows]
        assert len(set(ids)) == len(ids)
        assert all(GROUND_PROP_BASE + 40 < item_id < 1 << 20 for item_id in ids)
        assert min(ids) >= PLATFORM_SHADOW_BASE
        for item in shadows:
            assert item.surface == 0.0, "the floes pass over the snow, never over the ledge"
            platform = live.soft_platforms[(item.item_id - PLATFORM_SHADOW_BASE) // 4]
            assert (item.x, item.y) == (platform.x0 + 1.0, platform.y0 + 1.0), "under its middle"
    # After half its trip the far floe is right out over the gap and casts nothing; the
    # near one, half a trip behind, is back over the main island.
    (out,) = platform_shadows(rest, rest.at(240))
    assert out.item_id == PLATFORM_SHADOW_BASE + 4 and out.x == 8.0

    # Lily Pads' leaves hang mostly over the gap: each shades the corner of the centre pad.
    pads = load_stage("lily_pads")
    assert [item.surface for item in platform_shadows(pads, pads)] == [0.0, 0.0]
    assert all(item.on_ground for item in platform_shadows(pads, pads))

    picture = build_moving_shadow(3, 2)
    assert picture.size == (80, 40)
    assert picture.getpixel((40, 20))[3] > 0 and picture.getpixel((0, 0))[3] == 0
    assert picture.getpixel((32, 1))[3] > 0, "the far corner is two cells in from the left"
