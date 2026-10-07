"""The battle HUD's player cards, combo counters and off-screen bubbles.

Plan note "13 - Game Modes UI and Flow" ("Battle HUD", decision D-061 item 9): one card per
player along the bottom, in the player's (or team's) colour with an angled frame: the bust,
a big damage number that rolls up to its new value, flashes and jumps on a hit, trembles at
high percent and follows the colour ramp; stock icons that break when a stock is lost; the
name with a CPU or team badge; the score when it is shown, and a crown for the leader. A
combo counter over the victim's card, and a bubble at the edge of the play area for a
fighter out of view, with its bust, its percent and an arrow.

Layout, colours and timings are in :mod:`isofightr.ui.hud_layout`, the art in
:mod:`isofightr.ui.hud_art`, the remembered state in :mod:`isofightr.ui.hud_state`; this
module only places sprites. The clock, the KO feed, popups and banners are in
:mod:`isofightr.ui.hud_extras`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import arcade
from PIL import Image

from isofightr.render import placeholder_art as art
from isofightr.render.effects import BattleEffects
from isofightr.sim.fighter import Fighter
from isofightr.ui import anim, font, hud_art, theme
from isofightr.ui import hud_layout as layout
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hud_layout import (
    BUBBLE_SIZE,
    KO_TEXT,
    MAX_STOCK_ICONS,
    STOCK_SLOT_SIZE,
    bubble_layout,
    combo_text,
    damage_color,
    damage_text,
    score_text,
    stock_count_text,
    stock_icons_shown,
)
from isofightr.ui.hud_state import SHATTER_TICKS, HudState
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import Picture, TextLabel, UiLayer, icon_texture, picture_texture

BADGE_HEIGHT = 9
BADGE_PAD = 3
COMBO_HEIGHT = 18
SHARD_SPEED = 1.2
"""How fast the pieces of a broken stock icon fly apart, in pixels per tick."""
SHARD_GRAVITY = 0.12
BUBBLE_FACE = 18
"""The bust is cropped to this square inside a bubble."""


@dataclass(frozen=True, slots=True)
class CardInfo:
    """What a player's card shows that does not change during a match."""

    name: str
    color: int
    """The player's colour index (its team's in a team match)."""
    bust: arcade.Texture | None = None
    icon: arcade.Texture | None = None
    cpu: int = 0
    team: int | None = None


class DamageHud:
    """The player cards (and the combo counters and off-screen bubbles), drawn in native
    screen space."""

    def __init__(self, glyphs: GlyphAtlas, cards: Sequence[CardInfo]) -> None:
        """Create every card's parts. ``glyphs`` is unused (the HUD draws in the game's
        font since M13) and kept so older callers still work."""
        del glyphs
        self.ui = UiLayer(GlyphAtlas())
        self.info = list(cards)
        self.rects = layout.card_rects(len(cards))
        self.ramps = [theme.player_ramp(card.color) for card in cards]
        self._frames: list[Picture] = []
        self._damage: list[TextLabel] = []
        self._names: list[TextLabel] = []
        self._score: list[TextLabel] = []
        self._stock_icons: list[list[arcade.Sprite]] = []
        self._stock_text: list[TextLabel] = []
        self._crowns: list[arcade.Sprite] = []
        self._combo: list[TextLabel] = []
        self._combo_plates: list[Picture] = []
        self._bubbles: list[arcade.Sprite] = []
        self._bubble_faces: list[arcade.Sprite] = []
        self._bubble_arrows: list[arcade.Sprite] = []
        self._bubble_text: list[TextLabel] = []
        self._shards: list[arcade.Sprite] = []
        self._shard_textures: list[list[tuple[arcade.Texture, tuple[int, int]]]] = []
        self._lit = [False] * len(cards)
        for index, (card, rect) in enumerate(zip(cards, self.rects, strict=True)):
            self._add_card(index, card, rect)
        for index, card in enumerate(cards):
            self._add_bubble(index, card)

    # --- building --------------------------------------------------------------------------

    def _add_card(self, index: int, card: CardInfo, rect: Rect) -> None:
        ui, ramp = self.ui, self.ramps[index]
        frame = Picture(ui, rect)
        self._frames.append(frame)
        self._show_frame(index, False)
        well = layout.BUST
        ui.picture(
            ("hud-well", well.width, ramp),
            lambda: hud_art.bust_well(well.width, ramp),
            rect.left + well.left,
            rect.bottom + well.bottom,
        )
        bust = card.bust or card.icon or self._placeholder_icon(card.color)
        ui.image(
            bust,
            rect.left + well.left + (well.width - bust.width) // 2,
            rect.bottom + well.bottom + (well.height - bust.height) // 2,
        )
        crown = arcade.Sprite(icon_texture("crown", theme.GOLD) or bust)
        crown.position = (rect.left + well.left + 7, rect.bottom + layout.CROWN_BOTTOM + 6)
        crown.visible = False
        ui.panels.append(crown)
        self._crowns.append(crown)

        name_x = rect.left + layout.NAME_LEFT
        name = ui.write(
            f"P{index + 1} {card.name}".upper(),
            name_x,
            rect.bottom + layout.NAME_BOTTOM,
            TextSize.SMALL,
            ramp[0],
        )
        self._names.append(name)
        badge_left = name.left + name.width + 4
        for text, color in self._badges(index, card):
            width = font.text_width(text, TextSize.SMALL) + 2 * BADGE_PAD
            ui.picture(
                ("hud-badge", width, color),
                lambda width=width, color=color: hud_art.badge(width, BADGE_HEIGHT, color),
                badge_left,
                rect.bottom + layout.NAME_BOTTOM - 1,
            )
            ui.write(
                text,
                badge_left + BADGE_PAD,
                rect.bottom + layout.NAME_BOTTOM,
                TextSize.SMALL,
                theme.INK,
                shadow=False,
            )
            badge_left += width + 3

        icon = card.icon or self._placeholder_icon(card.color)
        row = []
        for slot in range(MAX_STOCK_ICONS):
            sprite = arcade.Sprite(
                icon,
                center_x=rect.left + layout.STOCK_LEFT + slot * layout.CARD_STOCK_STEP + 6,
                center_y=rect.bottom + layout.STOCK_BOTTOM + STOCK_SLOT_SIZE / 2,
            )
            sprite.visible = False
            ui.panels.append(sprite)
            row.append(sprite)
        self._stock_icons.append(row)
        self._shard_textures.append(self._shard_pieces(icon))
        self._stock_text.append(
            ui.write(
                "",
                rect.left + layout.STOCK_LEFT + 15,
                rect.bottom + layout.STOCK_BOTTOM + 2,
                TextSize.SMALL,
            )
        )
        self._damage.append(
            ui.write(
                "0%",
                rect.right - layout.DAMAGE_RIGHT,
                rect.bottom + layout.DAMAGE_BOTTOM,
                TextSize.NUMERAL,
                align="right",
            )
        )
        self._score.append(
            ui.write(
                "",
                rect.right - layout.DAMAGE_RIGHT,
                rect.bottom + layout.NAME_BOTTOM,
                TextSize.SMALL,
                theme.GOLD,
                align="right",
            )
        )
        plate = Picture(ui, Rect(rect.left + 2, rect.top + 2, 1, COMBO_HEIGHT))
        self._combo_plates.append(plate)
        self._combo.append(
            ui.write("", rect.left + 8, rect.top + 5, TextSize.TITLE, theme.FOCUS_GLOW)
        )

    def _badges(self, index: int, card: CardInfo) -> list[tuple[str, theme.Rgb]]:
        badges = []
        if card.cpu:
            badges.append((f"CPU{card.cpu}", self.ramps[index][1]))
        if card.team is not None:
            badges.append(("TEAM", theme.player_color(card.team)))
        return badges

    def _add_bubble(self, index: int, card: CardInfo) -> None:
        ui, ramp = self.ui, self.ramps[index]
        bubble = arcade.Sprite(
            picture_texture(
                ("hud-bubble", BUBBLE_SIZE, ramp), lambda: hud_art.bubble(BUBBLE_SIZE, ramp)
            )
        )
        bubble.visible = False
        ui.panels.append(bubble)
        self._bubbles.append(bubble)
        face = arcade.Sprite(self._face(card))
        face.visible = False
        ui.panels.append(face)
        self._bubble_faces.append(face)
        arrow = arcade.Sprite(self._arrow(0, index))
        arrow.visible = False
        ui.panels.append(arrow)
        self._bubble_arrows.append(arrow)
        self._bubble_text.append(ui.write("", 0, 0, TextSize.BODY, ramp[0], "centre"))

    def _arrow(self, direction: int, index: int) -> arcade.Texture:
        ramp = self.ramps[index]
        return picture_texture(
            ("hud-arrow", direction, ramp), lambda: hud_art.bubble_arrow(direction, ramp)
        )

    def _face(self, card: CardInfo) -> arcade.Texture:
        source = card.bust or card.icon
        if source is None:
            return self._placeholder_icon(card.color)
        image = source.image.convert("RGBA")
        size = min(BUBBLE_FACE, image.width, image.height)
        left = (image.width - size) // 2
        top = max((image.height - size) // 3, 0)
        face = image.crop((left, top, left + size, top + size))
        return arcade.Texture(face, hash=f"hud-face:{id(source)}")

    def _placeholder_icon(self, color: int) -> arcade.Texture:
        return picture_texture(("hud-disc", color), lambda: art.build_stock_icon(color))

    def _shard_pieces(self, icon: arcade.Texture) -> list[tuple[arcade.Texture, tuple[int, int]]]:
        image: Image.Image = icon.image.convert("RGBA")
        pieces = []
        for number, (piece, offset) in enumerate(hud_art.shards(image)):
            texture = arcade.Texture(piece, hash=f"hud-shard:{id(icon)}:{number}")
            pieces.append((texture, offset))
        return pieces

    def _show_frame(self, index: int, lit: bool) -> None:
        rect, ramp = self.rects[index], self.ramps[index]
        self._frames[index].show(
            ("hud-card", rect.width, rect.height, ramp, lit),
            lambda: hud_art.card(rect.width, rect.height, ramp, lit),
        )

    # --- per frame -------------------------------------------------------------------------

    def update(
        self,
        fighters: Sequence[Fighter],
        effects: BattleEffects,
        scores: Sequence[int] | None = None,
        state: HudState | None = None,
        shake: float = 1.0,
        flashing: bool = True,
    ) -> None:
        """Refresh the cards from the current state.

        ``scores`` (one per player) shows each player's score and crowns the leader;
        ``None`` hides them (the Rules screen's "score display"). ``state`` gives the
        rolling numbers, hit flashes and breaking stocks (without it the real percent shows
        at once). ``shake`` is the screen-shake setting (0 to 1) for the trembling number;
        ``flashing`` off ("reduce flashing") keeps the number and frame from flashing.
        """
        crowned = None if scores is None else layout.leader(list(scores))
        tick = 0 if state is None else state.tick
        for fighter in fighters:
            index = fighter.player_index
            rect = self.rects[index]
            self._score[index].text = "" if scores is None else score_text(scores[index])
            self._crowns[index].visible = crowned == index
            shown = fighter.damage if state is None else state.shown_damage(index)
            label = self._damage[index]
            label.text = damage_text(shown) if fighter.in_play else KO_TEXT
            hit = state is not None and flashing and state.flash.get(index, 0) > 0
            label.color = theme.WHITE if hit else damage_color(shown)
            if hit != self._lit[index]:
                self._lit[index] = hit
                self._show_frame(index, hit)
            amplitude = layout.shake_amplitude(shown, shake if flashing else 0.0)
            jitter_x = anim.shake(tick, amplitude)
            jitter_y = anim.shake(tick + 7, amplitude)
            lift = effects.hud_offset(index)
            label.move_to(
                rect.right - layout.DAMAGE_RIGHT + jitter_x,
                rect.bottom + layout.DAMAGE_BOTTOM + lift + jitter_y,
            )
            shown_icons = stock_icons_shown(fighter.stocks)
            for slot, sprite in enumerate(self._stock_icons[index]):
                sprite.visible = slot < shown_icons
            self._stock_text[index].text = stock_count_text(fighter.stocks)
            self._update_combo(index, effects)
        self._update_shards(state)

    def _update_combo(self, index: int, effects: BattleEffects) -> None:
        readout = effects.combos.get(index)
        text = "" if readout is None else combo_text(readout.hits, readout.damage)
        label, plate = self._combo[index], self._combo_plates[index]
        if text == label.text:
            return
        label.text = text
        if not text:
            plate.hide()
            return
        width = label.width + 12
        rect = self.rects[index]
        plate.sprite.position = (rect.left + 2 + width / 2, rect.top + 2 + COMBO_HEIGHT / 2)
        plate.show(("hud-combo", width), lambda: hud_art.combo_plate(width, COMBO_HEIGHT))

    def _update_shards(self, state: HudState | None) -> None:
        shatters = [] if state is None else state.shatters
        needed = 4 * len(shatters)
        while len(self._shards) < needed:
            sprite = arcade.Sprite()
            sprite.visible = False
            self.ui.panels.append(sprite)
            self._shards.append(sprite)
        for sprite in self._shards[needed:]:
            sprite.visible = False
        for number, shatter in enumerate(shatters):
            rect = self.rects[shatter.player]
            x0 = rect.left + layout.STOCK_LEFT + shatter.slot * layout.CARD_STOCK_STEP
            y0 = rect.bottom + layout.STOCK_BOTTOM + STOCK_SLOT_SIZE
            age = shatter.age
            for piece, (texture, (dx, dy)) in enumerate(self._shard_textures[shatter.player]):
                sprite = self._shards[4 * number + piece]
                sprite.texture = texture
                spread_x = -1 if dx == 0 else 1
                rise = 1.5 if dy == 0 else 0.6
                x = x0 + dx + texture.width / 2 + spread_x * SHARD_SPEED * age
                y = y0 - dy - texture.height / 2 + rise * age - SHARD_GRAVITY * age * age / 2
                sprite.position = (round(x), round(y))
                sprite.alpha = max(255 - 255 * age // SHATTER_TICKS, 0)
                sprite.visible = True

    def place_bubbles(
        self,
        fighters: Sequence[Fighter],
        screen_positions: Sequence[tuple[float, float]],
        state: HudState | None = None,
    ) -> None:
        """Show a bubble at the edge of the play area for each fighter out of it, with an
        arrow pointing at the fighter. ``screen_positions`` are native screen pixels."""
        for parts in zip(self._bubbles, self._bubble_faces, self._bubble_arrows, strict=True):
            for sprite in parts:
                sprite.visible = False
        for label in self._bubble_text:
            label.text = ""
        for fighter, (x, y) in zip(fighters, screen_positions, strict=True):
            spot = bubble_layout(x, y)
            index = fighter.player_index
            if spot is None or not fighter.in_play:
                continue
            bx, by, direction = spot
            bubble, face = self._bubbles[index], self._bubble_faces[index]
            bubble.position = (bx + 0.5, by + 0.5)
            face.position = (bx + (face.width % 2) / 2, by + (face.height % 2) / 2)
            arrow = self._bubble_arrows[index]
            arrow.texture = self._arrow(direction, index)
            dx, dy = ARROW_STEPS[direction]
            reach = BUBBLE_SIZE // 2 + 4
            arrow.position = (bx + dx * reach + 0.5, by + dy * reach + 0.5)
            for sprite in (bubble, face, arrow):
                sprite.visible = True
            shown = fighter.damage if state is None else state.shown_damage(index)
            label = self._bubble_text[index]
            label.text = damage_text(shown)
            label.move_to(bx, by - BUBBLE_SIZE // 2 - 13)

    def bubble_shown(self, player_index: int) -> bool:
        """Return whether a player's off-screen bubble is showing."""
        return bool(self._bubbles[player_index].visible)

    def score_shown(self, player_index: int) -> str:
        """Return the score text a player's card is showing ("" when scores are off)."""
        return self._score[player_index].text

    def stocks_shown(self, player_index: int) -> int:
        """Return how many stock icons a player's card is showing."""
        return sum(bool(sprite.visible) for sprite in self._stock_icons[player_index])

    def crowned(self) -> int | None:
        """Return the player wearing the leader's crown, if any."""
        return next((index for index, crown in enumerate(self._crowns) if crown.visible), None)

    def fixed_rects(self) -> list[Rect]:
        """The rectangles the cards always cover (for the play-area test)."""
        return list(self.rects)

    def draw(self) -> None:
        """Draw the cards. Call inside ``pixel_buffer.drawing()`` without a world camera."""
        self.ui.draw()


ARROW_STEPS: tuple[tuple[float, float], ...] = (
    (1, 0),
    (0.7, 0.7),
    (0, 1),
    (-0.7, 0.7),
    (-1, 0),
    (-0.7, -0.7),
    (0, -1),
    (0.7, -0.7),
)
"""Unit steps toward each of the eight arrow directions (screen y up)."""
