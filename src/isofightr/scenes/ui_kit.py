"""The UI kit sheet: every font size, widget and icon on one screen, with a live cursor.

Plan note "13 - Game Modes UI and Flow" (decision D-061, group 0). Not part of the game's
flow: ``tools/capture_scene.py --screen kit`` shows it so the kit can be reviewed, and it
exercises the things every rebuilt screen relies on (the focus map with a stick, keys and
the mouse; widget looks; the tweens).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isofightr.config import NATIVE_H, NATIVE_W
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
    Stepper,
    Tab,
    Toggle,
    add_panel,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LEFT_PANEL = Rect(theme.MARGIN, 40, 300, 270)
RIGHT_PANEL = Rect(328, 40, 300, 270)
GAUGE_TICKS = 180
"""The demo gauge fills, then starts again, over this many ticks."""
KEY_CAPTIONS = ("J", "K", "SPACE", "L-SHIFT", "n/a")
STEPS = ("0.5x", "1.0x", "1.5x", "2.0x")


class UiKitView(MenuView):
    """Shows the kit. The stick, keys or mouse move the cursor; confirm presses a widget."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Lay everything out."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        ui = self.ui
        ui.write("UI KIT", theme.MARGIN, NATIVE_H - 34, TextSize.DISPLAY, theme.HEADING)
        self.tabs = [
            Tab(ui, Rect(388 + index * 60, NATIVE_H - 32, 64, 20), f"P{index + 1}", color)
            for index, color in enumerate(theme.PLAYER_COLORS)
        ]
        self.tab = 0

        add_panel(ui, LEFT_PANEL)
        x, top = LEFT_PANEL.left + theme.PAD, LEFT_PANEL.top
        ui.write("Display 87%", x, top - 30, TextSize.DISPLAY)
        ui.write("Title: Bramble, the heavyweight", x, top - 50, TextSize.TITLE)
        ui.write("Body: a mossy stone golem. Slow, huge reach.", x, top - 66, TextSize.BODY)
        ui.write(
            "Muted: 0123456789% (3:00) <1.0x> [J]", x, top - 80, TextSize.BODY,
            theme.TEXT_MUTED,
        )  # fmt: skip
        ui.write("small: tags and fine print 0123456789", x, top - 93, TextSize.SMALL, theme.FOG)
        self.number = ui.write("0%", LEFT_PANEL.right - theme.PAD, top - 34, TextSize.NUMERAL,
                               theme.AMBER, "right")  # fmt: skip
        arrows = f"{ARROW_LEFT} arrows {ARROW_RIGHT} ↑ ↓"
        ui.write(arrows, x, top - 108, TextSize.BODY, theme.FOCUS)

        self.buttons = {
            "play": Button(ui, Rect(x, top - 140, 88, theme.BUTTON_HEIGHT), "VERSUS", "stock"),
            "rules": Button(ui, Rect(x + 94, top - 140, 88, theme.BUTTON_HEIGHT), "RULES", "gear"),
            "default": Button(
                ui, Rect(x + 188, top - 140, 96, theme.BUTTON_HEIGHT), "DEFAULT", look=Look.DANGER
            ),
        }
        ui.write("Launch rate", x, top - 162, TextSize.BODY)
        self.stepper = Stepper(ui, Rect(x + 150, top - 166, 86, 16), STEPS[1])
        self.step = 1
        ui.write("Parry", x, top - 184, TextSize.BODY)
        self.toggle = Toggle(ui, Rect(x + 196, top - 188, 40, 16))
        self.parry = False
        ui.write("In the random pool", x, top - 206, TextSize.BODY)
        self.checkbox = Checkbox(ui, x + 225, top - 208)
        self.pooled = True
        ui.write("Power", x, top - 228, TextSize.BODY, theme.TEXT_MUTED)
        self.gauge = Gauge(ui, Rect(x + 60, top - 228, 120, 9), segmented=True)
        self.plain_gauge = Gauge(ui, Rect(x + 190, top - 228, 94, 9), fill=theme.ON)
        self.prompt = ui.write("PRESS A KEY", x, top - 252, TextSize.TITLE, theme.FOCUS)

        add_panel(ui, RIGHT_PANEL)
        x, top = RIGHT_PANEL.left + theme.PAD, RIGHT_PANEL.top
        ui.write("KEY CAPS", x, top - 18, TextSize.SMALL, theme.TEXT_MUTED)
        self.caps: dict[str, KeyCap] = {}
        cap_x = x
        for caption in KEY_CAPTIONS:
            width = 28 if len(caption) <= 1 else 62 if len(caption) > 5 else 50
            look = Look.DANGER if caption == "n/a" else Look.NORMAL
            self.caps[caption] = KeyCap(ui, Rect(cap_x, top - 50, width, 28), caption, look)
            cap_x += width + theme.GAP
        self.lit = KeyCap(ui, Rect(x, top - 86, 28, 28), "U", Look.LIT)
        ui.write("held right now (live test)", x + 36, top - 78, TextSize.BODY, theme.TEXT_MUTED)
        self.disabled = KeyCap(ui, Rect(x, top - 120, 28, 28), "T", Look.DISABLED)
        ui.write("not available", x + 36, top - 112, TextSize.BODY, theme.TEXT_MUTED)

        ui.write("ICONS", x, top - 140, TextSize.SMALL, theme.TEXT_MUTED)
        for index, name in enumerate(load_icons()):
            column, row = index % 8, index // 8
            ui.icon(name, x + column * 18, top - 160 - row * 34, theme.TEXT)
            ui.icon(name, x + column * 18, top - 176 - row * 34, theme.FOCUS)
        ui.write("PLAYER COLOURS", x, top - 232, TextSize.SMALL, theme.TEXT_MUTED)
        for index, color in enumerate(theme.PLAYER_COLORS):
            Button(ui, Rect(x + index * 70, top - 258, 64, 18), f"P{index + 1}").label.color = color

        rects = {name: button.rect for name, button in self.buttons.items()}
        rects |= {"step": self.stepper.rect, "parry": self.toggle.rect, "pool": self.checkbox.rect}
        rects |= {f"key:{caption}": cap.rect for caption, cap in self.caps.items()}
        self.focus_map = FocusMap(rects)
        self.cursor = "play"
        self.frame = FocusFrame(ui)
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
            self.tab = (self.tab + 1) % len(self.tabs)
        elif action is not MenuAction.CONFIRM:
            if self.cursor == "step" and action in (MenuAction.LEFT, MenuAction.RIGHT):
                change = 1 if action is MenuAction.RIGHT else -1
                self.step = min(max(self.step + change, 0), len(STEPS) - 1)
            else:
                self.cursor = self.focus_map.move(self.cursor, action)
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
        self.stepper.set(STEPS[self.step], self.cursor == "step")
        self.toggle.set(self.parry, self.cursor == "parry")
        self.checkbox.set(self.pooled, self.cursor == "pool")
        for caption, cap in self.caps.items():
            rest = Look.DANGER if caption == "n/a" else Look.NORMAL
            cap.set(caption, Look.FOCUS if self.cursor == f"key:{caption}" else rest)
        for index, tab in enumerate(self.tabs):
            tab.active = index == self.tab
        fill = ease_out(progress(tick % GAUGE_TICKS, 0, GAUGE_TICKS // 2))
        self.gauge.value = fill
        self.plain_gauge.value = pulse(tick, GAUGE_TICKS)
        self.number.text = f"{count_up(tick % GAUGE_TICKS, 0, GAUGE_TICKS // 2, 187)}%"
        self.prompt.visible = blink(tick, 40)
        if self.cursor in self.buttons:
            self.frame.hide()
        else:
            self.frame.show(self.focus_map.rects[self.cursor], tick)


assert LEFT_PANEL.right < RIGHT_PANEL.left <= NATIVE_W
