"""The battle HUD: each player's damage percent along the bottom of the screen.

Plan note "13 - Game Modes UI and Flow" ("HUD (battle)": panels on the bottom row, colored by
player, damage % in a big pixel font with the color ramp from "09 - Art Direction", popping
when hit). Portraits, stock icons and names arrive with the full HUD in M6.

Layout and colors are worked out in :mod:`isofightr.ui.hud_layout`; this module draws.
"""

from collections.abc import Sequence

import arcade

from isofightr.render.effects import BattleEffects
from isofightr.render.placeholder_art import player_color
from isofightr.sim.fighter import Fighter
from isofightr.ui.hud_layout import (
    DAMAGE_CAPACITY,
    DAMAGE_SCALE,
    KO_TEXT,
    TAG_CAPACITY,
    Rgb,
    damage_color,
    damage_text,
    panel_lefts,
)
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel


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
