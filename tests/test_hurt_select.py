"""Tests for choosing D-067's hit animations (M16 group 4d): ground flinches by hit height,
damage tier and side, air flinches, the reeling roll and the electric pose, with D-066's
animations as the fallback for a character without them. From the real sim, fed to the
effects as the battle feeds them."""

from dataclasses import dataclass, replace
from itertools import pairwise

import pytest

from helpers import make_match, place
from isofightr.data.character_loader import load_character
from isofightr.data.sprite_sheet import AnimInfo, load_sprite_set
from isofightr.data.stage_loader import load_stage
from isofightr.render.effects import BattleEffects
from isofightr.render.hurt_motion import (
    ELECTRIC_ANIM,
    FLY_ANIM,
    IMPACT_ANIM,
    MELEE_HIT_ANIMS,
    ROLL_ANIM,
    ROLL_BODY_ANGLE,
    ROLL_POSES,
    ROLL_TURN_DEGREES,
    TUMBLE_ANIM,
    TUMBLE_STEP_DEGREES,
    HurtChoice,
    HurtTrack,
    hurt_choice,
)
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.events import HitEvent
from isofightr.sim.fighter import GroundKind, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import ZERO3, Vec3
from isofightr.sim.move_def import Effect
from isofightr.sim.states.interrupts import start_move

ROOK = load_sprite_set("rook")
ROOK_ANIMS = ROOK.anims if ROOK is not None else {}
OLD_ANIMS: dict[str, AnimInfo] = {
    name: info for name, info in ROOK_ANIMS.items() if name not in MELEE_HIT_ANIMS
}
"""Rook's animations without D-067's: a character that has only D-066's."""


@dataclass(frozen=True, slots=True)
class Seen:
    """The victim on one tick from the hit on."""

    state: StateId
    hitlag: int
    hitstun: int
    grounded: bool
    choice: HurtChoice | None
    track: HurtTrack


def zapper() -> CharacterDef:
    """Rook whose forward smash is electric (no move in the game is; D-067 tests it so)."""
    rook = load_character("rook")
    fsmash = rook.moves["fsmash"]
    windows = tuple(
        replace(w, hitboxes=tuple(replace(h, effect=Effect.ELECTRIC) for h in w.hitboxes))
        for w in fsmash.windows
    )
    return replace(rook, moves={**rook.moves, "fsmash": replace(fsmash, windows=windows)})


def played(
    move: str,
    percent: float,
    lift: float | None = None,
    behind: bool = False,
    delay: int = 0,
    attacker: CharacterDef | None = None,
    anims: dict[str, AnimInfo] | None = None,
    ticks: int = 120,
) -> list[Seen]:
    """Rook (or ``attacker``) does ``move`` on Rook at ``percent`` on Training Grid, the victim
    held ``lift`` units up until the hit; what the victim shows each tick from the hit on."""
    characters = [attacker or load_character("rook"), load_character("rook")]
    match = Match.create(load_stage("training_grid"), characters, rules=MatchRules(stocks=None))
    striker, target = match.fighters
    place(match, striker, 4.0, 6.0, facing=Dir8.E)
    place(match, target, 5.0, 6.0, facing=Dir8.E if behind else Dir8.W, damage=percent)
    floor = target.pos.z
    effects = BattleEffects()
    for _ in range(delay):
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
    start_move(match, striker, move)
    seen: list[Seen] = []
    hit = False
    for _ in range(240 + ticks):
        if not hit and lift is not None:
            target.pos = Vec3(target.pos.x, target.pos.y, floor + lift)
            target.vel = ZERO3
            target.ground = GroundKind.NONE
        match.tick([NEUTRAL_INPUT, NEUTRAL_INPUT])
        effects.tick()
        effects.consume(match.events)
        effects.observe(match.fighters, match.stage, match.frame)
        hit = hit or any(isinstance(e, HitEvent) and e.target == 1 for e in match.events)
        if not hit:
            continue
        if len(seen) >= ticks or not target.in_play:
            break
        track = effects.hurt.track(1)
        assert track is not None
        choice = hurt_choice(target, track, ROOK_ANIMS if anims is None else anims)
        copy = HurtTrack(**{key: getattr(track, key) for key in HurtTrack.__slots__})
        seen.append(
            Seen(target.state, target.hitlag, target.hitstun, target.grounded, choice, copy)
        )
    assert hit, f"{move} never hit"
    return seen


def stunned(seen: list[Seen]) -> list[Seen]:
    return [
        s
        for s in seen
        if s.hitlag == 0 and s.hitstun > 0 and s.state in (StateId.FLINCH, StateId.TUMBLE)
    ]


def test_rook_has_every_d067_animation() -> None:
    assert all(name in ROOK_ANIMS for name in MELEE_HIT_ANIMS)


@pytest.mark.parametrize(
    ("move", "behind", "expected"),
    [
        ("utilt", False, "hurt_high_medium_front"),
        ("dtilt", False, "hurt_low_medium_front"),
        ("jab1", False, "hurt_mid_weak_front"),
        ("jab1", True, "hurt_mid_weak_back"),
        ("ftilt", True, "hurt_mid_medium_back"),
    ],
)
def test_a_ground_flinch_follows_the_hits_height_tier_and_side(
    move: str, behind: bool, expected: str
) -> None:
    """On the ground (an up or down tilt lifts its victim first, which then flies: D-067)."""
    seen = stunned(played(move, 0.0, behind=behind))
    flinching = [s for s in seen if s.state is StateId.FLINCH and s.grounded]
    assert flinching
    assert {s.choice.anim for s in flinching if s.choice} == {expected}
    assert all(s.choice and s.choice.direction is None for s in flinching), "in the facing"


def test_a_weak_hit_in_the_air_shows_the_air_flinch_until_it_lands() -> None:
    seen = stunned(played("jab1", 0.0, lift=0.6))
    air = [s for s in seen if not s.grounded]
    ground = [s for s in seen if s.grounded]
    assert air and {s.choice.anim for s in air if s.choice} == {"hurt_air_weak_front"}
    assert all(s.choice and s.choice.anim == "hurt_mid_weak_front" for s in ground)


def rolling_delay() -> tuple[int, int]:
    """Return a delay whose airborne 120% forward smash rolls, and one whose does not."""
    rolled = kept = None
    for delay in range(40):
        seen = played("fsmash", 120.0, lift=0.6, delay=delay, ticks=12)
        rolls = any(s.track.rolling for s in seen)
        rolled = delay if rolls and rolled is None else rolled
        kept = delay if not rolls and kept is None else kept
        if rolled is not None and kept is not None:
            return rolled, kept
    raise AssertionError("no hit frame both rolls and does not")


def test_the_reeling_roll_replaces_damage_fly_for_its_whole_hitstun() -> None:
    rolled, kept = rolling_delay()
    seen = played("fsmash", 120.0, lift=0.6, delay=rolled, ticks=200)
    stun = stunned(seen)
    assert stun and all(s.choice and s.choice.anim == ROLL_ANIM for s in stun)
    poses = [s.choice.pose for s in stun if s.choice]
    steps = [(b - a) % ROLL_POSES for a, b in pairwise(poses)]
    assert set(steps) <= {0, 1} and steps.count(1) >= len(steps) // 3, "a steady corkscrew"
    assert ROLL_TURN_DEGREES < 360.0 / ROLL_POSES, "never a pose skipped"
    assert all(s.choice and s.choice.direction is not None for s in stun), "by the travel"
    after = [s for s in seen if s.state is StateId.TUMBLE and s.hitstun == 0]
    if after:
        first = after[0].choice
        assert first is not None and first.anim == TUMBLE_ANIM
        gap = abs((first.pose * TUMBLE_STEP_DEGREES - ROLL_BODY_ANGLE + 180.0) % 360.0 - 180.0)
        assert gap <= TUMBLE_STEP_DEGREES
    other = stunned(played("fsmash", 120.0, lift=0.6, delay=kept))
    assert other and all(s.choice and s.choice.anim == FLY_ANIM for s in other)


def test_an_electric_hit_convulses_for_its_hitstun_at_any_knockback() -> None:
    for percent in (0.0, 60.0):
        seen = played("fsmash", percent, attacker=zapper(), ticks=200)
        assert seen[0].track.effect is Effect.ELECTRIC
        assert seen[0].choice is not None and seen[0].choice.anim == IMPACT_ANIM, "the freeze"
        stun = stunned(seen)
        assert stun and all(s.choice and s.choice.anim == ELECTRIC_ANIM for s in stun)
        assert {s.choice.pose for s in stun if s.choice} == {0, 1}, "two postures in turn"
        assert all(s.choice and s.choice.direction is None for s in stun), "in the facing"


def test_without_d067s_animations_a_character_falls_back_to_d066s() -> None:
    weak = stunned(played("jab1", 0.0, anims=OLD_ANIMS))
    assert weak and {s.choice.anim for s in weak if s.choice} == {"hurt_light_front"}
    air = stunned(played("jab1", 0.0, lift=0.6, anims=OLD_ANIMS))
    assert {s.choice.anim for s in air if s.choice} == {"hurt_light_front"}
    rolled, _ = rolling_delay()
    launched = stunned(played("fsmash", 120.0, lift=0.6, delay=rolled, anims=OLD_ANIMS))
    assert launched and all(s.choice and s.choice.anim == FLY_ANIM for s in launched)
    zapped = stunned(played("fsmash", 60.0, attacker=zapper(), anims=OLD_ANIMS))
    assert zapped and all(s.choice and s.choice.anim == FLY_ANIM for s in zapped)


def test_every_animation_the_selector_names_exists_for_rook() -> None:
    """Whatever the selector picks over a spread of hits is in Rook's sheets."""
    names = set()
    for move, percent, lift in (
        ("jab1", 0.0, None),
        ("jab1", 0.0, 0.6),
        ("utilt", 30.0, None),
        ("dtilt", 30.0, None),
        ("fsmash", 0.0, None),
        ("fsmash", 120.0, 0.6),
    ):
        names |= {s.choice.anim for s in played(move, percent, lift) if s.choice}
    assert names <= set(ROOK_ANIMS)
    assert {"hurt_air_weak_front", "hurt_high_medium_front", "hurt_low_medium_front"} <= names


def test_the_selection_never_changes_the_sim() -> None:
    match = make_match(stocks=None)
    before = match.state_hash()
    effects = BattleEffects()
    effects.consume(match.events)
    effects.observe(match.fighters, match.stage, match.frame)
    for fighter in match.fighters:
        hurt_choice(fighter, effects.hurt.track(fighter.player_index), ROOK_ANIMS)
    assert match.state_hash() == before


def test_a_flinch_after_a_short_flight_plays_from_the_landing() -> None:
    """An up tilt at 0% lifts its victim, which flies, then flinches on landing: the flinch
    plays from its first pose there (rock, then settle), not from where the hitstun is."""
    seen = stunned(played("utilt", 0.0))
    flew = [s for s in seen if s.choice and s.choice.anim == FLY_ANIM]
    landed = [s for s in seen if s.choice and s.choice.anim == "hurt_high_medium_front"]
    assert flew and landed and seen.index(landed[0]) > seen.index(flew[-1])
    assert [s.choice.pose for s in landed[:9] if s.choice] == [0, 0, 1, 1, 1, 2, 2, 2, 3]


def test_a_weak_launch_keeps_the_pose_of_its_launch() -> None:
    """D-067 refined: a launch under tumble strength is short and lands on its feet, so its
    damage-fly keeps the pose of the direction it was launched in (an up tilt's straight up,
    a forward smash at 0% up and forward), never turned flat at the top or diving down."""
    for move, pose in (("utilt", 0), ("fsmash", 1)):
        poses = {
            s.choice.pose
            for s in stunned(played(move, 0.0))
            if s.choice and s.choice.anim == FLY_ANIM
        }
        assert poses == {pose}, (move, poses)
