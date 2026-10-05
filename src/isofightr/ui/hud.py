"""The battle HUD: per-player damage, name and stocks along the bottom, and off-screen markers.

Plan note "13 - Game Modes UI and Flow" ("Battle HUD": panels on the bottom row colored by
player, damage % in a big pixel font with the color ramp from "09 - Art Direction", popping
when hit, stock icons, name; an edge bubble for fighters that are out of view). Portraits
arrive with real art in M8.

Layout and colors are worked out in :mod:`isofightr.ui.hud_layout`; this module draws.
"""

from collections.abc import Sequence

import arcade

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.render import placeholder_art as art
from isofightr.render.effects import BattleEffects
from isofightr.sim.fighter import Fighter
from isofightr.ui.hud_layout import (
    COMBO_CAPACITY,
    COMBO_COLOR,
    DAMAGE_CAPACITY,
    DAMAGE_SCALE,
    KO_TEXT,
    MAX_STOCK_ICONS,
    STOCK_ICON_STEP,
    STOCK_SLOT_SIZE,
    TAG_CAPACITY,
    Rgb,
    bubble_position,
    combo_text,
    damage_color,
    damage_text,
    panel_lefts,
    stock_count_text,
    stock_icons_shown,
)
from isofightr.ui.pixel_font import GLYPH_ADVANCE, GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

NAME_CAPACITY = 12
STOCK_ROW_HEIGHT = STOCK_SLOT_SIZE + 2
STOCK_TEXT_CAPACITY = len("x99")


class DamageHud:
    """One readout per player, drawn in native screen space.

    From the bottom up: the stock icons, the damage percent, the player tag and name, and
    (while the player is being comboed) the combo counter.
    """

    def __init__(
        self,
        glyphs: GlyphAtlas,
        player_count: int,
        bottom: int,
        names: Sequence[str] = (),
        colors: Sequence[int] = (),
        icons: Sequence[arcade.Texture | None] = (),
    ) -> None:
        """Create the labels and icons, with their bottom edge at ``bottom`` native pixels.

        ``colors`` gives each player's color index (its team's in a team match); by default
        every player has its own. ``icons`` gives each player's stock icon (the character's
        head in its costume); without one a disc in the player's color is used.
        """
        self.bottom = bottom
        self.sprites: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._lefts = panel_lefts(player_count)
        self._damage: list[PixelLabel] = []
        self._stock_text: list[PixelLabel] = []
        self._combo: list[PixelLabel] = []
        self._stock_icons: list[list[arcade.Sprite]] = []
        self._bubbles: list[arcade.Sprite] = []
        self._colors: list[Rgb | None] = [None] * player_count
        self._offsets = [0] * player_count
        self.damage_bottom = bottom + STOCK_ROW_HEIGHT
        tag_bottom = self.damage_bottom + GLYPH_HEIGHT * DAMAGE_SCALE
        for index, left in enumerate(self._lefts):
            color = colors[index] if index < len(colors) else index
            red, green, blue, _ = art.player_color(color)
            tag = PixelLabel(
                glyphs,
                self.sprites,
                left,
                tag_bottom,
                TAG_CAPACITY + NAME_CAPACITY,
                (red, green, blue),
            )
            self._combo.append(
                PixelLabel(
                    glyphs,
                    self.sprites,
                    left,
                    tag_bottom + GLYPH_HEIGHT,
                    COMBO_CAPACITY,
                    COMBO_COLOR,
                )
            )
            name = names[index][:NAME_CAPACITY] if index < len(names) else ""
            tag.text = f"P{index + 1} {name}".rstrip()
            self._damage.append(
                PixelLabel(
                    glyphs,
                    self.sprites,
                    left,
                    self.damage_bottom,
                    DAMAGE_CAPACITY,
                    scale=DAMAGE_SCALE,
                )
            )
            given = icons[index] if index < len(icons) else None
            icon = given or arcade.Texture(art.build_stock_icon(color))
            row = []
            for slot in range(MAX_STOCK_ICONS):
                sprite = arcade.Sprite(
                    icon,
                    center_x=left + slot * STOCK_ICON_STEP + STOCK_SLOT_SIZE / 2,
                    center_y=bottom + STOCK_SLOT_SIZE / 2,
                )
                sprite.visible = False
                self.sprites.append(sprite)
                row.append(sprite)
            self._stock_icons.append(row)
            self._stock_text.append(
                PixelLabel(
                    glyphs,
                    self.sprites,
                    left + STOCK_ICON_STEP + GLYPH_ADVANCE // 2,
                    bottom - 2,
                    STOCK_TEXT_CAPACITY,
                )
            )
            bubble = arcade.Sprite(arcade.Texture(art.build_bubble(color)))
            bubble.visible = False
            self.sprites.append(bubble)
            self._bubbles.append(bubble)

    def update(self, fighters: Sequence[Fighter], effects: BattleEffects) -> None:
        """Refresh the text, colors, stock icons and hit pops from the current state."""
        for fighter in fighters:
            index = fighter.player_index
            label = self._damage[index]
            label.text = damage_text(fighter.damage) if fighter.in_play else KO_TEXT
            color = damage_color(fighter.damage)
            if color != self._colors[index]:
                self._colors[index] = color
                label.color = color
            readout = effects.combos.get(index)
            self._combo[index].text = (
                "" if readout is None else combo_text(readout.hits, readout.damage)
            )
            offset = effects.hud_offset(index)
            if offset != self._offsets[index]:
                self._offsets[index] = offset
                label.move_to(self._lefts[index], self.damage_bottom + offset)
            shown = stock_icons_shown(fighter.stocks)
            for slot, sprite in enumerate(self._stock_icons[index]):
                sprite.visible = slot < shown
            self._stock_text[index].text = stock_count_text(fighter.stocks)

    def place_bubbles(
        self, fighters: Sequence[Fighter], screen_positions: Sequence[tuple[float, float]]
    ) -> None:
        """Show a marker at the screen edge for each fighter that is out of view.

        ``screen_positions`` are the fighters' positions in native screen pixels.
        """
        for bubble in self._bubbles:
            bubble.visible = False
        for fighter, (x, y) in zip(fighters, screen_positions, strict=True):
            spot = bubble_position(x, y, NATIVE_W, NATIVE_H)
            bubble = self._bubbles[fighter.player_index]
            if spot is not None and fighter.in_play:
                bubble.visible = True
                bubble.position = (spot[0] + 0.5, spot[1] + 0.5)

    def bubble_shown(self, player_index: int) -> bool:
        """Return whether a player's off-screen marker is showing."""
        return bool(self._bubbles[player_index].visible)

    def stocks_shown(self, player_index: int) -> int:
        """Return how many stock icons a player's panel is showing."""
        return sum(bool(sprite.visible) for sprite in self._stock_icons[player_index])

    def draw(self) -> None:
        """Draw the HUD. Call inside ``pixel_buffer.drawing()`` without a world camera."""
        self.sprites.draw(pixelated=True)
