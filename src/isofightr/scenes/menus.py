"""The menus' shared base (:class:`MenuView`), the list menu and the settings screen.

Plan note "13 - Game Modes UI and Flow" ("Screen flow", "Character select screen",
"Settings"). Every scene is driven by every connected device through
:class:`isofightr.ui.menu.MenuInput`: move with the stick, attack or jump to confirm, special
or shield to go back. Enter and Escape also confirm and go back, as the WASD keyboard.
Scenes ask the :class:`~isofightr.scenes.flow.GameFlow` to move on.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

import arcade
from PIL import Image

from isofightr.audio.cues import UI_GLIDE
from isofightr.config import (
    AUDIO_MENU_SONG,
    NATIVE_H,
    NATIVE_W,
)
from isofightr.input.devices import KEYBOARD_PREFIX
from isofightr.input.keyboard import KeyLatch
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.pixel_scale import window_to_native
from isofightr.scenes.ticked_view import TickedView
from isofightr.settings import (
    CAMERA_ZOOMS,
    DEPTH_AIDS,
    HIT_EFFECTS,
    KEYBOARD_SOLO,
    SCALES,
    SHAKE_STEPS,
    VOLUME_MAX,
    Settings,
)
from isofightr.sim.input_frame import InputFrame
from isofightr.ui import font, kit_art, logo, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hints import device_labels, fit_hint, is_pad
from isofightr.ui.menu import MENU_SOUNDS, Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import (
    Gauge,
    Picture,
    PromptBar,
    Sign,
    Stepper,
    TextLabel,
    Toggle,
    UiLayer,
    add_panel,
    add_slab,
    icon_image,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

KEY_CONFIRM = arcade.key.ENTER
KEY_BACK = arcade.key.ESCAPE
KEY_NEXT_TAB = arcade.key.TAB
KEYBOARD_DEVICE = KEYBOARD_PREFIX + KEYBOARD_SOLO
"""The device Enter and Escape act as."""
MOUSE_LEFT = arcade.MOUSE_BUTTON_LEFT
MOUSE_RIGHT = arcade.MOUSE_BUTTON_RIGHT
NOTICE_TICKS = 180
"""How long a message stays in the bottom band (about three seconds)."""
ON_OFF = ("off", "on")
LIST_WIDTH = 400
"""Width of a list menu's panel."""
LIST_ROW_GAP = 1
"""Gap between two rows of a list menu: 1 since D-070, so Settings' 14 rows, the help line
and a clear gap above the footer all fit (at 2 the help line sat on the footer)."""
LIST_TOP_GAP = 8
"""Gap between the header and a list menu's panel."""
LIST_VALUE_WIDTH = 96
"""Width of the well a row's value sits in."""
LIST_SWITCH_WIDTH = 44
LIST_BAR_WIDTH = 70
LIST_HELP_HEIGHT = 18


class MenuView(TickedView):
    """Base of the menu scenes: polls every device each tick and draws one UI layer."""

    surface: ClassVar[theme.Surface] = theme.INKED
    """What the scene's blocks are made of (decision D-072): a screen rebuilt in M21 is
    ``theme.STONE``; one still to be rebuilt keeps the dark panels it was laid out for."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Create an empty scene with its own input devices."""
        super().__init__(pixel_buffer, flow.max_ticks)
        self.flow = flow
        self.hub = flow.hub()
        self.menu_input = MenuInput()
        self.ui = UiLayer(GlyphAtlas(), self.surface)
        self._keys = KeyLatch()
        self._key_actions: list[MenuAction] = []
        self._clicks: list[tuple[int, int]] = []
        self.world = flow.world()
        """The Isle: the piece of the game's world the scene is drawn on (decision D-072)."""
        if not self.hub.connected(flow.active_device):
            flow.active_device = KEYBOARD_DEVICE
        self._footer_template = ""
        self._footer_drop: tuple[str, ...] = ()
        self._footer_shown: tuple[str, str, str] | None = None
        self._footer: PromptBar | None = None
        self._notice_band: arcade.Sprite | None = None
        self._notice = ""
        self._notice_ticks = 0
        self._notice_warning = True

    @property
    def active_device(self) -> str:
        """The device that acted last: the footer shows its controls. It is kept by the
        flow, so the next screen starts with it (decision D-062)."""
        return self.flow.active_device

    @active_device.setter
    def active_device(self, device: str) -> None:
        self.flow.active_device = device

    def pointer_device(self) -> str:
        """Return the device Enter, Escape and the mouse act as: the keyboard layout in
        use (the active device if it is a keyboard, else the first one a player slot
        remembers, else the WASD keyboard). Scenes with player slots override this."""
        if self.active_device.startswith(KEYBOARD_PREFIX):
            return self.active_device
        for device in self.flow.settings.slot_devices:
            if device.startswith(KEYBOARD_PREFIX) and self.hub.connected(device):
                return device
        return KEYBOARD_DEVICE

    def poll(self) -> dict[str, InputFrame]:
        """Return this tick's input from every usable device, by device id. Scenes that
        must ignore some keys (character select) override this."""
        return self.hub.frames(self._keys.keys())

    def notify(self, text: str, ticks: int = NOTICE_TICKS, warning: bool = True) -> None:
        """Show a one-line message in the bottom band, in place of the footer, for about
        three seconds ("" takes it away at once): in the danger colours for a ``warning``,
        in gold on the footer's own strip for news (a player joined)."""
        self._notice = font.fit(text.upper(), NATIVE_W - 2 * theme.PAD) if text else ""
        self._notice_ticks = ticks if text else 0
        self._notice_warning = warning

    @property
    def notice_shown(self) -> str:
        """The message the bottom band is showing ("" for the footer)."""
        return self._notice if self._notice_ticks > 0 else ""

    @property
    def notice_rect(self) -> Rect:
        """The band a message is shown in: the footer's strip."""
        return Rect(0, 0, NATIVE_W, theme.FOOTER_HEIGHT)

    def header(self, text: str, icon: str | None = None) -> None:
        """Add the screen's title at the top left: the logo's lettering, standing on the
        sky like a sign, with its icon on a small block (decision D-072; it was a dark bar
        across the screen)."""
        band = Rect(0, NATIVE_H - theme.HEADER_HEIGHT, NATIVE_W, theme.HEADER_HEIGHT)
        left = theme.MARGIN
        if icon is not None and icon_image(icon) is not None:
            side = theme.ICON_SIZE + 6
            block = Rect(left, band.bottom + (band.height - side - theme.LIP) // 2, side, side)
            self.ui.picture(
                ("title-icon-block", side),
                lambda: kit_art.block_button(side, side + theme.LIP, surface=theme.STONE),
                block.left,
                block.bottom,
            )
            self.ui.icon(icon, block.left + 3, block.bottom + theme.LIP + 3, theme.INK)
            left += side + theme.GAP + 2
        caption = text.upper()
        title = logo.build_title(caption)
        self.title = caption
        """The screen's title, as shown."""
        self.ui.picture(
            ("title", caption),
            lambda: title,
            left,
            band.bottom + (band.height - title.height) // 2,
        )

    def footer(self, template: str, drop: tuple[str, ...] = ()) -> None:
        """Set the prompts along the bottom. ``{attack}``, ``{special}``, ``{grab}``,
        ``{stick}`` and the other action names are replaced by the real controls of the
        device that acted last, each drawn as a key cap (or a gamepad button) with its
        words beside it (decision D-072). The line is measured: if it is wider than the
        screen its items named in ``drop`` go first (see
        :func:`isofightr.ui.hints.fit_hint`)."""
        self._footer_template = template
        self._footer_drop = drop
        if self._footer is None:
            strip = Rect(0, 0, NATIVE_W, theme.FOOTER_HEIGHT)
            self._footer = PromptBar(self.ui, strip, theme.STONE)
            self._notice_band = self.ui.picture(
                ("notice-band", NATIVE_W),
                lambda: kit_art.filled(
                    kit_art.shape_mask(NATIVE_W, theme.FOOTER_HEIGHT, 0),
                    theme.DANGER_FILL,
                    theme.DANGER_BORDER,
                ),
                0,
                0,
            )
            self._notice_band.visible = False
        self._footer_shown = None
        self._sync_footer()

    def _sync_footer(self) -> None:
        """Show the message if there is one, else the footer in the active device's keys."""
        if self._footer is None:
            return
        notice = self.notice_shown
        warning = bool(notice) and self._notice_warning
        shown = (self._footer_template, self.active_device, notice + ("!" if warning else ""))
        if shown == self._footer_shown:
            return
        self._footer_shown = shown
        if self._notice_band is not None:
            self._notice_band.visible = warning
        if notice:
            # A message: plain text, white on the red band for a warning, else in the
            # ledge's accent colour.
            self._footer.set(notice, False, theme.WHITE if warning else theme.STONE.accent)
            return
        labels = device_labels(self.flow.settings, self.active_device)
        width = NATIVE_W - 2 * theme.PAD
        line = fit_hint(self._footer_template, labels, width, self._footer_drop)
        self._footer.set(line, is_pad(self.active_device))

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys; Enter and Escape confirm and go back."""
        self._keys.press(symbol)
        if symbol == KEY_CONFIRM:
            self._key_actions.append(MenuAction.CONFIRM)
        elif symbol == KEY_BACK:
            self._key_actions.append(MenuAction.BACK)
        elif symbol == KEY_NEXT_TAB:
            self._key_actions.append(MenuAction.NEXT_TAB)

    # --- mouse (an extra: everything also works without it) --------------------------------

    def native_point(self, x: float, y: float) -> tuple[int, int] | None:
        """Return the native pixel under a window position, or ``None`` on the letterbox."""
        return window_to_native(x, y, self.window_viewport(), self.window.get_pixel_ratio())

    def on_mouse_motion(self, x: int, y: int, dx: int, dy: int) -> None:
        """Moving the mouse moves the cursor to whatever it is over."""
        spot = self.native_point(x, y)
        if spot is not None:
            self.hover(*spot)

    def on_mouse_press(self, x: int, y: int, button: int, modifiers: int) -> None:
        """A left click confirms what is under the mouse; a right click goes back. Both act
        on the next tick, as the keyboard, so they are handled in one place."""
        spot = self.native_point(x, y)
        if button == MOUSE_RIGHT:
            self._key_actions.append(MenuAction.BACK)
        elif button == MOUSE_LEFT and spot is not None:
            self._clicks.append(spot)

    def hover(self, x: int, y: int) -> bool:
        """Move the cursor to the thing at a native pixel. Returns whether there is one (a
        click only confirms then). Override in scenes."""
        return False

    def click(self, x: int, y: int) -> None:
        """Handle a left click at a native pixel: by default, confirm whatever is there.
        Scenes whose widgets care where they are clicked (steppers) override this."""
        if self.hover(x, y):
            self.audio.play(MENU_SOUNDS[MenuAction.CONFIRM])
            self.act(self.pointer_device(), MenuAction.CONFIRM)

    def on_key_release(self, symbol: int, modifiers: int) -> None:
        """Stop tracking a released key."""
        self._keys.release(symbol)

    music = AUDIO_MENU_SONG
    """The song a menu scene plays (it carries on from scene to scene)."""
    music_loops = True

    station: ClassVar[str] = "plaza"
    """The framing of the Isle the scene is shown at: the camera glides there when the
    scene opens (see :mod:`isofightr.scenes.menu_world_model`)."""

    def on_show_view(self) -> None:
        """Start (or keep) the scene's music, and send the camera to the scene's station
        (with a soft whoosh when it sets off, unless the cloud covers the change)."""
        self.audio.play_music(self.music, self.music_loops)
        before = self.world.station
        self.world.go(self.station)
        if self.world.station is not before and not self.wiping:
            self.audio.play(UI_GLIDE)

    def tick(self) -> None:
        """Hand this tick's menu actions to :meth:`act`, then refresh the text."""
        frames = self.poll()
        self._keys.end_tick()
        devices = list(frames)
        extras = self.hub.menu_extras(devices)
        self.hub.end_tick()
        fired = self.menu_input.update([frames[device] for device in devices], extras)
        self.flow.menu_ticks += 1
        self.world.tick()
        if self._notice_ticks > 0:
            self._notice_ticks -= 1
        for action in self._key_actions:
            if self.window.current_view is self:
                if MENU_SOUNDS[action]:
                    self.audio.play(MENU_SOUNDS[action])
                device = self.pointer_device()
                self.active_device = device
                self.act(device, action)
        self._key_actions = []
        for spot in self._clicks:
            if self.window.current_view is self:
                self.active_device = self.pointer_device()
                self.click(*spot)
        self._clicks = []
        for device, actions in zip(devices, fired, strict=True):
            for action in MenuAction:
                if action in actions and self.window.current_view is self:
                    if MENU_SOUNDS[action]:
                        self.audio.play(MENU_SOUNDS[action])
                    self.active_device = device
                    self.act(device, action)
        if self.window.current_view is self:
            self._sync_footer()
            self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Handle one menu action from one device. Override in scenes."""

    def refresh(self) -> None:
        """Update labels from the scene's state. Override in scenes."""

    def draw_under(self) -> None:
        """Draw what the scene puts between the world and its own layer. Override."""

    def draw_over(self) -> None:
        """Draw what the scene puts over its own layer. Override."""

    def on_draw(self) -> None:
        """Draw the Isle, then the scene over it, at native resolution; then upscale it to
        the window."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            settings = self.flow.settings
            self.world.apply_settings(settings.reduce_flashing, settings.depth_aids)
            self.world.draw()
            self.draw_under()
            self.ui.draw()
            self.draw_over()
            self.draw_fade()
        self.blit_to_window()


class ListRows:
    """The rows of a list menu, drawn with the UI kit (decision D-061): a strip per row, lit
    under the cursor, with the row's icon and name on the left and, for a setting, its value
    on the right: a switch for an on/off row, a ``< value >`` stepper for the others, and a
    bar as well for a volume."""

    def __init__(
        self,
        layer: UiLayer,
        menu: Menu,
        left: int,
        top: int,
        width: int,
        icons: dict[str, str] | None = None,
        bars: dict[str, int] | None = None,
        danger: tuple[str, ...] = (),
        opens: tuple[str, ...] = (),
        row_height: int = theme.ROW_HEIGHT,
    ) -> None:
        """Lay the rows out hanging down from ``top``. ``icons`` gives a row's icon by its
        key; ``bars`` the top value of a row that also shows a bar; ``danger`` the rows that
        overwrite things; ``opens`` the rows that lead to another screen (they end in an
        arrow). On the stone surface (decision D-072) a row is a pale well, gold under the
        cursor, its name in the title face."""
        self.left, self.top, self.width = left, top, width
        self.strip_height = row_height
        self.row_height = row_height + LIST_ROW_GAP
        self.surface = layer.surface
        stone = self.surface is theme.STONE
        self.menu = menu
        self.bars = bars or {}
        self.danger = danger
        self._strips: list[Picture] = []
        self._labels: list[TextLabel] = []
        self._steppers: dict[str, Stepper] = {}
        self._switches: dict[str, Toggle] = {}
        self._gauges: dict[str, Gauge] = {}
        self._arrows: dict[str, Picture] = {}
        for index, item in enumerate(menu.items):
            rect = self.rect(index)
            self._strips.append(Picture(layer, rect))
            icon = (icons or {}).get(item.key)
            middle = rect.bottom + (rect.height - theme.ICON_SIZE) // 2
            if icon is not None:
                layer.icon(icon, rect.left + theme.GAP, middle, self.surface.text_muted)
            box = Rect(rect.left + theme.ICON_SIZE + theme.GAP, rect.bottom, 200, rect.height)
            if stone:
                label = layer.write_in(box, item.label, TextSize.TITLE, align="left", shadow=False)
            else:
                label = layer.write_in(box, item.label.upper(), align="left")
            self._labels.append(label)
            inset = 3 if stone else 1
            well = Rect(rect.right - LIST_VALUE_WIDTH - theme.GAP, rect.bottom + inset,
                        LIST_VALUE_WIDTH, rect.height - 2 * inset)  # fmt: skip
            if item.key in opens:
                arrow = Rect(well.right - theme.ICON_SIZE - 2, rect.bottom + 3, theme.ICON_SIZE,
                             theme.ICON_SIZE)  # fmt: skip
                self._arrows[item.key] = Picture(layer, arrow)
            elif item.choices == ON_OFF:
                switch = Rect(well.right - LIST_SWITCH_WIDTH, well.bottom, LIST_SWITCH_WIDTH,
                              well.height)  # fmt: skip
                self._switches[item.key] = Toggle(layer, switch, block=stone)
            elif item.choices:
                self._steppers[item.key] = Stepper(layer, well)
                if item.key in self.bars:
                    bar = Rect(well.left - LIST_BAR_WIDTH - theme.PAD,
                               rect.bottom + (rect.height - 9) // 2, LIST_BAR_WIDTH, 9)  # fmt: skip
                    self._gauges[item.key] = Gauge(layer, bar, segmented=True)

    def rect(self, index: int) -> Rect:
        """Return a row's strip."""
        bottom = self.top - (index + 1) * self.row_height + LIST_ROW_GAP
        return Rect(self.left, bottom, self.width, self.strip_height)

    def row_at(self, x: float, y: float) -> int | None:
        """Return the row under a native pixel, or ``None``."""
        if not self.left <= x < self.left + self.width or y > self.top:
            return None
        row = int((self.top - y) // self.row_height)
        return row if 0 <= row < len(self.menu.items) else None

    def refresh(self) -> None:
        """Show the rows as the menu has them now."""
        surface = self.surface
        stone = surface is theme.STONE
        for index, item in enumerate(self.menu.items):
            focused = index == self.menu.cursor
            rect = self.rect(index)
            danger = item.key in self.danger
            # A row that overwrites things is quiet until the cursor is on it, then red.
            look = kit_art.Look.DANGER if focused else kit_art.Look.CAUTION

            def strip(
                rect: Rect = rect,
                focused: bool = focused,
                danger: bool = danger,
                look: kit_art.Look = look,
            ) -> Image.Image:
                if danger:
                    if stone:
                        return kit_art.block_button(rect.width, rect.height, look, surface)
                    return kit_art.button(rect.width, rect.height, look)
                if stone:
                    return kit_art.row_strip(rect.width, rect.height, focused, surface)
                return kit_art.list_row(rect.width, rect.height, focused)

            self._strips[index].show(
                ("list-row", rect.width, rect.height, focused, danger, surface.name), strip
            )
            if danger:
                self._labels[index].color = kit_art.look_text(look, surface)
            elif stone:
                self._labels[index].color = theme.INK if focused else surface.text
            else:
                self._labels[index].color = theme.FOCUS if focused else theme.TEXT
            if item.key in self._arrows:
                if stone:
                    color = theme.INK if focused else surface.text_muted
                else:
                    color = theme.FOCUS if focused else theme.TEXT_DIM
                image = icon_image("arrow_right")
                if image is not None:
                    self._arrows[item.key].show(
                        ("icon", "arrow_right", color),
                        lambda image=image, color=color: kit_art.tint(image, color),
                    )
            if item.key in self._switches:
                self._switches[item.key].set(bool(item.index), focused)
            elif item.key in self._steppers:
                self._steppers[item.key].set(item.value.upper(), focused)
            if item.key in self._gauges:
                self._gauges[item.key].value = item.index / max(self.bars[item.key], 1)


class MenuListView(MenuView):
    """A scene that is one vertical menu on a panel, shared by every device."""

    icons: ClassVar[dict[str, str]] = {}
    """A row's icon, by its key."""
    bars: ClassVar[dict[str, int]] = {}
    """The top value of a row that also shows a bar (volumes), by its key."""
    danger: tuple[str, ...] = ()
    opens: tuple[str, ...] = ()
    """The rows that lead to another screen: they end in an arrow."""
    help: ClassVar[dict[str, str]] = {}
    """A line about a row, shown under the list while the cursor is on it."""
    list_left: ClassVar[int | None] = None
    """Where the list's slab starts (``None``: centred on the screen)."""
    list_width: ClassVar[int] = LIST_WIDTH
    row_height: ClassVar[int] = theme.ROW_HEIGHT

    def make_header(self, title: str, icon: str | None) -> None:
        """Draw the title band. Screens that are a tab of the options draw their tabs
        instead."""
        self.header(title, icon)

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        flow: GameFlow,
        title: str,
        menu: Menu,
        icon: str | None = None,
    ) -> None:
        """Build the title bar, the panel and the menu's rows."""
        super().__init__(pixel_buffer, flow)
        self.menu = menu
        self.make_header(title, icon)
        stone = self.surface is theme.STONE
        row_height = self.row_height + LIST_ROW_GAP
        lip = theme.LIP if stone else 0
        height = len(menu.items) * row_height + 2 * theme.GAP + lip
        top = NATIVE_H - theme.HEADER_HEIGHT - LIST_TOP_GAP
        width = self.list_width
        left = (NATIVE_W - width) // 2 if self.list_left is None else self.list_left
        panel = Rect(left, top - height, width, height)
        if stone:
            add_slab(self.ui, panel)
        else:
            add_panel(self.ui, panel)
        self.rows = ListRows(
            self.ui,
            menu,
            panel.left + theme.GAP,
            panel.top - theme.GAP,
            panel.width - 2 * theme.GAP,
            self.icons,
            self.bars,
            self.danger,
            self.opens,
            self.row_height,
        )
        strip = Rect(panel.left, panel.bottom - LIST_HELP_HEIGHT - theme.GAP, panel.width,
                     LIST_HELP_HEIGHT)  # fmt: skip
        self.help_rect = strip
        """The strip the line about the row under the cursor sits on."""
        self.help_sign: Sign | None = None
        if stone:
            self.help_sign = Sign(self.ui, strip)
            self.help_label = self.help_sign.label
        else:
            self.ui.picture(
                ("list-help", strip.width, strip.height),
                lambda: kit_art.panel(
                    strip.width, strip.height, theme.PANEL_DEEP, theme.PANEL_LIGHT,
                    theme.SMALL_CORNER,
                ),
                strip.left,
                strip.bottom,
            )  # fmt: skip
            self.help_label = self.ui.write_in(strip, "", TextSize.BODY, theme.FOG)
        self.refresh()

    def act(self, device: str, action: MenuAction) -> None:
        """Navigate; hand confirmed items to :meth:`choose` and back to :meth:`back`."""
        if action is MenuAction.BACK:
            self.back()
            return
        before = [item.index for item in self.menu.items]
        chosen = self.menu.apply(action)
        if chosen is not None:
            self.choose(chosen)
        elif before != [item.index for item in self.menu.items]:
            self.changed()

    def choose(self, key: str) -> None:
        """An action item was confirmed. Override in scenes."""

    def changed(self) -> None:
        """A setting changed. Override in scenes."""

    def back(self) -> None:
        """Back was pressed. Override in scenes."""

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the row under the mouse."""
        row = self.rows.row_at(x, y)
        if row is None or row >= len(self.menu.items):
            return False
        self.menu.cursor = row
        return True

    def refresh(self) -> None:
        """Show the menu rows and the line about the one under the cursor."""
        self.rows.refresh()
        line = self.help.get(self.menu.selected.key, "")
        if self.help_sign is not None:
            self.help_sign.text = line
        else:
            self.help_label.text = line


SETTINGS_PAGES: dict[str, tuple[str, ...]] = {
    "display": ("scale", "fullscreen", "camera_zoom"),
    "sound": ("master_volume", "music_volume", "sfx_volume", "sound_test"),
    "feel": ("screen_shake", "reduce_flashing", "depth_aids", "hit_effects"),
}
"""The settings each page shows (decision D-072: a few rows each, not fourteen)."""
SETTING_FIELDS: dict[str, str] = {
    "scale": "scale",
    "fullscreen": "fullscreen",
    "camera_zoom": "camera_zoom",
    "master_volume": "master_volume",
    "music_volume": "music_volume",
    "sfx_volume": "sfx_volume",
    "screen_shake": "screen_shake",
    "reduce_flashing": "reduce_flashing",
    "depth_aids": "depth_aids",
    "hit_effects": "hit_effects",
}
"""The ``Settings`` field each row sets."""
SHAKE_DEMO_PIXELS = 5
"""How far the Isle shakes, at 100%, when the screen shake setting changes."""


class SettingsView(MenuListView):
    """One page of the settings, a tab of the options: Display, Sound or Feel. Every change
    is applied and saved at once; each page's reset puts back that page only."""

    station = "workshop"
    surface = theme.STONE
    list_left = theme.MARGIN + 8
    list_width = 340
    row_height = theme.ROW_TALL

    icons: ClassVar[dict[str, str]] = {
        "scale": "hud",
        "fullscreen": "hud",
        "screen_shake": "burst",
        "master_volume": "speaker",
        "music_volume": "speaker",
        "sfx_volume": "speaker",
        "sound_test": "speaker",
        "camera_zoom": "stage",
        "reduce_flashing": "shield",
        "depth_aids": "fall",
        "hit_effects": "burst",
        "defaults": "cross",
        "back": "arrow_left",
    }
    bars: ClassVar[dict[str, int]] = {
        "master_volume": VOLUME_MAX,
        "music_volume": VOLUME_MAX,
        "sfx_volume": VOLUME_MAX,
    }
    danger = ("defaults",)
    opens = ("sound_test",)
    help: ClassVar[dict[str, str]] = {
        "scale": "How many screen pixels each game pixel covers.",
        "fullscreen": "Fill the screen, keeping whole pixels.",
        "screen_shake": "How hard big hits shake the picture.",
        "master_volume": "Everything.",
        "music_volume": "The songs.",
        "sfx_volume": "Hits, swings and menu blips.",
        "sound_test": "Listen to every song and sound in the game.",
        "camera_zoom": "Stepped: the camera doubles when everyone is close.",
        "reduce_flashing": "No hit flashes, no screen shake, no pulsing clock.",
        "depth_aids": "A ring and a line show where a fighter is. Strong adds a grid.",
        "hit_effects": "How hits look. Minimal has no particles; off is the old spark.",
        "defaults": "This page's settings back to how they came.",
        "back": "Back to the main menu.",
    }

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, tab: str = "display") -> None:
        """Build the page's rows from the current settings."""
        self.tab = tab if tab in SETTINGS_PAGES else "display"
        settings = flow.settings
        volumes = tuple(str(level) for level in range(VOLUME_MAX + 1))
        rows = {
            "scale": _setting(
                "scale", "Window scale", [f"{scale}x" for scale in SCALES], SCALES, settings.scale
            ),
            "fullscreen": MenuItem("fullscreen", "Fullscreen", ON_OFF, int(settings.fullscreen)),
            "screen_shake": _setting(
                "screen_shake",
                "Screen shake",
                [f"{step}%" for step in SHAKE_STEPS],
                SHAKE_STEPS,
                settings.screen_shake,
            ),
            "master_volume": MenuItem(
                "master_volume", "Master volume", volumes, settings.master_volume
            ),
            "music_volume": MenuItem(
                "music_volume", "Music volume", volumes, settings.music_volume
            ),
            "sfx_volume": MenuItem("sfx_volume", "Effects volume", volumes, settings.sfx_volume),
            "sound_test": MenuItem("sound_test", "Sound test"),
            "camera_zoom": _setting(
                "camera_zoom",
                "Camera zoom",
                ["static", "stepped 2x"],
                CAMERA_ZOOMS,
                settings.camera_zoom,
            ),
            "reduce_flashing": MenuItem(
                "reduce_flashing", "Reduce flashing", ON_OFF, int(settings.reduce_flashing)
            ),
            "depth_aids": _setting(
                "depth_aids", "Depth aids", list(DEPTH_AIDS), DEPTH_AIDS, settings.depth_aids
            ),
            "hit_effects": _setting(
                "hit_effects", "Hit effects", list(HIT_EFFECTS), HIT_EFFECTS, settings.hit_effects
            ),
        }
        menu = Menu(
            [
                *(rows[key] for key in SETTINGS_PAGES[self.tab]),
                MenuItem("defaults", "Reset this page"),
                MenuItem("back", "Back"),
            ]
        )
        super().__init__(pixel_buffer, flow, "SETTINGS", menu, "gear")
        self.footer(
            "{stick}: row and value   {attack}: pick   {tabs}: next tab   {special}: back",
            drop=("tabs",),
        )

    def make_header(self, title: str, icon: str | None) -> None:
        """The options' strip of tabs, this page's tab on show."""
        from isofightr.scenes.options_view import add_option_tabs

        add_option_tabs(self, self.tab)

    def act(self, device: str, action: MenuAction) -> None:
        """The tab buttons step through the options; the rest is the list's."""
        from isofightr.scenes.options_view import option_tab_action

        if option_tab_action(self, action):
            return
        super().act(device, action)

    def click(self, x: int, y: int) -> None:
        """A click on a tab opens it; elsewhere it is the list's."""
        from isofightr.scenes.options_view import option_tab_click

        if option_tab_click(self, x, y):
            return
        super().click(x, y)

    def changed(self) -> None:
        """Apply and save the rows that changed; a change of screen shake shakes the Isle
        by that much, so the setting can be felt."""
        before = self.flow.settings
        values = {
            SETTING_FIELDS[item.key]: self._value(item.key)
            for item in self.menu.items
            if item.key in SETTING_FIELDS
        }
        self.flow.update_settings(replace(before, **values))
        after = self.flow.settings
        if after.screen_shake != before.screen_shake:
            self.world.shake(round(SHAKE_DEMO_PIXELS * after.screen_shake / 100))

    def _value(self, key: str) -> object:
        """Return the value a row stands for now."""
        index = self.menu.item(key).index
        if key == "scale":
            return SCALES[index]
        if key == "screen_shake":
            return SHAKE_STEPS[index]
        if key == "camera_zoom":
            return CAMERA_ZOOMS[index]
        if key == "depth_aids":
            return DEPTH_AIDS[index]
        if key == "hit_effects":
            return HIT_EFFECTS[index]
        if key in ("fullscreen", "reduce_flashing"):
            return bool(index)
        return index

    def choose(self, key: str) -> None:
        """Open the sound test, reset this page, or leave."""
        if key == "sound_test":
            self.flow.show_sound_test()
        elif key == "defaults":
            fresh = Settings()
            fields = {
                SETTING_FIELDS[name]: getattr(fresh, SETTING_FIELDS[name])
                for name in SETTINGS_PAGES[self.tab]
                if name in SETTING_FIELDS
            }
            self.flow.update_settings(replace(self.flow.settings, **fields))
            self.flow.show_settings(self.tab)
        else:
            self.back()

    def back(self) -> None:
        """Leave the options for the main menu."""
        self.flow.show_main_menu()


def _setting[T](
    key: str, label: str, names: list[str], values: tuple[T, ...], value: T
) -> MenuItem:
    """Return a setting row whose choices stand for ``values``, with ``value`` selected."""
    index = values.index(value) if value in values else 0
    return MenuItem(key, label, tuple(names), index)
