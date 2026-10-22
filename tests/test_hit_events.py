"""Tests for the hit events' new data (decision D-068, M17 group 1): where a hit lands (the
contact point), whether its hitbox is a sweetspot or a multi-hit sub-hit, the launch event
with the direction after DI, and the characters' hit themes. Event data only: the state hash,
the goldens and an old replay are unchanged.
"""

import math
from pathlib import Path

import pytest

from helpers import hold, place, run
from isofightr.config import HIT_THEMES
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.move_loader import mark_sweetspot
from isofightr.data.replay_io import load_replay, match_for
from isofightr.data.stage_loader import load_stage
from isofightr.sim.combat.constants import SWEETSPOT_SHARE
from isofightr.sim.combat.hitbox import hurtbox
from isofightr.sim.combat.knockback import launch_vector
from isofightr.sim.events import HitEvent, LaunchEvent
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Capsule, Vec3, closest_points, overlap_middle
from isofightr.sim.replay import play_back
from isofightr.sim.states.interrupts import start_move

FIXTURES = Path(__file__).parent / "fixtures"


def inside(point: Vec3, capsule: Capsule) -> bool:
    on_segment, _ = closest_points(capsule.start, capsule.end, point, point)
    return (point - on_segment).length() <= capsule.radius + 1e-9


# --- the contact point ----------------------------------------------------------------------


def test_the_contact_is_the_middle_of_the_overlap_along_the_closest_line() -> None:
    body = Capsule(Vec3(0.0, 0.0, 0.5), Vec3(0.0, 0.0, 2.0), 0.5)
    touching = Capsule(Vec3(1.0, 0.0, 1.0), Vec3(1.0, 0.0, 1.0), 0.7)
    point = overlap_middle(touching, body)
    # The hitbox reaches x = 0.3, the body x = 0.5: the middle is x = 0.4, at the same height.
    assert point.x == pytest.approx(0.4) and point.y == 0.0 and point.z == pytest.approx(1.0)
    small = Capsule(Vec3(0.1, 0.0, 1.2), Vec3(0.1, 0.0, 1.2), 0.2)
    assert overlap_middle(small, body) == small.start, "a hitbox inside the body: its own point"
    huge = Capsule(Vec3(0.5, 0.0, 1.0), Vec3(0.5, 0.0, 1.0), 3.0)
    assert overlap_middle(huge, body) == Vec3(0.0, 0.0, 1.0), "the body inside the hitbox"
    level = Capsule(Vec3(0.0, 0.0, 1.0), Vec3(0.0, 0.0, 1.0), 0.3)
    assert overlap_middle(level, body) == level.start, "centres together"


def test_closest_points_agree_with_the_segment_distance() -> None:
    from isofightr.sim.math3d import segment_distance_squared

    pairs = [
        (Vec3(0, 0, 0), Vec3(1, 0, 0), Vec3(0.5, 1, 0), Vec3(0.5, 2, 0)),
        (Vec3(0, 0, 0), Vec3(0, 0, 0), Vec3(1, 1, 1), Vec3(1, 1, 1)),
        (Vec3(0, 0, 0), Vec3(2, 0, 0), Vec3(0, 1, 0), Vec3(2, 1, 0)),
        (Vec3(-1, 0, 0), Vec3(1, 0, 0), Vec3(0, -1, 1), Vec3(0, 1, 1)),
    ]
    for a0, a1, b0, b1 in pairs:
        on_a, on_b = closest_points(a0, a1, b0, b1)
        assert (on_a - on_b).length_squared() == segment_distance_squared(a0, a1, b0, b1)


def first_hit(attacker: str, move: str, percent: float = 0.0, gap: float = 0.9) -> HitEvent:
    match = Match.create(
        load_stage("training_grid"),
        [load_character(attacker), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, target = match.fighters
    place(match, striker, 5.0, 6.0, facing=Dir8.E)
    east = Dir8.E.world * gap
    place(match, target, 5.0 + east.x, 6.0 + east.y, facing=Dir8.W, damage=percent)
    start_move(match, striker, move)
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        hits = [e for e in match.events if isinstance(e, HitEvent) and e.target == 1]
        if hits:
            assert hits[0].contact is not None
            assert inside(hits[0].contact, hurtbox(target)), f"{attacker} {move}: on the target"
            return hits[0]
    raise AssertionError(f"{attacker}'s {move} never hit")


@pytest.mark.parametrize(
    ("attacker", "move"),
    [
        ("rook", "jab1"),  # a small hitbox
        ("bramble", "dspecial"),  # the biggest: its centre is 18 px from the overlap
        ("zephyr", "dair"),  # a hitbox that sweeps
        ("mote", "fsmash"),  # the lantern, out past the target
        ("rook", "fsmash"),
    ],
)
def test_a_hit_lands_where_hitbox_and_hurtbox_overlap(attacker: str, move: str) -> None:
    """``first_hit`` checks the contact is on the target's hurtbox; the old position stays."""
    event = first_hit(attacker, move)
    assert event.contact is not None and event.position is not None


def test_the_contact_is_on_the_target_where_the_hitbox_centre_is_not() -> None:
    event = first_hit("bramble", "utilt")
    assert event.contact is not None
    assert (event.contact - event.position).length() > 0.5, "the centre is far off the body"


def test_a_projectile_hit_has_a_contact_too() -> None:
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, target = match.fighters
    place(match, striker, 3.0, 6.0, facing=Dir8.E)
    east = Dir8.E.world * 3.0
    place(match, target, 3.0 + east.x, 6.0 + east.y, facing=Dir8.W)
    start_move(match, striker, "nspecial")
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        hits = [e for e in match.events if isinstance(e, HitEvent)]
        if hits:
            assert hits[0].contact is not None and inside(hits[0].contact, hurtbox(target))
            return
    raise AssertionError("the crescent never hit")


# --- sweetspots and multi-hits ----------------------------------------------------------------


def test_rooks_forward_smash_tip_is_its_sweetspot() -> None:
    [window] = load_character("rook").moves["fsmash"].windows
    assert [(box.id, box.damage, box.sweet) for box in window.hitboxes] == [
        (0, 16.0, True),
        (1, 13.0, False),
    ]
    assert first_hit("rook", "fsmash").sweet
    assert not first_hit("rook", "fsmash", gap=0.0).sweet, "right up close: the sour spot"


def test_a_sweetspot_needs_the_others_ten_percent_weaker() -> None:
    from dataclasses import replace

    [window] = load_character("rook").moves["fsmash"].windows
    tip, near = window.hitboxes
    plain = tuple(replace(box, sweet=False) for box in window.hitboxes)
    just = (replace(tip, damage=10.0, sweet=False), replace(near, damage=10.0 * SWEETSPOT_SHARE))
    assert [box.sweet for box in mark_sweetspot(just)] == [True, False]
    close = (replace(tip, damage=10.0, sweet=False), replace(near, damage=9.5))
    assert [box.sweet for box in mark_sweetspot(close)] == [False, False]
    assert [box.sweet for box in mark_sweetspot(plain[:1])] == [False], "one hitbox: none"
    even = load_character("rook").moves["dtilt"].windows[0].hitboxes
    assert not any(box.sweet for box in even), "equal damage: none"


def test_multi_hits_rehit_or_have_their_hitlag_cut() -> None:
    zephyr, mote, rook = (load_character(name) for name in ("zephyr", "mote", "rook"))
    assert all(p.hitbox.multi for p in zephyr.moves["nspecial"].projectiles), "the darts"
    assert mote.moves["nair"].windows[0].hitboxes[0].multi, "it rehits"
    assert not mote.moves["nair"].windows[1].hitboxes[0].multi, "the finisher"
    assert not any(box.multi for box in rook.moves["fsmash"].windows[0].hitboxes)
    assert first_hit("zephyr", "fair").multi


# --- the launch ---------------------------------------------------------------------------


def launch_of(stick: Dir8 | None, percent: float = 100.0) -> tuple[LaunchEvent, Vec3, int]:
    """Rook forward-smashes Rook; return the launch event, the target's knockback velocity
    on that tick, and how many ticks after the hit it came."""
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, target = match.fighters
    place(match, striker, 5.0, 6.0, facing=Dir8.E)
    east = Dir8.E.world * 0.9
    place(match, target, 5.0 + east.x, 6.0 + east.y, facing=Dir8.W, damage=percent)
    held = NEUTRAL_INPUT if stick is None else InputFrame(move=stick.world)
    start_move(match, striker, "fsmash")
    hit_at = None
    for tick in range(120):
        match.tick(
            [NEUTRAL_INPUT, NEUTRAL_INPUT if hit_at is None else held]
        )  # DI: held in the freeze
        if hit_at is None and any(isinstance(e, HitEvent) for e in match.events):
            hit_at = tick
            assert target.launch is not None
            hitlag = target.hitlag
        launches = [e for e in match.events if isinstance(e, LaunchEvent)]
        if launches:
            assert hit_at is not None and tick - hit_at == hitlag, "the tick the freeze ends"
            return launches[0], target.kb_vel, tick - hit_at
    raise AssertionError("no launch")


def test_the_launch_event_points_where_the_target_flies_after_di() -> None:
    plain, velocity, _ = launch_of(None)
    assert plain.target == 1 and plain.knockback > 80.0
    assert (plain.direction - velocity.normalized()).length() < 1e-9
    assert abs(plain.direction.length() - 1.0) < 1e-9
    bent, velocity, _ = launch_of(Dir8.N)
    assert (bent.direction - velocity.normalized()).length() < 1e-9
    turned = math.degrees(math.acos(max(-1.0, min(1.0, bent.direction.dot(plain.direction)))))
    assert 1.0 < turned <= 20.0, "DI bends it, by at most 18 degrees and a little elevation"


def test_a_throw_launches_too() -> None:
    from helpers import make_match
    from isofightr.sim.input_frame import Button

    match = make_match(stocks=None)
    grabber, target = match.fighters
    place(match, grabber, 5.0, 6.0, facing=Dir8.E)
    east = Dir8.E.world * 0.8
    place(match, target, 5.0 + east.x, 6.0 + east.y, facing=Dir8.W, damage=50.0)
    seen = []
    frames = hold(buttons=Button.GRAB, frames=1) + [NEUTRAL_INPUT] * 12
    frames += [InputFrame(move=Dir8.E.world)] * 2 + [NEUTRAL_INPUT] * 60
    for frame in frames:
        run(match, [frame])
        seen += [e for e in match.events if isinstance(e, LaunchEvent)]
    assert seen and seen[0].target == 1


# --- hit themes -------------------------------------------------------------------------------


def test_every_character_has_a_hit_theme() -> None:
    themes = {name: load_character(name).hit_theme for name in list_character_ids()}
    assert themes == {"rook": "slash", "bramble": "earth", "zephyr": "wind", "mote": "fire"}
    assert set(themes.values()) <= set(HIT_THEMES)


def test_a_hit_theme_is_optional_and_checked() -> None:
    import tomllib

    from isofightr.data.character_loader import parse_character
    from isofightr.data.paths import CHARACTERS_DIR
    from isofightr.data.validation import DataError

    rook = load_character("rook")
    with (CHARACTERS_DIR / "rook" / "fighter.toml").open("rb") as file:
        data = tomllib.load(file)
    del data["hit_theme"]
    assert parse_character(data, moves=rook.moves, source="test").hit_theme == ""
    with pytest.raises(DataError, match="hit_theme"):
        parse_character({**data, "hit_theme": "plasma"}, moves=rook.moves, source="test")


# --- nothing in the sim changed -------------------------------------------------------------


def test_a_replay_recorded_before_the_new_events_still_verifies() -> None:
    """``replay_before_m17_events.json`` was recorded before M17 group 1 added the contact,
    sweetspot and multi-hit fields and the launch event: event data only, so it plays back
    to the same state (the goldens check the same)."""
    replay = load_replay(FIXTURES / "replay_before_m17_events.json")
    assert play_back(match_for(replay), replay)


def test_without_di_the_launch_goes_where_the_hit_said() -> None:
    """With nothing held the launch event's direction is the pending launch's own (the one
    the splash shows during the freeze)."""
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook"), load_character("rook")],
        rules=MatchRules(stocks=None),
    )
    striker, target = match.fighters
    place(match, striker, 5.0, 6.0, facing=Dir8.E)
    east = Dir8.E.world * 0.9
    place(match, target, 5.0 + east.x, 6.0 + east.y, facing=Dir8.W, damage=100.0)
    start_move(match, striker, "fsmash")
    pending = None
    for _ in range(120):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        pending = pending or target.launch
        launches = [e for e in match.events if isinstance(e, LaunchEvent)]
        if launches:
            assert pending is not None
            expected = launch_vector(pending.heading, pending.elevation)
            assert (launches[0].direction - expected).length() < 1e-9
            return
    raise AssertionError("no launch")
