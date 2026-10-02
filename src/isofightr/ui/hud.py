"""The battle HUD: each player's damage percent along the bottom of the screen.

Plan note "13 - Game Modes UI and Flow" ("HUD (battle)": panels on the bottom row, colored by
player, damage % in a big pixel font with the color ramp from "09 - Art Direction", popping
when hit). Portraits, stock icons and names arrive with the full HUD in M6.

:func:`damage_color` and :func:`panel_lefts` are pure; :class:`DamageHud` draws.
"""

from collections.abc import Sequence
from typing import Final

import arcade

from isofightr.config import NATIVE_W
from isofightr.render.effects import BattleEffects
from isofightr.render.placeholder_art import player_color
from isofightr.sim.fighter import Fighter
from isofightr.ui.pixel_font import GLYPH_ADVANCE, GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

type Rgb = tuple[int, int, int]

DAMAGE_RAMP: Final[tuple[tuple[float, Rgb], ...]] = (
    (0.0, (255, 255, 255)),
    (60.0, (255, 232, 96)),
    (100.0, (255, 150, 48)),
    (150.0, (232, 56, 48)),
    (200.0, (150, 24, 40)),
)
"""Damage text color stops: white, yellow, orange, red, dark red (plan note 09)."""
DAMAGE_SCALE: Final[int] = 2
DAMAGE_CAPACITY: Final[int] = len("999%")
PANEL_WIDTH: Final[int] = DAMAGE_CAPACITY * GLYPH_ADVANCE * DAMAGE_SCALE
TAG_CAPACITY: Final[int] = len("P1 KO")
KO_TEXT: Final[str] = "--"


def damage_color(percent: float) -> Rgb:
    """Return the damage text color at ``percent``, blended between the ramp's stops."""
    previous_stop, previous_color = DAMAGE_RAMP[0]
    for stop, color in DAMAGE_RAMP[1:]:
        if percent < stop:
            blend = max(0.0, (percent - previous_stop) / (stop - previous_stop))
            mixed = [round(a + (b - a) * blend) for a, b in zip(previous_color, color, strict=True)]
            return (mixed[0], mixed[1], mixed[2])
        previous_stop, previous_color = stop, color
    return DAMAGE_RAMP[-1][1]


def damage_text(percent: float) -> str:
    """Return the HUD text for a damage value: whole percent, rounded down."""
    return f"{int(percent)}%"


def panel_lefts(player_count: int) -> list[int]:
    """Return the left edge of each player's panel, spread evenly across the screen."""
    return [
        round(NATIVE_W * (index + 1) / (player_count + 1) - PANEL_WIDTH / 2)
        for index in range(player_count)
    ]


class DamageHud:
    """One damage readout per player, drawn in native screen space."""

    def __init__(self, glyphs: GlyphAtlas, player_count: int, bottom: int) -> None:
        """Create the labels, with their bottom edge at ``bottom`` native pixels."""
        self.bottom = bottom
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._lefts = panel_lefts(player_count)
        self._damage: list[PixelLabel] = []
        self._colors: list[Rgb | None] = [None] * player_count
        self._offsets = [0] * player_count
        tag_bottom = bottom + GLYPH_HEIGHT * DAMAGE_SCALE
        for index, left in enumerate(self._lefts):
            red, green, blue, _ = player_color(index)
            tag = PixelLabel(
                glyphs, self.sprites, left, tag_bottom, TAG_CAPACITY, (red, green, blue)
            )
            tag.text = f"P{index + 1}"
            self._damage.append(
                PixelLabel(glyphs, self.sprites, left, bottom, DAMAGE_CAPACITY, scale=DAMAGE_SCALE)
            )

    def update(self, fighters: Sequence[Fighter], effects: BattleEffects) -> None:
        """Refresh the text, colors and hit pops from the current state."""
        for fighter in fighters:
            index = fighter.player_index
            label = self._damage[index]
            label.text = damage_text(fighter.damage) if fighter.in_play else KO_TEXT
            color = damage_color(fighter.damage)
            if color != self._colors[index]:
                self._colors[index] = color
                label.color = color
            offset = effects.hud_offset(index)
            if offset != self._offsets[index]:
                self._offsets[index] = offset
                label.move_to(self._lefts[index], self.bottom + offset)

    def draw(self) -> None:
        """Draw the HUD. Call inside ``pixel_buffer.drawing()`` without a world camera."""
        self.sprites.draw(pixelated=True)
