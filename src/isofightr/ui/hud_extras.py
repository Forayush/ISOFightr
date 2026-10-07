"""The rest of the battle HUD: the clock, the KO feed, the KO sash, damage popups and the big
banners (3, 2, 1, GO!, GAME!, SUDDEN DEATH).

Plan note "13 - Game Modes UI and Flow" ("Battle HUD", decision D-061 item 9). The clock
sits in the top band's middle and turns red and pulses in the last 30 seconds; the feed
lists the last three KOs in the top band's left end for about three seconds; the KO sash
crosses the upper play area when a stock is lost; a "+12%" rises where each hit lands,
coloured by its damage; and the banners pop in, in the logo's lettering. The state they
show is in :mod:`isofightr.ui.hud_state`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import arcade

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.sim.math3d import Vec3
from isofightr.ui import anim, hud_art, theme
from isofightr.ui import hud_layout as layout
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hud_state import BANNER_POP_TICKS, KO_BANNER_TICKS, MAX_POPUPS, HudState
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import Picture, TextLabel, UiLayer, picture_texture, text_bottom

CLOCK = layout.CLOCK
CLOCK_PULSE_TICKS = 30
FEED_LEFT = layout.FEED_LEFT
FEED_TOP = layout.FEED_TOP
FEED_ROW = layout.FEED_ROW
FEED_GAP = layout.FEED_GAP
SASH = (300, 26)
SASH_BOTTOM = 252
SASH_SLIDE_TICKS = 10
BANNER_CENTRE_Y = NATIVE_H // 2 + 40
BANNER_POP_SCALE = 1.8
GO_FADE_TICKS = 10
BANNER_KINDS = {"GO!": "mint", "SUDDEN DEATH": "red", "TIME!": "red"}
"""Banners that are not gold: GO! is mint, the sudden-death warning red."""

type ScreenPoint = Callable[[Vec3], tuple[float, float]]


class HudExtras:
    """The clock, the feed, the KO sash, the popups and the banners."""

    def __init__(self, ramps: Sequence[theme.Ramp], names: Sequence[str] = ()) -> None:
        """Create everything hidden. ``ramps`` are the players' colour ramps, ``names``
        how the KO sash names them."""
        self.ramps = list(ramps)
        self.names = list(names)
        self.ui = UiLayer(GlyphAtlas())
        """The clock and the banners: shown even with HUD display off."""
        self.hud_ui = UiLayer(GlyphAtlas())
        """The feed, the sash and the popups: hidden with HUD display off."""
        ui, hud_ui = self.ui, self.hud_ui
        self.clock_plate = Picture(ui, CLOCK)
        self.clock_icon = arcade.Sprite()
        self.clock_icon.visible = False
        ui.panels.append(self.clock_icon)
        self.clock = ui.write("", CLOCK.left + CLOCK.width // 2 + 7, CLOCK.bottom + 3,
                              TextSize.TITLE, theme.TEXT, "centre")  # fmt: skip
        self.banner_sprite = arcade.Sprite()
        self.banner_sprite.visible = False
        ui.text.append(self.banner_sprite)
        self.banner = _BannerText()

        self.feed_plates: list[Picture] = []
        self.feed_text: list[TextLabel] = []
        for row in range(layout.FEED_LINES):
            top = FEED_TOP - row * (FEED_ROW[1] + FEED_GAP)
            rect = Rect(FEED_LEFT, top - FEED_ROW[1], *FEED_ROW)
            self.feed_plates.append(Picture(hud_ui, rect))
            self.feed_text.append(
                hud_ui.write(
                    "", rect.left + 8, text_bottom(rect, TextSize.BODY), TextSize.BODY, theme.TEXT
                )
            )
        sash_rect = Rect((NATIVE_W - SASH[0]) // 2, SASH_BOTTOM, *SASH)
        self.sash_rect = sash_rect
        self.sash = Picture(hud_ui, sash_rect)
        self.sash_text = hud_ui.write("", NATIVE_W // 2, sash_rect.bottom + 5, TextSize.TITLE,
                                      theme.WHITE, "centre")  # fmt: skip
        self.popups = {
            size: [hud_ui.write("", 0, 0, size, theme.WHITE, "centre") for _ in range(MAX_POPUPS)]
            for size in (TextSize.BODY, TextSize.TITLE)
        }

    # --- per frame -------------------------------------------------------------------------

    def update(
        self,
        state: HudState,
        time_left: int | None,
        clock_text: str,
        banner: str,
        to_screen: ScreenPoint,
        flashing: bool = True,
    ) -> None:
        """Refresh everything from the HUD state. ``clock_text`` is the clock as text ("" for
        none); ``to_screen`` turns a world point into native screen pixels (for the
        popups)."""
        self._update_clock(time_left, clock_text, state.tick, flashing)
        self._update_banner(state, banner)
        self._update_feed(state)
        self._update_sash(state)
        self._update_popups(state, to_screen)

    def _update_clock(
        self, time_left: int | None, clock_text: str, tick: int, flashing: bool
    ) -> None:
        if time_left is None or not clock_text:
            self.clock.text = ""
            self.clock_plate.hide()
            self.clock_icon.visible = False
            return
        alarm = layout.clock_alarm(time_left)
        glow = alarm and flashing and anim.pulse(tick, CLOCK_PULSE_TICKS) > 0.5
        self.clock_plate.show(
            ("hud-clock", CLOCK.width, CLOCK.height, alarm, glow),
            lambda: hud_art.clock_plate(CLOCK.width, CLOCK.height, alarm, glow),
        )
        self.clock.text = clock_text
        self.clock.color = theme.SALMON if alarm else theme.TEXT
        color = theme.RED if alarm and not glow else theme.TEXT_MUTED
        texture = _icon("clock", theme.WHITE if glow else color)
        if texture is not None:
            self.clock_icon.texture = texture
            self.clock_icon.position = (CLOCK.left + 11, CLOCK.bottom + CLOCK.height / 2)
            self.clock_icon.visible = True

    def _update_banner(self, state: HudState, text: str) -> None:
        state.show_banner(text)
        self.banner.text = text
        sprite = self.banner_sprite
        if not text:
            sprite.visible = False
            return
        kind = BANNER_KINDS.get(text, "gold")
        sprite.texture = picture_texture(
            ("hud-banner", text, kind), lambda: hud_art.banner(text, kind)
        )
        age = state.banner_age()
        grow = anim.tween(age, 0, BANNER_POP_TICKS, BANNER_POP_SCALE, 1.0, anim.ease_out)
        sprite.scale = grow
        sprite.position = (
            NATIVE_W // 2 + (sprite.texture.width % 2) / 2,
            BANNER_CENTRE_Y + (sprite.texture.height % 2) / 2,
        )
        sprite.alpha = 255
        if text == "GO!" and age > layout.GO_TICKS - GO_FADE_TICKS:
            sprite.alpha = max(round(255 * (layout.GO_TICKS - age) / GO_FADE_TICKS), 0)
        sprite.visible = True

    def _update_feed(self, state: HudState) -> None:
        lines = list(reversed(state.feed))
        for row, (plate, label) in enumerate(zip(self.feed_plates, self.feed_text, strict=True)):
            if row >= len(lines):
                plate.hide()
                label.text = ""
                continue
            line = lines[row]
            ramp = self.ramps[line.victim % len(self.ramps)] if self.ramps else theme.EMPTY_RAMP
            slide = anim.slide(line.age, 0, layout.FEED_SLIDE_TICKS, -FEED_ROW[0], 0)
            left_out = layout.FEED_TICKS - line.age
            if left_out < layout.FEED_SLIDE_TICKS:
                slide = -round(FEED_ROW[0] * (1 - left_out / layout.FEED_SLIDE_TICKS))
            plate.show(
                ("hud-feed", *FEED_ROW, ramp[1]),
                lambda ramp=ramp: hud_art.feed_row(*FEED_ROW, ramp[1]),
            )
            rect = plate.rect
            plate.sprite.center_x = rect.left + rect.width / 2 + slide
            label.text = line.text
            label.move_to(rect.left + 8 + slide, label.bottom)

    def _update_sash(self, state: HudState) -> None:
        if state.ko_banner is None or not self.ramps:
            self.sash.hide()
            self.sash_text.text = ""
            return
        player, age = state.ko_banner
        ramp = self.ramps[player % len(self.ramps)]
        rect = self.sash_rect
        width = NATIVE_W
        slide = anim.slide(age, 0, SASH_SLIDE_TICKS, -width, 0, anim.ease_out_back)
        out = KO_BANNER_TICKS - age
        if out < SASH_SLIDE_TICKS:
            slide = round(width * (1 - out / SASH_SLIDE_TICKS))
        self.sash.show(("hud-sash", *SASH, ramp), lambda: hud_art.sash(*SASH, ramp))
        self.sash.sprite.center_x = rect.left + rect.width / 2 + slide
        name = self.names[player] if player < len(self.names) else f"P{player + 1}"
        self.sash_text.text = f"{name}  KO!"
        self.sash_text.move_to(NATIVE_W // 2 + slide, self.sash_text.bottom)

    def _update_popups(self, state: HudState, to_screen: ScreenPoint) -> None:
        free = {size: list(labels) for size, labels in self.popups.items()}
        for labels in self.popups.values():
            for label in labels:
                label.text = ""
        for popup in reversed(state.popups):
            big = popup.damage >= layout.BIG_POPUP_DAMAGE
            pool = free[TextSize.TITLE if big else TextSize.BODY]
            if not pool:
                continue
            label = pool.pop(0)
            x, y = to_screen(popup.position)
            label.text = layout.popup_text(popup.damage)
            label.color = layout.popup_color(popup.damage)
            label.alpha = layout.popup_alpha(popup.age)
            label.move_to(round(x), round(y) + 10 + layout.popup_offset(popup.age))

    def popups_shown(self) -> list[str]:
        """The popup texts on screen (for tests)."""
        return [label.text for labels in self.popups.values() for label in labels if label.text]

    def fixed_rects(self) -> list[Rect]:
        """The rectangles the clock and the feed can cover (for the play-area test)."""
        return [CLOCK, layout.feed_rect()]

    def draw(self, hud_display: bool) -> None:
        """Draw: the feed, sash and popups only with HUD display on; the clock and banners
        always."""
        if hud_display:
            self.hud_ui.draw()
        self.ui.draw()


class _BannerText:
    """The banner's text, for tests that read ``banner.text``."""

    text: str = ""


def _icon(name: str, color: theme.Rgb) -> arcade.Texture | None:
    from isofightr.ui.widgets import icon_texture

    return icon_texture(name, color)
