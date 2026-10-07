"""The Rules screen's model: its rows, what each does to a setup, and the saved rules.

Plan note "13 - Game Modes UI and Flow" ("Rules settings", decision D-061). A row has a
value to step through, an ON/OFF switch, or both (time limit and stock). The screen in
:mod:`isofightr.scenes.rules_view` only draws these rows and passes input on; everything a
row changes is decided here, so it is tested without a window. Only rules the game really
has are listed.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from typing import Final

from isofightr.scenes.setup import MatchSetup
from isofightr.settings import RULE_FLAGS, SavedRules


@dataclass(frozen=True, slots=True)
class RuleRow:
    """One row of the Rules screen."""

    key: str
    label: str
    icon: str
    has_value: bool = False
    """Whether left and right step a value."""
    has_switch: bool = True
    """Whether confirm flips an ON/OFF switch."""
    help: str = ""
    """One line saying what the rule does, shown under the list."""


RULE_ROWS: Final[tuple[RuleRow, ...]] = (
    RuleRow(
        "time",
        "TIME LIMIT",
        "clock",
        has_value=True,
        help="The match ends when the clock runs out. With stock off, best score wins.",
    ),
    RuleRow(
        "stock",
        "STOCK",
        "stock",
        has_value=True,
        help="Lives per fighter. The last one standing wins.",
    ),
    RuleRow(
        "launch_rate",
        "LAUNCH RATE",
        "burst",
        has_value=True,
        has_switch=False,
        help="Multiplies all knockback.",
    ),
    RuleRow(
        "start_damage",
        "STARTING DAMAGE",
        "percent",
        has_value=True,
        has_switch=False,
        help="Damage every fighter starts with, and comes back with.",
    ),
    RuleRow(
        "team_play",
        "TEAM BATTLE",
        "team",
        help="Play in teams. Pick your team on character select.",
    ),
    RuleRow(
        "friendly_fire",
        "TEAM ATTACK",
        "swords",
        help="Teammates can hit each other, for half damage.",
    ),
    RuleRow(
        "parry",
        "PARRY",
        "shield",
        help="Dropping shield just before a hit lands parries it.",
    ),
    RuleRow(
        "short_hop_macro",
        "JUMP + ATTACK = SHORT-HOP AERIAL",
        "hop",
        help="Jump and attack together give a short-hop aerial.",
    ),
    RuleRow(
        "air_dodge_helpless",
        "HELPLESS AFTER A DIRECTIONAL AIR DODGE",
        "fall",
        help="A directional air dodge leaves you falling helpless.",
    ),
    RuleRow(
        "hud_display",
        "HUD DISPLAY",
        "hud",
        help="Show damage, stocks and names. The clock always shows.",
    ),
    RuleRow(
        "score_display",
        "SCORE DISPLAY",
        "score",
        help="Show each player's score: KOs minus falls.",
    ),
    RuleRow(
        "player_tags",
        "PLAYER TAG DISPLAY",
        "tag",
        help="A name tag floats over each fighter.",
    ),
    RuleRow(
        "pausing",
        "PAUSING",
        "pause",
        help="Off: no pause. Backspace or Start + attack + special quits.",
    ),
)
"""The rows, top to bottom. The switch rows' keys are :class:`MatchSetup` fields."""
ROW_KEYS: Final[tuple[str, ...]] = tuple(row.key for row in RULE_ROWS)
_SWITCH_FIELDS: Final[frozenset[str]] = frozenset(RULE_FLAGS)


def row(key: str) -> RuleRow:
    """Return the row with this key."""
    return RULE_ROWS[ROW_KEYS.index(key)]


def row_value(setup: MatchSetup, key: str) -> str:
    """Return the value a row's stepper shows ("" for a row without one)."""
    if key == "time":
        return setup.time_label
    if key == "stock":
        return str(setup.stocks)
    if key == "launch_rate":
        return f"{setup.launch_rate:g}x" if setup.launch_rate % 1 else f"{setup.launch_rate:.1f}x"
    if key == "start_damage":
        return f"{setup.start_damage}%"
    return ""


def row_on(setup: MatchSetup, key: str) -> bool | None:
    """Return whether a row's switch is on (``None`` for a row without one)."""
    if key == "time":
        return setup.time_on
    if key == "stock":
        return setup.stock_on
    if key in _SWITCH_FIELDS:
        return bool(getattr(setup, key))
    return None


def step_row(setup: MatchSetup, key: str, step: int) -> MatchSetup:
    """Return the setup after stepping a row's value down (-1) or up (+1). A row without a
    value is left alone."""
    if key == "time":
        return setup.with_minutes(step)
    if key == "stock":
        return setup.with_stocks(step)
    if key == "launch_rate":
        return setup.with_launch_rate(step)
    if key == "start_damage":
        return setup.with_start_damage(step)
    return setup


def toggle_row(setup: MatchSetup, key: str) -> MatchSetup:
    """Return the setup after flipping a row's switch. Time limit and stock keep each other
    honest: switching the last one off switches the other on. A row without a switch steps
    its value forward instead, so confirm always does something."""
    if key == "time":
        return setup.with_time_on(not setup.time_on)
    if key == "stock":
        return setup.with_stock_on(not setup.stock_on)
    if key in _SWITCH_FIELDS:
        return replace(setup, **{key: not getattr(setup, key)})
    return step_row(setup, key, 1)


# --- the saved rules ---------------------------------------------------------------------

_SAVED_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in fields(SavedRules))


def to_saved(setup: MatchSetup) -> SavedRules:
    """Return the rules of a setup, as they are saved in the settings."""
    return SavedRules(**{name: getattr(setup, name) for name in _SAVED_FIELDS})


def with_saved(setup: MatchSetup, saved: SavedRules) -> MatchSetup:
    """Return a setup with its rules replaced by saved ones. Who plays whom, on which
    devices and teams, and where, is kept."""
    return replace(setup, **{name: getattr(saved, name) for name in _SAVED_FIELDS})


def with_default_rules(setup: MatchSetup) -> MatchSetup:
    """Return a setup with every rule back at its default (the DEFAULT button)."""
    return with_saved(setup, SavedRules())


def toggle_pool(setup: MatchSetup, stage: str, stages: Sequence[str]) -> MatchSetup:
    """Return the setup with one stage added to or taken out of the random pool. The last
    stage cannot be taken out. A pool holding every stage is stored empty ("all")."""
    pool = setup.pool(stages)
    if stage in pool:
        if len(pool) == 1:
            return setup
        pool.remove(stage)
    elif stage in stages:
        pool.append(stage)
    kept = tuple(each for each in stages if each in pool)
    return replace(setup, random_pool=() if len(kept) == len(stages) else kept)


def rule_chips(setup: MatchSetup) -> list[str]:
    """Return the rules in a few words, for the chips on character and stage select."""
    chips = []
    if setup.stock_on:
        chips.append(f"STOCK {setup.stocks}")
    if setup.time_on:
        chips.append(f"TIME {setup.time_label}")
    chips.append(row_value(setup, "launch_rate"))
    if setup.start_damage:
        chips.append(f"START {setup.start_damage}%")
    chips.append("TEAMS ON" if setup.team_play else "TEAMS OFF")
    return chips
