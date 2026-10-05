"""Tests for projectile art and ground items (plan note 09, decision D-060)."""

import pytest

from isofightr.art.palettes import load_master
from isofightr.data.character_loader import load_character
from isofightr.data.stage_loader import load_stage
from isofightr.render import projectile_art as pa
from isofightr.render.ground_items import (
    DECAL_RANK,
    SHADOW_RANK,
    ProjectileLooks,
    projectile_items,
)
from isofightr.render.placeholder_art import SHADOW_HEIGHT, SHADOW_WIDTH
from isofightr.sim.input_frame import Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.states.interrupts import start_move

MASTER = load_master("resurrect64")
STYLES = (pa.CRESCENT, pa.BOULDER, pa.DART, pa.EMBER, pa.LAMP, pa.GLYPH)
CHARACTERS = ("rook", "bramble", "zephyr", "mote")


def _colours(image: object) -> set[tuple[int, int, int]]:
    return {pixel[:3] for pixel in image.getdata() if pixel[3]}  # type: ignore[attr-defined]


def test_every_shipped_projectile_has_a_style() -> None:
    for character_id in CHARACTERS:
        for move_id, move in load_character(character_id).moves.items():
            if move.projectiles:
                assert pa.style_of(character_id, move_id) is not None, (character_id, move_id)
    assert pa.style_of("rook", "jab1") is None, "no style: the plain ball"


@pytest.mark.parametrize("style", STYLES, ids=lambda style: style.name)
def test_art_is_palette_locked_centred_and_animated(style: pa.Style) -> None:
    seen = set()
    for heading in range(pa.HEADINGS if style.headed else 1):
        for frame in range(style.frames):
            for step in range(3 if style.charged else 1):
                image = pa.build(style, heading, frame, step, 1)
                width = style.size + (step * pa.CHARGE_GROWTH if style.charged else 0)
                assert image.size == (width, style.height or width)
                assert image.width % 2 == 1 and image.height % 2 == 1, "odd, so it centres"
                assert _colours(image) <= MASTER
                assert image.getpixel((0, 0))[3] == 0, "transparent corners"
                seen.add(image.tobytes())
    assert len(seen) > 1, "it animates"


def test_pointed_styles_face_their_heading() -> None:
    for style in (pa.CRESCENT, pa.DART, pa.EMBER):
        right = pa.build(style, 0, 0, 0, 0)
        left = pa.build(style, 4, 0, 0, 0)
        assert right.tobytes() != left.tobytes()
    dart = pa.build_dart(0, 0, 0)
    white = [
        x
        for x in range(dart.width)
        for y in range(dart.height)
        if dart.getpixel((x, y)) == pa.WHITE
    ]
    assert min(white) > dart.width // 2, "the tip is on the heading's side"


def test_heading_charge_and_frame_helpers() -> None:
    assert pa.heading_of(Vec3(0.0, 0.0, 0.0)) == 0
    assert pa.heading_of(Vec3(0.0, 0.0, 1.0)) == 2, "straight up on screen"
    assert pa.heading_of(Vec3(1.0, -1.0, 0.0)) == 0, "world (1, -1) is screen right"
    assert pa.heading_of(Vec3(-1.0, 1.0, 0.0)) == 4
    assert [pa.charge_step(d, 10.0) for d in (10.0, 11.4, 11.5, 14.9, 15.0, 30.0)] == [
        0, 0, 1, 1, 2, 2
    ]  # fmt: skip
    assert pa.charge_step(5.0, 0.0) == 0
    assert [pa.frame_of(pa.BOULDER, age) for age in (0, 3, 4, 15, 16)] == [0, 0, 1, 3, 0]
    assert [pa.shadow_step(h) for h in (0.0, 1.0, 1.1, 2.6)] == [0, 0, 1, 2]


def test_projectile_shadows_share_the_fighter_shadow_canvas() -> None:
    sizes = []
    for step in range(3):
        shadow = pa.build_shadow(step)
        assert shadow.size == (SHADOW_WIDTH, SHADOW_HEIGHT)
        assert _colours(shadow) <= MASTER
        sizes.append(sum(1 for pixel in shadow.getdata() if pixel[3]))
    assert sizes[0] > sizes[1] > sizes[2], "smaller the higher the projectile flies"


def fired(character_id: str, move_id: str, ticks: int) -> tuple[Match, ProjectileLooks]:
    stage = load_stage("training_grid")
    characters = [load_character(character_id), load_character("rook")]
    match = Match.create(stage, characters, rules=MatchRules(stocks=None))
    attacker, target = match.fighters
    attacker.pos, attacker.facing = Vec3(4.0, 6.0, 0.0), Dir8.SE
    target.pos = Vec3(10.5, 9.5, 0.0)
    start_move(match, attacker, move_id)
    for _ in range(ticks):
        match.tick([type(attacker.buffer.frame)()] * 2)
    looks = ProjectileLooks()
    looks.learn(characters)
    return match, looks


def test_a_flying_projectile_gets_a_shadow_on_the_surface_below() -> None:
    match, looks = fired("bramble", "nspecial", 30)
    [boulder] = match.projectiles
    assert looks.style(boulder) is pa.BOULDER
    [item] = projectile_items(match.stage, match.projectiles, looks, {0: 0})
    assert (item.x, item.y, item.surface) == (boulder.pos.x, boulder.pos.y, 0.0)
    assert item.rank == SHADOW_RANK and item.key[0] == "projectile_shadow"
    assert item.build().size == (SHADOW_WIDTH, SHADOW_HEIGHT)

    boulder.pos = Vec3(-3.0, 6.0, 2.0)  # over the void: nothing to cast a shadow on
    assert projectile_items(match.stage, match.projectiles, looks, {0: 0}) == []


def test_the_snare_glyph_is_a_ground_decal_not_a_shadow() -> None:
    match, looks = fired("mote", "dspecial", 50)
    [glyph] = match.projectiles
    assert looks.style(glyph) is pa.GLYPH and pa.GLYPH.decal
    [item] = projectile_items(match.stage, match.projectiles, looks, {0: 2})
    assert item.rank == DECAL_RANK < SHADOW_RANK, "a shadow lies on the decal, not under it"
    assert item.key[:2] == ("decal", "glyph") and item.key[-1] == 2, "in its owner's colour"
    assert item.build().size == (pa.GLYPH.size, pa.GLYPH.height)


def test_a_reflected_projectile_keeps_its_style() -> None:
    match, looks = fired("rook", "nspecial", 20)
    [wave] = match.projectiles
    wave.owner = 1  # reflected: it now belongs to the other player
    assert looks.style(wave) is pa.CRESCENT
    assert looks.style(wave) is not None
