"""How a player's card reacts to a hit, in two stages (decision D-068, group 4).

Plan note "13 - Game Modes UI and Flow" ("Battle HUD") and D-068 item 7. The card already
turns its number and frame white and lifts the number on a hit (M13); on top of that, with
hit effects on:

- **at contact** the victim's portrait flashes white (``PORTRAIT_FLASH_TICKS``) and its
  damage number jitters by a pixel for as long as the victim is frozen (the hit's hitlag), as
  if it were caught in the freeze too;
- **at the launch** the number punches: it jumps to a bigger size for a moment
  (``PUNCH_BIG_TICKS``, by the hit's tier: light hits keep their size) and shakes, harder
  and longer the heavier the hit (``PUNCH_PIXELS``, ``PUNCH_TICKS``); and for heavy and
  critical hits the card's frame takes the attacker's colour (``FRAME_FLASH_TICKS``; a
  critical one blinks between it and white), so the whole table sees who landed it.

The tier is the hit splash's (:mod:`isofightr.render.hit_splash`). "Reduce flashing" turns the
portrait and frame flashes off; the screen-shake setting scales the jitter and the shake (the
card draws it: :mod:`isofightr.ui.hud`). Presentation only, fed by
:class:`isofightr.render.effects.BattleEffects` from ``match.events``.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Final

PORTRAIT_FLASH_TICKS: Final[int] = 3
"""How long the victim's portrait shows white from the contact."""
JITTER_PIXELS: Final[int] = 1
"""How far the number jitters, either way, while the victim is frozen."""
PUNCH_TICKS: Final[tuple[int, ...]] = (4, 6, 8, 10)
"""How long the number shakes from the launch, by tier."""
PUNCH_PIXELS: Final[tuple[int, ...]] = (1, 1, 2, 3)
"""How hard it shakes at first, by tier (it fades out over ``PUNCH_TICKS``)."""
PUNCH_BIG_TICKS: Final[tuple[int, ...]] = (0, 2, 3, 4)
"""How long the number shows at the punch size from the launch, by tier."""
FRAME_FLASH_TICKS: Final[tuple[int, ...]] = (0, 0, 8, 12)
"""How long the card's frame shows the attacker's colour from the launch, by tier."""
FRAME_BLINK_TICKS: Final[int] = 2
"""A critical hit's frame blinks between the attacker's colour and white this often."""
CRITICAL: Final[int] = 3


@dataclass(slots=True)
class CardReaction:
    """What one card is doing about the hits its player took."""

    portrait: int = 0
    """Ticks of white left on the portrait."""
    frozen: int = 0
    """Ticks of the player's freeze left (the number jitters meanwhile)."""
    frozen_age: int = 0
    tier: int = 0
    """The tier of the last launch."""
    punch_age: int | None = None
    """Ticks since the last launch, while its punch or frame flash lasts."""
    attacker: int | None = None
    """Who landed the last launch (``None`` for a stage hazard)."""


@dataclass(slots=True)
class HudReactions:
    """Every card's reaction, advanced once a sim tick (before the tick's events)."""

    cards: dict[int, CardReaction] = field(default_factory=dict)

    def contact(self, target: int, hitlag: int) -> None:
        """A hit landed on ``target`` and froze it for ``hitlag`` ticks."""
        card = self.cards.setdefault(target, CardReaction())
        card.portrait = PORTRAIT_FLASH_TICKS
        card.frozen = max(card.frozen, hitlag)
        card.frozen_age = 0

    def launch(self, target: int, tier: int, attacker: int | None) -> None:
        """``target``'s freeze ended in a launch of ``tier``, landed by ``attacker``."""
        card = self.cards.setdefault(target, CardReaction())
        card.frozen = 0
        card.tier = min(max(tier, 0), CRITICAL)
        card.punch_age = 0
        card.attacker = attacker

    def tick(self) -> None:
        """Advance every card by one sim tick."""
        for card in self.cards.values():
            card.portrait = max(0, card.portrait - 1)
            if card.frozen:
                card.frozen -= 1
                card.frozen_age += 1
            if card.punch_age is not None:
                card.punch_age += 1
                last = max(PUNCH_TICKS[card.tier], FRAME_FLASH_TICKS[card.tier])
                if card.punch_age >= last:
                    card.punch_age = None

    def clear(self) -> None:
        """Forget every reaction (a match restart)."""
        self.cards = {}

    def portrait_flash(self, player: int) -> bool:
        """Whether ``player``'s portrait shows white now."""
        card = self.cards.get(player)
        return card is not None and card.portrait > 0

    def punched(self, player: int) -> bool:
        """Whether ``player``'s number shows at the punch size now."""
        card = self.cards.get(player)
        if card is None or card.punch_age is None:
            return False
        return card.punch_age < PUNCH_BIG_TICKS[card.tier]

    def offset(self, player: int, strength: float = 1.0) -> tuple[int, int]:
        """How far ``player``'s number is moved now, in pixels: the freeze's jitter or the
        launch's shake, scaled by the screen-shake setting ``strength`` (0 to 1)."""
        card = self.cards.get(player)
        if card is None or strength <= 0.0:
            return (0, 0)
        if card.frozen:
            side = JITTER_PIXELS if card.frozen_age % 2 == 0 else -JITTER_PIXELS
            return (side, 0)
        if card.punch_age is None or card.punch_age >= PUNCH_TICKS[card.tier]:
            return (0, 0)
        left = PUNCH_TICKS[card.tier] - card.punch_age
        size = math.ceil(PUNCH_PIXELS[card.tier] * strength * left / PUNCH_TICKS[card.tier])
        across = size if card.punch_age % 2 == 0 else -size
        up = size if (card.punch_age // 2) % 2 == 0 else -size
        return (across, up)

    def frame_attacker(self, player: int) -> int | None:
        """Whose colour ``player``'s card frame shows now (``None``: its own look). A
        critical hit's frame blinks: on its other ticks this is ``None`` and the card shows
        its white frame (see :meth:`frame_white`)."""
        card = self.cards.get(player)
        if card is None or card.punch_age is None or card.attacker is None:
            return None
        if card.punch_age >= FRAME_FLASH_TICKS[card.tier]:
            return None
        if card.tier == CRITICAL and (card.punch_age // FRAME_BLINK_TICKS) % 2:
            return None
        return card.attacker

    def frame_white(self, player: int) -> bool:
        """Whether a critical hit's blinking frame is on its white half now."""
        card = self.cards.get(player)
        if card is None or card.punch_age is None or card.attacker is None:
            return False
        flashing = card.punch_age < FRAME_FLASH_TICKS[card.tier]
        return flashing and card.tier == CRITICAL and self.frame_attacker(player) is None
