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

from isofightr.config import (
    AUDIO_MENU_SONG,
    NATIVE_H,
    NATIVE_W,
)
from isofightr.input.devices import KEYBOARD_PREFIX
from isofightr.input.keyboard import KeyLatch
from isofightr.render import placeholder_art as art
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.pixel_scale import window_to_native
from isofightr.scenes.ticked_view import TickedView
from isofightr.settings import (
    CAMERA_ZOOMS,
    KEYBOARD_SOLO,
    SCALES,
    SHAKE_STEPS,
    VOLUME_MAX,
    Settings,
)
from isofightr.sim.input_frame import InputFrame
from isofightr.ui import font, kit_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize
from isofightr.ui.hints import device_labels, fit_hint
from isofightr.ui.menu import MENU_SOUNDS, Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import (
    Gauge,
    Picture,
    Stepper,
    TextLabel,
    Toggle,
    UiLayer,
    add_panel,
    picture_texture,
    text_bottom,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

KEY_CONFIRM = arcade.key.ENTER
KEY_BACK = arcade.key.ESCAPE
KEYBOARD_DEVICE = KEYBOARD_PREFIX + KEYBOARD_SOLO
"""The device Enter and Escape act as."""
MOUSE_LEFT = arcade.MOUSE_BUTTON_LEFT
MOUSE_RIGHT = arcade.MOUSE_BUTTON_RIGHT
FADE_TICKS = 10
NOTICE_TICKS = 180
"""How long a message stays in the bottom band (about three seconds)."""
"""A scene fades in from black over this many ticks."""
ON_OFF = ("off", "on")
LIST_WIDTH = 400
"""Width of a list menu's panel."""
LIST_ROW_GAP = 2
LIST_TOP_GAP = 10
LIST_VALUE_WIDTH = 96
"""Width of the well a row's value sits in."""
LIST_SWITCH_WIDTH = 44
LIST_BAR_WIDTH = 70
LIST_HELP_HEIGHT = 18


class MenuView(TickedView):
    """Base of the menu scenes: polls every device each tick and draws one UI layer."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Create an empty scene with its own input devices."""
        super().__init__(pixel_buffer, flow.max_ticks)
        self.flow = flow
        self.hub = flow.hub()
        self.menu_input = MenuInput()
        self.ui = UiLayer(GlyphAtlas())
        self._keys = KeyLatch()
        self._key_actions: list[MenuAction] = []
        self._clicks: list[tuple[int, int]] = []
        self.fade_ticks = FADE_TICKS
        self.backdrop = flow.backdrop()
        self.dim: arcade.SpriteList[arcade.Sprite] | None = arcade.SpriteList()
        """A veil over the backdrop so plain text reads on it; ``None`` for scenes that
        put their text on panels."""
        self.dim.append(
            arcade.Sprite(
                picture_texture(
                    ("dim", NATIVE_W, NATIVE_H),
                    lambda: art.build_panel(
                        NATIVE_W, NATIVE_H, theme.DIM_OVERLAY, theme.DIM_OVERLAY
                    ),
                ),
                center_x=NATIVE_W / 2,
                center_y=NATIVE_H / 2,
            )
        )
        if not self.hub.connected(flow.active_device):
            flow.active_device = KEYBOARD_DEVICE
        self._footer_template = ""
        self._footer_drop: tuple[str, ...] = ()
        self._footer_shown: tuple[str, str, str] | None = None
        self._footer: TextLabel | None = None
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
        """Add the title bar across the top of a rebuilt screen (decision D-061)."""
        bar = Rect(0, NATIVE_H - theme.HEADER_HEIGHT, NATIVE_W, theme.HEADER_HEIGHT)
        self.ui.picture(
            ("header", NATIVE_W),
            lambda: art.build_panel(bar.width, bar.height, theme.PANEL_DEEP, theme.PANEL_DEEP),
            bar.left,
            bar.bottom,
        )
        self.ui.picture(("header-rule", NATIVE_W), lambda: kit_art.divider(NATIVE_W), 0, bar.bottom)
        left = theme.MARGIN
        if icon is not None and self.ui.icon(icon, left, bar.bottom + 8, theme.HEADING):
            left += theme.ICON_SIZE + theme.GAP + 2
        self.ui.write(
            text, left, text_bottom(bar, TextSize.DISPLAY), TextSize.DISPLAY, theme.HEADING
        )

    def footer(self, template: str, drop: tuple[str, ...] = ()) -> None:
        """Set the hint line at the bottom. ``{attack}``, ``{special}``, ``{grab}``,
        ``{stick}`` and the other action names are replaced by the real controls of the
        device that acted last. The line is measured: if it is wider than the screen its
        items named in ``drop`` go first (see :func:`isofightr.ui.hints.fit_hint`)."""
        self._footer_template = template
        self._footer_drop = drop
        if self._footer is None:
            strip = Rect(0, 0, NATIVE_W, theme.FOOTER_HEIGHT)
            self.ui.picture(
                ("footer", NATIVE_W),
                lambda: art.build_panel(
                    NATIVE_W, theme.FOOTER_HEIGHT, theme.PANEL_DEEP, theme.PANEL_DEEP
                ),
                0,
                0,
            )
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
            self._footer = self.ui.write_in(strip, "", TextSize.BODY, theme.TEXT_MUTED)
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
        self._footer.color = theme.TEXT if warning else theme.FOCUS if notice else theme.TEXT_MUTED
        if notice:
            self._footer.text = notice
            return
        labels = device_labels(self.flow.settings, self.active_device)
        width = NATIVE_W - 2 * theme.PAD
        self._footer.text = fit_hint(self._footer_template, labels, width, self._footer_drop)

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys; Enter and Escape confirm and go back."""
        self._keys.press(symbol)
        if symbol == KEY_CONFIRM:
            self._key_actions.append(MenuAction.CONFIRM)
        elif symbol == KEY_BACK:
            self._key_actions.append(MenuAction.BACK)

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

    def on_show_view(self) -> None:
        """Start (or keep) the scene's music."""
        self.audio.play_music(self.music, self.music_loops)

    def tick(self) -> None:
        """Hand this tick's menu actions to :meth:`act`, then refresh the text."""
        frames = self.poll()
        self._keys.end_tick()
        devices = list(frames)
        extras = self.hub.menu_extras(devices)
        self.hub.end_tick()
        fired = self.menu_input.update([frames[device] for device in devices], extras)
        self.flow.menu_ticks += 1
        if self._notice_ticks > 0:
            self._notice_ticks -= 1
        for action in self._key_actions:
            if self.window.current_view is self:
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

    def on_draw(self) -> None:
        """Draw the scene at native resolution, then upscale it to the window."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            self.backdrop.draw(self.flow.menu_ticks)
            if self.dim is not None:
                self.dim.draw(pixelated=True)
            self.ui.draw()
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
    ) -> None:
        """Lay the rows out hanging down from ``top``. ``icons`` gives a row's icon by its
        key; ``bars`` the top value of a row that also shows a bar; ``danger`` the rows that
        overwrite things."""
        self.left, self.top, self.width = left, top, width
        self.row_height = theme.ROW_HEIGHT + LIST_ROW_GAP
        self.menu = menu
        self.bars = bars or {}
        self.danger = danger
        self._strips: list[Picture] = []
        self._labels: list[TextLabel] = []
        self._steppers: dict[str, Stepper] = {}
        self._switches: dict[str, Toggle] = {}
        self._gauges: dict[str, Gauge] = {}
        for index, item in enumerate(menu.items):
            rect = self.rect(index)
            self._strips.append(Picture(layer, rect))
            icon = (icons or {}).get(item.key)
            if icon is not None:
                layer.icon(icon, rect.left + theme.GAP, rect.bottom + 3, theme.TEXT_MUTED)
            box = Rect(rect.left + theme.ICON_SIZE + theme.GAP, rect.bottom, 200, rect.height)
            self._labels.append(layer.write_in(box, item.label.upper(), align="left"))
            well = Rect(rect.right - LIST_VALUE_WIDTH - theme.GAP, rect.bottom + 1,
                        LIST_VALUE_WIDTH, rect.height - 2)  # fmt: skip
            if item.choices == ON_OFF:
                switch = Rect(well.right - LIST_SWITCH_WIDTH, well.bottom, LIST_SWITCH_WIDTH,
                              well.height)  # fmt: skip
                self._switches[item.key] = Toggle(layer, switch)
            elif item.choices:
                self._steppers[item.key] = Stepper(layer, well)
                if item.key in self.bars:
                    bar = Rect(well.left - LIST_BAR_WIDTH - theme.PAD, rect.bottom + 5,
                               LIST_BAR_WIDTH, rect.height - 10)  # fmt: skip
                    self._gauges[item.key] = Gauge(layer, bar, segmented=True)

    def rect(self, index: int) -> Rect:
        """Return a row's strip."""
        bottom = self.top - (index + 1) * self.row_height + LIST_ROW_GAP
        return Rect(self.left, bottom, self.width, theme.ROW_HEIGHT)

    def row_at(self, x: float, y: float) -> int | None:
        """Return the row under a native pixel, or ``None``."""
        if not self.left <= x < self.left + self.width or y > self.top:
            return None
        row = int((self.top - y) // self.row_height)
        return row if 0 <= row < len(self.menu.items) else None

    def refresh(self) -> None:
        """Show the rows as the menu has them now."""
        for index, item in enumerate(self.menu.items):
            focused = index == self.menu.cursor
            rect = self.rect(index)
            danger = item.key in self.danger and not focused
            self._strips[index].show(
                ("list-row", rect.width, rect.height, focused, danger),
                lambda rect=rect, focused=focused, danger=danger: (
                    kit_art.button(rect.width, rect.height, kit_art.Look.DANGER)
                    if danger
                    else kit_art.list_row(rect.width, rect.height, focused)
                ),
            )
            self._labels[index].color = theme.FOCUS if focused else theme.TEXT
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
    help: ClassVar[dict[str, str]] = {}
    """A line about a row, shown under the list while the cursor is on it."""

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
        self.dim = None
        self.menu = menu
        self.header(title, icon)
        row_height = theme.ROW_HEIGHT + LIST_ROW_GAP
        height = len(menu.items) * row_height + 2 * theme.GAP
        top = NATIVE_H - theme.HEADER_HEIGHT - LIST_TOP_GAP
        panel = Rect((NATIVE_W - LIST_WIDTH) // 2, top - height, LIST_WIDTH, height)
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
        )
        strip = Rect(panel.left, panel.bottom - LIST_HELP_HEIGHT - theme.GAP, panel.width,
                     LIST_HELP_HEIGHT)  # fmt: skip
        self.ui.picture(
            ("list-help", strip.width, strip.height),
            lambda: kit_art.panel(
                strip.width, strip.height, theme.PANEL_DEEP, theme.PANEL_LIGHT, theme.SMALL_CORNER
            ),
            strip.left,
            strip.bottom,
        )
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
        self.help_label.text = self.help.get(self.menu.selected.key, "")


class SettingsView(MenuListView):
    """Video, audio and control settings. Every change is applied and saved at once."""

    icons: ClassVar[dict[str, str]] = {
        "scale": "hud",
        "fullscreen": "hud",
        "screen_shake": "burst",
        "master_volume": "speaker",
        "music_volume": "speaker",
        "sfx_volume": "speaker",
        "controls": "controller",
        "camera_zoom": "stage",
        "reduce_flashing": "shield",
        "defaults": "cross",
        "back": "arrow_left",
    }
    bars: ClassVar[dict[str, int]] = {
        "master_volume": VOLUME_MAX,
        "music_volume": VOLUME_MAX,
        "sfx_volume": VOLUME_MAX,
    }
    danger = ("defaults",)
    help: ClassVar[dict[str, str]] = {
        "scale": "How many screen pixels each game pixel covers.",
        "fullscreen": "Fill the screen, keeping whole pixels.",
        "screen_shake": "How hard big hits shake the picture.",
        "master_volume": "Everything.",
        "music_volume": "The songs.",
        "sfx_volume": "Hits, swings and menu blips.",
        "controls": "Rebind the keyboards and the gamepads.",
        "camera_zoom": "Stepped: the camera doubles when everyone is close.",
        "reduce_flashing": "No hit flashes, no screen shake, no pulsing clock.",
        "defaults": "Video, sound and accessibility back to how they came.",
        "back": "Back to the main menu.",
    }

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Build the rows from the current settings."""
        settings = flow.settings
        volumes = tuple(str(level) for level in range(VOLUME_MAX + 1))
        menu = Menu(
            [
                _setting(
                    "scale",
                    "Window scale",
                    [f"{scale}x" for scale in SCALES],
                    SCALES,
                    settings.scale,
                ),
                MenuItem("fullscreen", "Fullscreen", ON_OFF, int(settings.fullscreen)),
                _setting(
                    "screen_shake",
                    "Screen shake",
                    [f"{step}%" for step in SHAKE_STEPS],
                    SHAKE_STEPS,
                    settings.screen_shake,
                ),
                MenuItem("master_volume", "Master volume", volumes, settings.master_volume),
                MenuItem("music_volume", "Music volume", volumes, settings.music_volume),
                MenuItem("sfx_volume", "Effects volume", volumes, settings.sfx_volume),
                MenuItem("controls", "Controls"),
                _setting(
                    "camera_zoom",
                    "Camera zoom",
                    ["static", "stepped 2x"],
                    CAMERA_ZOOMS,
                    settings.camera_zoom,
                ),
                MenuItem(
                    "reduce_flashing", "Reduce flashing", ON_OFF, int(settings.reduce_flashing)
                ),
                MenuItem("defaults", "Reset to defaults"),
                MenuItem("back", "Back"),
            ]
        )
        super().__init__(pixel_buffer, flow, "SETTINGS", menu, "gear")
        self.footer("{stick}: row and value   {attack}: pick   {special}: back")

    def changed(self) -> None:
        """Apply and save the row that changed."""
        menu = self.menu
        self.flow.update_settings(
            replace(
                self.flow.settings,
                scale=SCALES[menu.item("scale").index],
                fullscreen=bool(menu.item("fullscreen").index),
                screen_shake=SHAKE_STEPS[menu.item("screen_shake").index],
                master_volume=menu.item("master_volume").index,
                music_volume=menu.item("music_volume").index,
                sfx_volume=menu.item("sfx_volume").index,
                camera_zoom=CAMERA_ZOOMS[menu.item("camera_zoom").index],
                reduce_flashing=bool(menu.item("reduce_flashing").index),
            )
        )

    def choose(self, key: str) -> None:
        """Open the controls screen, reset, or leave."""
        if key == "controls":
            self.flow.show_controls(self.flow.show_settings)
        elif key == "defaults":
            # Video, audio and accessibility only: the controls and the rules have their
            # own DEFAULT buttons.
            kept = self.flow.settings
            self.flow.update_settings(
                Settings(
                    slot_devices=kept.slot_devices,
                    rules=kept.rules,
                    keys=kept.keys,
                    alt_keys=kept.alt_keys,
                    pads=kept.pads,
                    deadzone=kept.deadzone,
                )
            )
            self.flow.show_settings()
        else:
            self.back()

    def back(self) -> None:
        """Back to the main menu."""
        self.flow.show_main_menu()


def _setting[T](
    key: str, label: str, names: list[str], values: tuple[T, ...], value: T
) -> MenuItem:
    """Return a setting row whose choices stand for ``values``, with ``value`` selected."""
    index = values.index(value) if value in values else 0
    return MenuItem(key, label, tuple(names), index)
