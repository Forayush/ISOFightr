"""What the battle HUD remembers from tick to tick: rolling damage numbers, hit flashes,
damage popups, the KO feed, the KO banner, stocks breaking, and when a banner appeared.

Plan note "13 - Game Modes UI and Flow" ("Battle HUD", decision D-061 item 9). Presentation
only: it reads fighters and ``match.events`` once per sim tick and never touches the sim, so
it holds nothing the state hash needs. The layout and timings are in
:mod:`isofightr.ui.hud_layout`; :mod:`isofightr.ui.hud` and :mod:`isofightr.ui.hud_extras`
draw it.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from isofightr.sim.events import Event, HitEvent, KoEvent
from isofightr.sim.fighter import Fighter
from isofightr.sim.math3d import Vec3
from isofightr.ui import hud_layout as layout

MAX_POPUPS: Final[int] = 8
KO_BANNER_TICKS: Final[int] = 54
"""The KO sash slides in, holds and slides out over this many ticks."""
SHATTER_TICKS: Final[int] = 30
BANNER_POP_TICKS: Final[int] = 8


@dataclass(slots=True)
class Popup:
    """A rising "+12%" where a hit landed."""

    position: Vec3
    damage: float
    age: int = 0


@dataclass(slots=True)
class FeedLine:
    """One KO feed line: the text and whose colour its block is."""

    text: str
    victim: int
    age: int = 0


@dataclass(slots=True)
class Shatter:
    """A stock icon breaking: whose, which slot, and how long ago."""

    player: int
    slot: int
    age: int = 0


@dataclass(slots=True)
class HudState:
    """Everything the HUD animates, advanced once per sim tick by :meth:`step`."""

    names: Sequence[str] = ()
    """Each player's name as the feed shows it ("ROOK")."""
    shown: dict[int, float] = field(default_factory=dict)
    """The damage each card shows (rolling toward the real one)."""
    flash: dict[int, int] = field(default_factory=dict)
    """Ticks of white left on a card's number after a hit."""
    popups: list[Popup] = field(default_factory=list)
    feed: list[FeedLine] = field(default_factory=list)
    ko_banner: tuple[int, int] | None = None
    """``(player, age)`` of the KO sash on screen."""
    shatters: list[Shatter] = field(default_factory=list)
    stocks: dict[int, int | None] = field(default_factory=dict)
    banner: str = ""
    banner_since: int = 0
    tick: int = 0

    def step(self, fighters: Sequence[Fighter], events: Sequence[Event], over: bool) -> None:
        """Advance one sim tick: age everything and read this tick's events. ``over`` is
        whether the match just ended (no KO sash then: GAME! is showing)."""
        self.tick += 1
        for popup in self.popups:
            popup.age += 1
        self.popups = [popup for popup in self.popups if popup.age < layout.POPUP_TICKS]
        for line in self.feed:
            line.age += 1
        self.feed = [line for line in self.feed if line.age < layout.FEED_TICKS]
        for shatter in self.shatters:
            shatter.age += 1
        self.shatters = [shatter for shatter in self.shatters if shatter.age < SHATTER_TICKS]
        self.flash = {player: ticks - 1 for player, ticks in self.flash.items() if ticks > 1}
        if self.ko_banner is not None:
            player, age = self.ko_banner
            self.ko_banner = (player, age + 1) if age + 1 < KO_BANNER_TICKS else None

        for event in events:
            if isinstance(event, HitEvent):
                self.flash[event.target] = layout.HIT_FLASH_TICKS
                self.popups.append(Popup(event.position, event.damage))
            elif isinstance(event, KoEvent):
                self._knocked_out(event, over)
        self.popups = self.popups[-MAX_POPUPS:]

        for fighter in fighters:
            index = fighter.player_index
            before = self.stocks.get(index, fighter.stocks)
            if before is not None and fighter.stocks is not None and fighter.stocks < before:
                for slot in range(fighter.stocks, min(before, layout.MAX_STOCK_ICONS)):
                    self.shatters.append(Shatter(index, slot))
            self.stocks[index] = fighter.stocks

    def roll(self, fighters: Sequence[Fighter]) -> None:
        """Move every card's number one frame closer to the real percent. Called once a
        drawn frame, so it also catches up while the game is paused (training tools)."""
        for fighter in fighters:
            index = fighter.player_index
            target = fighter.damage if fighter.in_play else 0.0
            self.shown[index] = layout.roll(self.shown.get(index, target), target)

    def _knocked_out(self, event: KoEvent, over: bool) -> None:
        victim = self._name(event.player)
        killer = None if event.credited_to is None else self._name(event.credited_to)
        self.feed.append(FeedLine(layout.feed_text(victim, killer), event.player))
        self.feed = self.feed[-layout.FEED_LINES :]
        if not over:
            self.ko_banner = (event.player, 0)

    def _name(self, player: int) -> str:
        return self.names[player] if player < len(self.names) else f"P{player + 1}"

    def show_banner(self, text: str) -> None:
        """Note the banner text this tick; a new text starts its pop."""
        if text != self.banner:
            self.banner = text
            self.banner_since = self.tick

    def banner_age(self) -> int:
        """Ticks since the banner text last changed."""
        return self.tick - self.banner_since

    def shown_damage(self, player: int) -> float:
        """The percent a player's card shows now."""
        return self.shown.get(player, 0.0)
