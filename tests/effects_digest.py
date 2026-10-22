"""Digests of what the battle's hit feedback shows, tick by tick, for the "Off is today" tests
(decision D-068, M17: with hit effects Off the game must show exactly the effects it showed
before the hit splash existed).

The scenarios are recorded in ``tests/fixtures/``: a long match of random play with every
character (the roster golden's setup: 90% start, parry and helpless air dodges on) and a hit
storm (Rook and Mote swing at Bramble and Zephyr every ``STORM_CYCLE`` ticks: jabs, tilts,
smashes of every element, a multi-hit aerial, projectiles, and rounds where the targets hold
their shields or parry). Digests are hashed per tick and kept per window of ``WINDOW`` ticks,
so a failure points at the ticks where the effects first differ.
"""

import hashlib
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from helpers import place
from isofightr.ai.random_inputs import random_inputs
from isofightr.data.character_loader import load_character
from isofightr.data.sprite_sheet import load_sprite_set
from isofightr.data.stage_loader import load_stage
from isofightr.render.effects import BattleEffects
from isofightr.render.ground_items import ProjectileLooks
from isofightr.render.hurt_motion import hurt_choice
from isofightr.sim.input_frame import NEUTRAL_INPUT, Button, Dir8, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2
from isofightr.sim.states.interrupts import start_move
from isofightr.ui.hud_state import HudState

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = 20
"""Ticks hashed together into one entry of a fixture."""
ROSTER = ("bramble", "zephyr", "mote", "rook")
RANDOM_SEED = 3
RANDOM_INPUT_SEED = 277
RANDOM_TICKS = 2400
RULES = MatchRules(stocks=None, parry=True, air_dodge_helpless=True, start_damage=90.0)
STORM_ROSTER = ("rook", "bramble", "mote", "zephyr")
"""Players 1 and 3 (Rook, Mote) attack; 2 and 4 (Bramble, Zephyr) are hit."""
STORM_CYCLE = 24
STORM_GAP = 0.9
STORM_SECOND_PAIR = Vec2(-1.2, -1.2)
STORM_ROUNDS: tuple[tuple[str, float, str], ...] = (
    ("jab1", 0.0, ""),
    ("ftilt", 40.0, ""),
    ("fsmash", 100.0, ""),
    ("dtilt", 20.0, "shield"),
    ("nair", 30.0, ""),
    ("fsmash", 60.0, "parry"),
    ("jab1", 10.0, ""),
    ("dsmash", 80.0, ""),
    ("nspecial", 50.0, ""),
    ("fsmash", 150.0, ""),
    ("utilt", 20.0, ""),
    ("usmash", 120.0, "shield"),
    ("jab1", 90.0, ""),
)
"""Each round's move, the percent everyone is set to, and what the targets do. A parried
attacker is frozen into the next round, which it sits out."""
STORM_TICKS = STORM_CYCLE * len(STORM_ROUNDS) * 2
PARRY_LEAD = 3
"""A parrying target lets go of shield this many ticks before its attacker's first active
frame (counted from the round's first tick), so the hit lands in the parry window."""
SHIELD = InputFrame(held=int(Button.SHIELD))
PARTS = ("effects", "hurt", "hud")


@dataclass(frozen=True, slots=True)
class Scenario:
    """A match to digest: its setup, its input, and whether the hit storm stages it."""

    name: str
    stage: str
    characters: tuple[str, ...]
    seed: int
    rules: MatchRules
    inputs: list[list[InputFrame]]
    storm: bool

    def match(self) -> Match:
        """A fresh match of this scenario."""
        characters = [load_character(name) for name in self.characters]
        return Match.create(load_stage(self.stage), characters, seed=self.seed, rules=self.rules)


def plain(value: Any) -> Any:
    """Return ``value`` as plain, comparable data: floats rounded, enums by value,
    dataclasses as tuples of their fields, dictionaries sorted."""
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 4) + 0.0
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return tuple(plain(getattr(value, field.name)) for field in fields(value))
    if isinstance(value, dict):
        return tuple(sorted((plain(key), plain(item)) for key, item in value.items()))
    if isinstance(value, set | frozenset):
        return tuple(sorted(plain(item) for item in value))
    if isinstance(value, list | tuple):
        return tuple(plain(item) for item in value)
    raise TypeError(f"cannot digest {type(value).__name__}")


def effects_part(effects: BattleEffects, players: int) -> Any:
    """What the effect layer, the screen shake and the fighters' flashes show. Hit splashes
    (decision D-068) are added only when there are any, so a run without them digests exactly
    as before they existed."""
    shake = effects.shake
    splashes = effects.splashes.sprites()
    return plain(
        (
            effects.sparks,
            effects.fx,
            effects.streaks,
            effects.puffs,
            effects.trails,
            effects.rings,
            effects.blasts,
            effects.decals,
            (shake.amplitude, shake.frames, shake.age, shake.direction, shake.offset),
            effects.flash,
            effects.hit_hitlag,
            effects.combos,
            [effects.hud_offset(player) for player in range(players)],
            [effects.afterimages(player) for player in range(players)],
            *([splashes] if splashes else []),
        )
    )


def hurt_part(effects: BattleEffects, match: Match, anims: Sequence[Any]) -> Any:
    """The hit pose each fighter shows (decisions D-066, D-067)."""
    shown = []
    for fighter, sprites in zip(match.fighters, anims, strict=True):
        track = effects.hurt.track(fighter.player_index)
        choice = None if track is None else hurt_choice(fighter, track, sprites)
        shown.append((track, choice))
    return plain(shown)


def hud_part(hud: HudState) -> Any:
    """What the HUD animates: rolling numbers, flashes, popups, the feed, stocks."""
    return plain(
        (
            hud.shown,
            hud.flash,
            hud.popups,
            hud.feed,
            hud.ko_banner,
            hud.shatters,
            hud.stocks,
        )
    )


def storm_round(match: Match, tick: int) -> None:
    """Every ``STORM_CYCLE`` ticks, stand the four fighters in two facing pairs and have the
    first of each pair swing (fighters still frozen in a hit are left alone). Call before the
    tick is played."""
    if tick % STORM_CYCLE:
        return
    move_id, percent, _ = STORM_ROUNDS[(tick // STORM_CYCLE) % len(STORM_ROUNDS)]
    respawn = match.stage.respawn
    first = (respawn, respawn + Dir8.E.world * STORM_GAP)
    spots = (*first, *(spot + STORM_SECOND_PAIR for spot in first))
    for index, fighter in enumerate(match.fighters):
        if fighter.hitlag:
            continue
        attacker = index % 2 == 0
        spot = spots[index]
        ground = match.stage.surface_top(spot.x, spot.y)
        facing = Dir8.E if attacker else Dir8.W
        place(match, fighter, spot.x, spot.y, ground, facing, percent)
        fighter.hitstun = 0
        fighter.launch = None
        if attacker and move_id in fighter.character.moves:
            start_move(match, fighter, move_id)


def storm_inputs() -> list[list[InputFrame]]:
    """The hit storm's input: only the targets act, holding shield in a shield round and
    letting go of it just before the hit in a parry round."""
    characters = [load_character(name) for name in STORM_ROSTER]
    inputs = []
    for tick in range(STORM_TICKS):
        move_id, _, guard = STORM_ROUNDS[(tick // STORM_CYCLE) % len(STORM_ROUNDS)]
        into = tick % STORM_CYCLE
        frames = []
        for index in range(len(characters)):
            holding = False
            if index % 2 == 1 and guard:
                windows = characters[index - 1].moves[move_id].windows
                first = min(window.frames.first for window in windows)
                holding = guard == "shield" or into < first - PARRY_LEAD
            frames.append(SHIELD if holding else NEUTRAL_INPUT)
        inputs.append(frames)
    return inputs


def scenarios() -> Iterator[Scenario]:
    """Yield the scenarios the fixtures were recorded from."""
    yield Scenario(
        "random",
        "sky_ruins",
        ROSTER,
        RANDOM_SEED,
        RULES,
        random_inputs(RANDOM_INPUT_SEED, RANDOM_TICKS, len(ROSTER)),
        storm=False,
    )
    rules = MatchRules(stocks=None, parry=True)
    yield Scenario("storm", "sky_ruins", STORM_ROSTER, RANDOM_SEED, rules, storm_inputs(), True)


def run(effects_factory: Any = BattleEffects) -> dict[str, list[str]]:
    """Play every scenario, feeding the effects and the HUD as the battle does, and return
    each part's window hashes."""
    windows: dict[str, list[str]] = {part: [] for part in PARTS}
    for scenario in scenarios():
        match = scenario.match()
        effects = effects_factory()
        hud = HudState()
        looks = ProjectileLooks()
        looks.learn([fighter.character for fighter in match.fighters])
        anims = []
        for fighter in match.fighters:
            sprites = load_sprite_set(fighter.character.id)
            anims.append(sprites.anims if sprites is not None else {})
        running = {part: hashlib.sha1() for part in PARTS}
        players = len(match.fighters)
        for tick, frames in enumerate(scenario.inputs):
            if scenario.storm:
                storm_round(match, tick)
            match.tick(frames)
            effects.tick()
            effects.consume(match.events)
            hud.step(match.fighters, match.events, False)
            effects.observe(match.fighters, match.stage, match.frame)
            effects.observe_projectiles(match.projectiles, looks)
            hud.roll(match.fighters)
            digests = {
                "effects": effects_part(effects, players),
                "hurt": hurt_part(effects, match, anims),
                "hud": hud_part(hud),
            }
            for part, digest in digests.items():
                running[part].update(repr(digest).encode())
            if (tick + 1) % WINDOW == 0 or tick + 1 == len(scenario.inputs):
                for part in PARTS:
                    windows[part].append(running[part].hexdigest()[:12])
                    running[part] = hashlib.sha1()
    return windows


def load(name: str) -> dict[str, Any]:
    """Read a fixture."""
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def save(name: str, description: str, data: dict[str, Any]) -> None:
    """Write a fixture."""
    FIXTURES.mkdir(exist_ok=True)
    body = {"description": description, "window": WINDOW, **data}
    text = json.dumps(body, indent=1) + "\n"
    (FIXTURES / name).write_text(text, encoding="utf-8", newline="\n")


def first_difference(
    expected: Sequence[str], actual: Sequence[str], played: dict[str, int] | None = None
) -> str:
    """Describe where two lists of window hashes first differ. ``played`` is how many ticks
    of each scenario were played, if not all of them."""
    lengths = {scenario.name: len(scenario.inputs) for scenario in scenarios()}
    lengths.update(played or {})
    for index, (want, got) in enumerate(zip(expected, actual, strict=False)):
        if want != got:
            for name, ticks in lengths.items():
                count = -(-ticks // WINDOW)
                if index < count:
                    first = index * WINDOW
                    return f"{name}: ticks {first} to {first + WINDOW - 1} differ"
                index -= count
    return f"{len(expected)} windows were recorded, {len(actual)} were played"
