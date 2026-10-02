"""Unit tests for the M1 debug sandbox and the pixel font (pure parts, no window)."""

import math

import pytest

from isofightr.config import SANDBOX_MOVE_SPEED, SANDBOX_PLAYER_COUNT, SANDBOX_RISE_SPEED
from isofightr.data.stage_loader import load_stage
from isofightr.render.iso import project
from isofightr.scenes.sandbox import Sandbox
from isofightr.sim.input_frame import Dir8
from isofightr.ui.pixel_font import (
    GLYPH_ADVANCE,
    GLYPH_HEIGHT,
    GLYPH_WIDTH,
    PRINTABLE,
    build_glyph,
    text_width,
)


@pytest.fixture
def sandbox() -> Sandbox:
    return Sandbox.create(load_stage("training_grid"))


def test_placeholders_start_on_their_spawn_points(sandbox: Sandbox) -> None:
    assert len(sandbox.entities) == SANDBOX_PLAYER_COUNT
    for index, entity in enumerate(sandbox.entities):
        assert entity.entity_id == entity.player_index == index
        assert entity.pos == sandbox.stage.spawn_point(index)


def test_placeholders_face_the_middle_of_the_stage(sandbox: Sandbox) -> None:
    # P1 spawns toward -x of the centre and P2 toward +x.
    assert sandbox.entities[0].facing is Dir8.SE
    assert sandbox.entities[1].facing is Dir8.NW


@pytest.mark.parametrize(
    ("stick", "facing"),
    [
        ((1.0, 0.0), Dir8.E),
        ((-1.0, 0.0), Dir8.W),
        ((0.0, 1.0), Dir8.N),
        ((0.0, -1.0), Dir8.S),
        ((1.0, 1.0), Dir8.NE),
        ((-1.0, -1.0), Dir8.SW),
    ],
)
def test_movement_is_screen_relative(
    sandbox: Sandbox, stick: tuple[float, float], facing: Dir8
) -> None:
    start = sandbox.controlled_entity.pos
    sandbox.step(stick[0], stick[1], 0.0)
    moved = sandbox.controlled_entity.pos - start
    screen_x, screen_y = project(moved.x, moved.y)
    assert math.copysign(1, screen_x) == math.copysign(1, stick[0]) or stick[0] == 0
    assert math.copysign(1, screen_y) == math.copysign(1, stick[1]) or stick[1] == 0
    assert sandbox.controlled_entity.facing is facing


def test_diagonal_input_is_not_faster(sandbox: Sandbox) -> None:
    start = sandbox.controlled_entity.pos
    sandbox.step(1.0, 1.0, 0.0)
    assert (sandbox.controlled_entity.pos - start).length() == pytest.approx(SANDBOX_MOVE_SPEED)


def test_rise_and_sink_change_only_height(sandbox: Sandbox) -> None:
    start = sandbox.controlled_entity.pos
    for _ in range(10):
        sandbox.step(0.0, 0.0, 1.0)
    risen = sandbox.controlled_entity.pos
    assert (risen.x, risen.y) == (start.x, start.y)
    assert risen.z == pytest.approx(start.z + 10 * SANDBOX_RISE_SPEED)
    sandbox.step(0.0, 0.0, -1.0)
    assert sandbox.controlled_entity.pos.z == pytest.approx(start.z + 9 * SANDBOX_RISE_SPEED)


def test_no_input_keeps_position_and_facing(sandbox: Sandbox) -> None:
    before = (sandbox.controlled_entity.pos, sandbox.controlled_entity.facing)
    sandbox.step(0.0, 0.0, 0.0)
    assert (sandbox.controlled_entity.pos, sandbox.controlled_entity.facing) == before


def test_there_is_no_physics_yet(sandbox: Sandbox) -> None:
    """The placeholder walks straight off the edge and keeps its height: M2 adds gravity."""
    for _ in range(200):
        sandbox.step(-1.0, 0.0, 0.0)
    pos = sandbox.controlled_entity.pos
    assert sandbox.stage.surface_top(pos.x, pos.y) is None
    assert pos.z == 0.0


def test_only_the_controlled_placeholder_moves_and_control_cycles(sandbox: Sandbox) -> None:
    other_start = sandbox.entities[1].pos
    sandbox.step(1.0, 0.0, 0.0)
    assert sandbox.entities[1].pos == other_start
    sandbox.cycle_control()
    assert sandbox.controlled_entity is sandbox.entities[1]
    sandbox.step(1.0, 0.0, 0.0)
    assert sandbox.entities[1].pos != other_start
    sandbox.cycle_control()
    assert sandbox.controlled_entity is sandbox.entities[0]


def test_reset_returns_everyone_to_spawn(sandbox: Sandbox) -> None:
    for _ in range(30):
        sandbox.step(1.0, 1.0, 1.0)
    sandbox.reset()
    assert sandbox.entities[0].pos == sandbox.stage.spawn_point(0)
    assert sandbox.entities[0].facing is Dir8.SE


# --- pixel font ---------------------------------------------------------------------------


def test_glyphs_are_even_sized_so_sprites_stay_pixel_aligned() -> None:
    glyph = build_glyph("A")
    assert glyph.size == (GLYPH_WIDTH, GLYPH_HEIGHT)
    assert GLYPH_WIDTH % 2 == 0 and GLYPH_HEIGHT % 2 == 0


def test_every_printable_glyph_draws_something() -> None:
    assert len(PRINTABLE) == 94
    for character in PRINTABLE:
        assert build_glyph(character).getbbox() is not None, character


def test_glyph_is_white_with_a_dark_drop_shadow() -> None:
    colors = {color for _, color in build_glyph("H").getcolors()}  # type: ignore[union-attr]
    assert colors == {(0, 0, 0, 0), (255, 255, 255, 255), (16, 16, 28, 255)}


def test_text_width_uses_the_fixed_advance() -> None:
    assert text_width("") == 0
    assert text_width("x=12") == 4 * GLYPH_ADVANCE
