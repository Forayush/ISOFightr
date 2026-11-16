"""The UI kit sheet: every font size, block and widget on one screen, with a live cursor.

Plan note "13 - Game Modes UI and Flow" (decisions D-061 group 0 and D-072 group 1). Not part
of the game's flow: ``tools/capture_scene.py --screen kit`` shows it so the kit can be
reviewed. The same sampler is laid out twice, once on each surface: stone on the left (the
menus'; it is the live half, with the cursor) and ink on the right (what is drawn over a
match). It exercises what every screen relies on: the focus map with a stick, keys and the
mouse, the widgets' looks, the blocks that rise and sink, the tweens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.config import NATIVE_W
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes.menus import MenuView
from isofightr.ui import theme
from isofightr.ui.anim import blink, count_up, ease_out, progress, pulse
from isofightr.ui.focus import FocusMap, Rect
from isofightr.ui.font import ARROW_LEFT, ARROW_RIGHT, TextSize
from isofightr.ui.icons import load_icons
from isofightr.ui.kit_art import Look
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Button,
    Checkbox,
    FocusFrame,
    Gauge,
    KeyCap,
    PipGauge,
    Sign,
    Stepper,
    TabStrip,
    Toggle,
    UiLayer,
    add_plate,
    add_slab,
    text_bottom,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LEFT_SLAB = Rect(theme.MARGIN, 26, 304, 302)
RIGHT_SLAB = Rect(324, 26, 304, 302)
GAUGE_TICKS = 180
"""The demo gauges fill, then start again, over this many ticks."""
KEY_CAPTIONS = ("J", "K", "SPACE", "n/a")
STEPS = ("0.5x", "1.0x", "1.5x", "2.0x")
TABS = ("RULES", "CONTROLS", "DISPLAY")
PIPS = 8
ICONS_SHOWN = 6


class Sampler:
    """One of everything, on one surface."""

    def __init__(self, ui: UiLayer, slab: Rect, surface: theme.Surface) -> None:
        """Lay the kit out on a slab of ``surface``."""
        add_slab(ui, slab, surface)
        x, top, right = slab.left + theme.PAD, slab.top, slab.right - theme.PAD
        plate = Rect(x, top - 30, 100, 23)
        add_plate(ui, plate, surface)
        ui.write_in(
            Rect(plate.left, plate.bottom + theme.LIP, plate.width, 14),
            surface.name.upper(),
            TextSize.TITLE,
            surface.text,
            shadow=False,
        )
        self.prompt = ui.write(
            "PRESS A KEY", x + 110, top - 26, TextSize.TITLE, surface.accent, shadow=False
        )
        self.number = ui.write(
            "0%", right, top - 34, TextSize.NUMERAL, surface.text, "right", surface.shadow
        )

        def write(text: str, y: int, size: TextSize, color: theme.Rgb) -> None:
            ui.write(text, x, top - y, size, color, shadow=surface.shadow)

        write("Title: Bramble, the heavyweight", 52, TextSize.TITLE, surface.text)
        write(
            "Text: a mossy stone golem. Slow, with a huge reach.", 66, TextSize.TEXT, surface.text
        )
        write("Second rank: who it is for and what it does.", 78, TextSize.TEXT, surface.text_muted)
        write("Body: 0123456789% (3:00) <1.0x> [J]", 92, TextSize.BODY, surface.text)
        arrows = f"small: tags and fine print   {ARROW_LEFT} {ARROW_RIGHT} ↑ ↓"
        write(arrows, 103, TextSize.SMALL, surface.text_muted)

        self.buttons = {
            "play": Button(
                ui, Rect(x, top - 134, 88, theme.BUTTON_HEIGHT), "VERSUS", "stock", surface=surface
            ),
            "rules": Button(
                ui,
                Rect(x + 94, top - 134, 88, theme.BUTTON_HEIGHT),
                "RULES",
                "gear",
                surface=surface,
            ),
            "default": Button(
                ui,
                Rect(x + 188, top - 134, 96, theme.BUTTON_HEIGHT),
                "DEFAULT",
                look=Look.CAUTION,
                surface=surface,
            ),
        }
        write("Launch rate", 156, TextSize.TEXT, surface.text)
        self.stepper = Stepper(ui, Rect(x + 150, top - 160, 86, 16), STEPS[1], surface)
        write("Parry", 176, TextSize.TEXT, surface.text)
        self.toggle = Toggle(ui, Rect(x + 196, top - 181, 40, 17), surface=surface, block=True)
        write("In the random pool", 196, TextSize.TEXT, surface.text)
        self.checkbox = Checkbox(ui, x + 225, top - 198)
        write("Power", 214, TextSize.TEXT, surface.text_muted)
        self.pips = PipGauge(ui, x + 44, top - 213, PIPS)
        self.gauge = Gauge(ui, Rect(x + 130, top - 214, 70, 9), segmented=True)
        self.plain_gauge = Gauge(ui, Rect(x + 210, top - 214, 74, 9), fill=theme.ON)

        self.caps: dict[str, KeyCap] = {}
        cap_x = x
        for caption in KEY_CAPTIONS:
            width = 28 if len(caption) <= 1 else 50
            look = Look.DANGER if caption == "n/a" else Look.NORMAL
            self.caps[caption] = KeyCap(
                ui, Rect(cap_x, top - 250, width, 28), caption, look, surface=surface
            )
            cap_x += width + theme.GAP
        KeyCap(ui, Rect(cap_x + 8, top - 250, 28, 28), "U", Look.LIT, surface=surface)
        KeyCap(ui, Rect(cap_x + 40, top - 250, 28, 28), "T", Look.DISABLED, surface=surface)
        for index, name in enumerate(list(load_icons())[:ICONS_SHOWN]):
            ui.icon(
                name,
                right - 44 + (index % 3) * 15,
                top - 235 - (index // 3) * 14,
                surface.text,
            )

        self.tabs = TabStrip(ui, x, top - 276, TABS, 20, surface)
        self.sign = Sign(
            ui,
            Rect(x, slab.bottom + theme.LIP + 4, slab.width - 2 * theme.PAD, 16),
            "A sign holds one line of help, in sentence case.",
            surface,
        )


class UiKitView(MenuView):
    """Shows the kit. The stick, keys or mouse move the cursor; confirm presses a widget."""

    surface = theme.STONE

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Lay everything out."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.header("UI kit", "gear")
        self.live = Sampler(self.ui, LEFT_SLAB, theme.STONE)
        """The stone half: the one the cursor moves on."""
        self.still = Sampler(self.ui, RIGHT_SLAB, theme.INKED)
        """The ink half: the same things at rest (with its first button under a cursor of
        its own, so both looks show)."""
        self.still.buttons["play"].focus(True)
        self.still.toggle.set(True)
        self.still.pips.lit = 5
        self.still.gauge.value = 0.6
        self.still.plain_gauge.value = 0.4
        self.still.number.text = "87%"
        self.still.tabs.set(1, False)
        self.buttons = self.live.buttons
        self.stepper, self.toggle, self.checkbox = (
            self.live.stepper,
            self.live.toggle,
            self.live.checkbox,
        )
        self.caps = self.live.caps
        self.step = 1
        self.parry = False
        self.pooled = True
        self.tab = 0

        rects = {name: button.rect for name, button in self.buttons.items()}
        rects |= {"step": self.stepper.rect, "parry": self.toggle.rect, "pool": self.checkbox.rect}
        rects |= {f"key:{caption}": cap.rect for caption, cap in self.caps.items()}
        rects |= {"tabs": self.live.tabs.rect}
        self.focus_map = FocusMap(rects)
        self.cursor = "play"
        self.frame = FocusFrame(self.ui)
        self.footer("{stick}: move   {attack}: press   {special}: back   mouse: hover and click")
        self.refresh()

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the widget under the mouse."""
        name = self.focus_map.at(x, y)
        if name is None:
            return False
        self.cursor = name
        return True

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, press what it is on, or leave."""
        if action is MenuAction.BACK:
            self.flow.show_main_menu()
        elif action is MenuAction.EXTRA:
            self.tab = (self.tab + 1) % len(TABS)
        elif action is not MenuAction.CONFIRM:
            sideways = action in (MenuAction.LEFT, MenuAction.RIGHT)
            change = 1 if action is MenuAction.RIGHT else -1
            if self.cursor == "step" and sideways:
                self.step = min(max(self.step + change, 0), len(STEPS) - 1)
            elif self.cursor == "tabs" and sideways:
                self.tab = min(max(self.tab + change, 0), len(TABS) - 1)
            else:
                self.cursor = self.focus_map.move(self.cursor, action)
        elif self.cursor in self.buttons:
            self.buttons[self.cursor].press(self.tick_count)
        elif self.cursor == "parry":
            self.parry = not self.parry
        elif self.cursor == "pool":
            self.pooled = not self.pooled
        elif self.cursor == "step":
            self.step = (self.step + 1) % len(STEPS)

    def refresh(self) -> None:
        """Show the cursor and run the demo animations."""
        tick = self.tick_count
        for name, button in self.buttons.items():
            button.focus(name == self.cursor)
            button.settle(tick)
        self.stepper.set(STEPS[self.step], self.cursor == "step")
        self.toggle.set(self.parry, self.cursor == "parry")
        self.checkbox.set(self.pooled, self.cursor == "pool")
        for caption, cap in self.caps.items():
            rest = Look.DANGER if caption == "n/a" else Look.NORMAL
            cap.set(caption, Look.FOCUS if self.cursor == f"key:{caption}" else rest)
        self.live.tabs.set(self.tab, self.cursor == "tabs")
        fill = ease_out(progress(tick % GAUGE_TICKS, 0, GAUGE_TICKS // 2))
        self.live.gauge.value = fill
        self.live.pips.lit = round(fill * PIPS)
        self.live.plain_gauge.value = pulse(tick, GAUGE_TICKS)
        self.live.number.text = f"{count_up(tick % GAUGE_TICKS, 0, GAUGE_TICKS // 2, 187)}%"
        self.live.prompt.visible = blink(tick, 40)
        if self.cursor in self.buttons or self.cursor == "tabs":
            self.frame.hide()
        else:
            self.frame.show(self.focus_map.rects[self.cursor], tick)


assert LEFT_SLAB.right < RIGHT_SLAB.left and RIGHT_SLAB.right <= NATIVE_W
assert text_bottom  # the kit's own layout helper, kept in the screen's namespace for tools
