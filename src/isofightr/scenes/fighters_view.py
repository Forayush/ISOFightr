"""The Fighters screen: a card for every character, under its fighter at the ring.

Decision D-077. The main menu's Fighters button glides the camera to the ring framed high
(the ``gallery`` station), where every character drops onto a spot and stands there live at
twice its battle size, a card under each (:mod:`isofightr.scenes.fighter_cards` says what is
on it, :mod:`isofightr.ui.card_art` draws it). The stick moves between the cards (the
fighter whose card the cursor reaches taunts), attack makes it cheer (its victory), the
strong button changes its costume, back returns to the main menu. More characters than ring
spots go on pages of four: stepping past the last card of a page opens the next.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.placeholder_art import NO_PLAYER
from isofightr.scenes import fighter_cards as cards_model
from isofightr.scenes.fighter_cards import FighterCard
from isofightr.scenes.menu_world_model import RING_SPOTS, STATIONS, Mood, rest_pose, screen_point
from isofightr.scenes.menus import MenuView
from isofightr.scenes.roster_model import STAT_NAMES, costume_colors, next_costume
from isofightr.ui import card_art, theme
from isofightr.ui.anim import ease_out_back, slide
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.font import TextSize
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import Gauge, Picture, SlideGroup, TextLabel

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

GALLERY = rest_pose(STATIONS["gallery"])
COSTUME_STEPS = {MenuAction.ALT: 1, MenuAction.ALT_BACK: -1}
FOOTER = "{stick}: browse   {attack}: cheer   {strong}: costume   {special}: back"
FOOTER_DROP = ("strong",)
PAGE_LABEL = (NATIVE_W - theme.MARGIN, NATIVE_H - 18)
"""Where "Page 1 of 2" stands (its right end), when there is more than one page."""


def spot_columns() -> list[int]:
    """Return the screen column of each ring spot's fighter at the gallery."""
    return [screen_point(GALLERY, x, y)[0] for x, y in RING_SPOTS]


class CardWidgets:
    """The sprites of one card on the screen."""

    def __init__(self, view: FightersView, card: FighterCard, slot: int, costumes: int) -> None:
        """Lay the card out under ring spot ``slot``."""
        ui, layout = view.ui, cards_model.card_layout()
        self.card = card
        self.rect = cards_model.card_rect(view.columns[slot])
        left, bottom = self.rect.left, self.rect.bottom
        colours = card.colours

        def at(box: Rect) -> Rect:
            return Rect(left + box.left, bottom + box.bottom, box.width, box.height)

        with SlideGroup(ui) as group:
            self.body = Picture(ui, self.rect)
            ui.write_in(
                at(layout.band), colours.label, TextSize.TEXT, colours.band_text, "left",
                shadow=False, pad=cards_model.INSET - 1,
            )  # fmt: skip
            ui.write_in(at(layout.name), card.name, TextSize.TITLE, theme.INK, "left", pad=0)
            for box, line in zip(layout.description, card.description, strict=False):
                ui.write_in(at(box), line, TextSize.TEXT, theme.INK, "left", pad=0)
            for box, line in zip(layout.specials, card.specials, strict=True):
                ui.write_in(at(box), line, TextSize.SMALL, theme.DEEP_TEAL, "left", pad=0)
            surface = view.surface
            self.gauges: dict[str, Gauge] = {}
            for row, stat in zip(layout.stats, STAT_NAMES, strict=True):
                ui.write_in(
                    at(layout.label(row)), cards_model.STAT_WORDS[stat], TextSize.SMALL,
                    surface.text_muted, "left", pad=0,
                )  # fmt: skip
                self.gauges[stat] = Gauge(
                    ui, at(layout.gauge(row)), card.stats[stat], colours.ramp[1], segmented=True
                )
                ui.write_in(
                    at(layout.figure(row)), card.figures[stat], TextSize.SMALL, surface.text,
                    "right", pad=0,
                )  # fmt: skip
            self.facts: TextLabel = ui.write_in(
                at(layout.facts), card.facts, TextSize.SMALL, surface.text_muted, "left", pad=0
            )
            self.swatches = [Picture(ui, at(box)) for box in cards_model.swatch_rects(costumes)]
        self.group = group
        self.focused: bool | None = None
        self.shown_costume = -1
        self.dividers = layout.dividers

    def show(self, focused: bool, costume: int, colors: list[theme.Rgb]) -> None:
        """Draw the card at rest or under the cursor, ringing the costume on show."""
        if focused != self.focused:
            self.focused = focused
            width, height = self.rect.width, self.rect.height
            colours, band = self.card.colours, cards_model.BAND
            self.body.show(
                ("fighter-card", width, height, colours, band, self.dividers, focused),
                lambda: card_art.fighter_card(width, height, colours, band, self.dividers, focused),
            )
        if costume != self.shown_costume:
            self.shown_costume = costume
            size = cards_model.SWATCH
            for index, (picture, color) in enumerate(zip(self.swatches, colors, strict=False)):
                shown = index == costume
                picture.show(
                    ("costume-chip", size, color, shown),
                    partial(card_art.costume_chip, size, color, shown),
                )


class FightersView(MenuView):
    """Every character's card, with its fighter standing over it."""

    station = "gallery"
    surface = theme.STONE

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, focus: int = 0) -> None:
        """Make the cards of the page the cursor starts on."""
        super().__init__(pixel_buffer, flow)
        self.character_ids = list_character_ids()
        self.cards = cards_model.fighter_cards(
            [load_character(name) for name in self.character_ids]
        )
        count = len(self.cards)
        self.focus = min(max(focus, 0), max(count - 1, 0))
        self.page = cards_model.page_of(self.focus)
        self.shown = list(cards_model.on_page(self.page, count))
        """The cards on this page, by index into :attr:`cards`; ring spot = position."""
        self.columns = spot_columns()
        self.costumes = [0] * count
        self.costume_counts: list[int] = []
        self.colors: list[list[theme.Rgb]] = []
        for card in self.cards:
            bank = self.world.bank(card.id)
            costumes = 1 if bank is None else max(len(bank.sprite_set.costumes), 1)
            self.costume_counts.append(costumes)
            self.colors.append([] if bank is None else costume_colors(bank.sprite_set))
        self.header("Fighters", "card")
        self.widgets = [
            CardWidgets(self, self.cards[index], slot, len(self.colors[index]))
            for slot, index in enumerate(self.shown)
        ]
        self.focus_map = FocusMap(
            {
                str(index): widget.rect
                for index, widget in zip(self.shown, self.widgets, strict=True)
            }
        )
        """The cards under the mouse, by their index (as text) into :attr:`cards`."""
        self.page_label: TextLabel | None = None
        pages = cards_model.page_count(count)
        if pages > 1:
            self.page_label = self.ui.write(
                f"Page {self.page + 1} of {pages}",
                *PAGE_LABEL,
                TextSize.SMALL,
                self.surface.text_muted,
                "right",
            )
        self.footer(FOOTER, FOOTER_DROP)
        self.refresh()

    # --- the ring ----------------------------------------------------------------------------

    def slot_of(self, index: int) -> int:
        """Return the ring spot a card's fighter stands on."""
        return self.shown.index(index)

    def _stand_fighters(self) -> None:
        """Drop each fighter of the page onto its spot when its turn comes (not before the
        screen is on show: the one it replaces clears the ring as it goes)."""
        if self.window is None or self.window.current_view is not self:
            return
        for slot, index in enumerate(self.shown):
            if self.world.ring[slot] is None and self.tick_count >= cards_model.drop_tick(slot):
                card = self.cards[index]
                self.world.stand(slot, card.id, self.costumes[index], NO_PLAYER)
                self.world.pads[slot] = card.colours.ramp

    def on_hide_view(self) -> None:
        """Clear the ring for whoever is next."""
        self.world.clear_ring()

    # --- input -------------------------------------------------------------------------------

    def act(self, device: str, action: MenuAction) -> None:
        """Browse, cheer, change costume, or go back."""
        if action is MenuAction.BACK:
            self.flow.show_main_menu()
            return
        if action is MenuAction.CONFIRM:
            self._cheer()
            return
        step = COSTUME_STEPS.get(action)
        if step is not None:
            self._change_costume(step)
            return
        target = cards_model.move_focus(self.focus, action, len(self.cards))
        if target != self.focus:
            self._focus_on(target)

    def _focus_on(self, target: int) -> None:
        """Put the cursor on another card: on this page the fighter taunts, on another the
        screen opens that page."""
        if target not in self.shown:
            self.flow.show_fighters(target)
            return
        previous = self.slot_of(self.focus)
        if self._landed(previous):
            self.world.mood(previous, Mood.IDLE)
        self.focus = target
        if self._landed(self.slot_of(target)):
            self.world.mood(self.slot_of(target), Mood.READY)

    def _landed(self, slot: int) -> bool:
        """Return whether a spot's fighter is down from its drop (a mood now would cut the
        fall short)."""
        stand_in = self.world.ring[slot]
        if stand_in is None:
            return False
        return stand_in.mood is not Mood.DROP_IN or stand_in.pose(self.world.ticks).lift == 0

    def _cheer(self) -> None:
        """The focused fighter plays its victory."""
        slot = self.slot_of(self.focus)
        if self._landed(slot):
            self.world.mood(slot, Mood.WIN)

    def _change_costume(self, step: int) -> None:
        """Show the focused fighter in its next (or previous) costume."""
        index = self.focus
        count = self.costume_counts[index]
        if count <= 1:
            return
        self.audio.play("ui_pick")
        self.costumes[index] = next_costume(self.costumes[index], step, count)
        slot = self.slot_of(index)
        if self.world.ring[slot] is not None:
            self.world.stand(slot, self.cards[index].id, self.costumes[index], NO_PLAYER)

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the card under the mouse."""
        key = self.focus_map.at(x, y)
        if key is None:
            return False
        if int(key) != self.focus:
            self._focus_on(int(key))
        return True

    # --- per tick ----------------------------------------------------------------------------

    def refresh(self) -> None:
        """Stand the fighters as their turns come, raise the card under the cursor, and let
        the cards rise into place as the screen opens."""
        self._stand_fighters()
        tick = self.tick_count
        for slot, (index, widget) in enumerate(zip(self.shown, self.widgets, strict=True)):
            focused = index == self.focus
            widget.show(focused, self.costumes[index], self.colors[index])
            start = cards_model.rise_start(slot)
            rise = slide(
                tick, start, cards_model.RISE_TICKS, cards_model.RISE_FROM, 0, ease_out_back
            )
            widget.group.offset(0, rise + (theme.RAISE if focused else 0))

    @property
    def focused_card(self) -> FighterCard:
        """The card under the cursor."""
        return self.cards[self.focus]
