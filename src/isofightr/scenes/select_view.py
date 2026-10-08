"""The character select screen.

Plan note "13 - Game Modes UI and Flow" ("Character select screen", decision D-061,
wireframe ``m13_wf_charselect.png``): a roster grid at the top with a cursor per player, a
detail strip for the fighter under the cursor, and four player panels along the bottom with
the character's hero art, name, costume swatches and state. Joining, readying, CPUs and
teams work as they always did (see :class:`CharacterSelectView`); what the grid, the
costumes and the stat bars do is in :mod:`isofightr.scenes.roster_model`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import arcade
from PIL import Image

from isofightr.config import (
    CPU_DEFAULT_LEVEL,
    CPU_MAX_LEVEL,
    CPU_MIN_LEVEL,
    MAX_PLAYERS,
    NATIVE_H,
    NATIVE_W,
)
from isofightr.data.character_loader import list_character_ids, load_character
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.render import stage_preview
from isofightr.render.fighter_look import costume_index
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.scenes import roster_model
from isofightr.scenes import select_text as text
from isofightr.scenes.menus import MenuView
from isofightr.scenes.roster_model import RANDOM, RANDOM_ENTRY, STAT_LABELS, STAT_NAMES
from isofightr.scenes.rules_model import rule_chips, with_saved
from isofightr.scenes.setup import TEAM_NAMES, MatchSetup, can_start
from isofightr.sim.input_frame import InputFrame
from isofightr.ui import anim, kit_art, select_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import ARROW_LEFT, ARROW_RIGHT, TextSize
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Button,
    Gauge,
    Picture,
    TextLabel,
    add_panel,
    icon_texture,
    text_bottom,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

ROSTER_FRAME = Rect(8, 238, 310, 88)
ROSTER_TOP = 322
"""Where the roster's first row hangs from when the rows do not fit inside the frame."""
TILE = (46, 46)
"""A roster tile: the 40x40 portrait with a name strip across its foot."""
TILE_GAP = 4
NAME_STRIP = 10
DETAIL = Rect(326, 238, 302, 88)
PANEL_WIDTH = 148
PANEL_GAP = 8
PANEL_LEFT = 12
PANEL_BOTTOM = 20
PANEL_HEIGHT = 214
STRIP_HEIGHT = 16
ART_BOTTOM = 78
"""Height of the hero art's feet (the middle of its isle) above the panel's bottom."""
ISLE_WIDTH = 68
PLATE = (132, 18)
PLATE_BOTTOM = 40
SWATCH = 10
SWATCH_GAP = 4
SWATCH_BOTTOM = 26
LINE1_BOTTOM = 13
LINE2_BOTTOM = 1
SASH = (140, 24)
SASH_BOTTOM = ART_BOTTOM - 8
"""The sash crosses the fighter's feet, so the fighter stays in view."""
ENTER_TICKS = 8
"""A fighter slides into its panel over this many ticks when it changes."""
ENTER_SLIDE = 12
SASH_TICKS = 12
SASH_SLIDE = 36
FLOAT_PERIOD = 120
"""Each isle bobs a pixel up and down over this many ticks, a little out of step."""
JOIN_BLINK = 40
PROMPT_TOP = 180
"""Height of an empty panel's first prompt line above the panel's bottom."""
PROMPT_STEP = 12
CHIP = Rect(388, NATIVE_H - 24, 240, 20)
CHIP_ROW = -1
"""A player's cursor row when it is on the rules chip, above the roster."""
ROSTER_ROW = 0
GAUGE_WIDTH = 84
STAT_ICONS = {"weight": "weight", "speed": "speed", "air": "air", "power": "burst"}
OPEN_SLOT = "OPEN"
"""What an empty panel says when it is not the next one to be filled."""


@dataclass(slots=True)
class Slot:
    """One player slot on the character select screen."""

    device: str = ""
    """The device that joined this slot ("" = empty)."""
    character: int = 0
    """The roster tile the slot's cursor is on (the last tile is Random)."""
    team: int = 0
    ready: bool = False
    row: int = 0
    """Which of the slot's rows its cursor is on: 0 the roster, then team (a person) or
    level and team (a CPU); -1 is the rules chip."""
    cpu: int = 0
    """CPU level (0 = a person's slot)."""
    owner: str = ""
    """For a CPU slot: the device of the player who added it and sets it up."""
    costume: int = 0
    """The costume picked for the slot's character."""

    @property
    def taken(self) -> bool:
        """Whether someone, or a CPU, plays in this slot."""
        return bool(self.device) or self.cpu > 0

    def clear(self) -> None:
        """Empty the slot."""
        self.device, self.ready, self.row, self.cpu, self.owner = "", False, 0, 0, ""


class PlayerPanel:
    """One of the four panels along the bottom: who plays, as whom, in which costume."""

    def __init__(self, view: CharacterSelectView, index: int) -> None:
        """Create the panel's parts, empty."""
        ui = view.ui
        left = PANEL_LEFT + index * (PANEL_WIDTH + PANEL_GAP)
        self.rect = Rect(left, PANEL_BOTTOM, PANEL_WIDTH, PANEL_HEIGHT)
        rect = self.rect
        self.index = index
        self.frame = Picture(ui, rect)
        self.strip_rect = Rect(left + 1, rect.top - STRIP_HEIGHT - 1, PANEL_WIDTH - 2, STRIP_HEIGHT)
        self.strip = Picture(ui, self.strip_rect)
        self.icon = arcade.Sprite(
            center_x=self.strip_rect.left + 12, center_y=self.strip_rect.bottom + 8
        )
        self.icon.visible = False
        ui.panels.append(self.icon)
        centre = left + PANEL_WIDTH // 2
        isle_height = ISLE_WIDTH // 2 + select_art.ISLE_DEPTH + select_art.ISLE_ROOT
        self.isle_rect = Rect(
            centre - ISLE_WIDTH // 2,
            rect.bottom + ART_BOTTOM + ISLE_WIDTH // 4 - isle_height,
            ISLE_WIDTH,
            isle_height,
        )
        self.isle = Picture(ui, self.isle_rect)
        self.art = arcade.Sprite(center_x=centre, center_y=rect.bottom)
        self.art.visible = False
        ui.panels.append(self.art)
        self.plate_rect = Rect(left + 8, rect.bottom + PLATE_BOTTOM, *PLATE)
        self.plate = Picture(ui, self.plate_rect)
        width = 6 * SWATCH + 5 * SWATCH_GAP
        first = left + (PANEL_WIDTH - width) // 2
        self.swatch_rects = [
            Rect(first + slot * (SWATCH + SWATCH_GAP), rect.bottom + SWATCH_BOTTOM, SWATCH, SWATCH)
            for slot in range(6)
        ]
        self.swatches = [Picture(ui, each) for each in self.swatch_rects]
        self.sash_rect = Rect(left + (PANEL_WIDTH - SASH[0]) // 2, rect.bottom + SASH_BOTTOM, *SASH)
        self.sash = Picture(ui, self.sash_rect)
        self.tag = ui.write(
            "",
            0,
            text_bottom(self.strip_rect, TextSize.BODY),
            TextSize.BODY,
            theme.TEXT_ON_FOCUS,
            shadow=False,
        )
        # The plate's left end is a solid block: the name centres on the rest of it.
        block = PLATE[1]
        name_rect = Rect(
            self.plate_rect.left + block, self.plate_rect.bottom, PLATE[0] - block - 4, PLATE[1]
        )
        self.name = ui.write_in(name_rect, "", TextSize.TITLE)
        self.unknown = ui.write(
            "?", centre, rect.bottom + ART_BOTTOM + 36, TextSize.DISPLAY, theme.TEXT_DIM, "centre"
        )
        self.prompt = [
            ui.write(
                "",
                centre,
                rect.bottom + PROMPT_TOP - row * PROMPT_STEP,
                TextSize.BODY,
                theme.TEXT_MUTED,
                "centre",
            )
            for row in range(text.PROMPT_LINES)
        ]
        self.line1 = ui.write(
            "", centre, rect.bottom + LINE1_BOTTOM, TextSize.BODY, theme.TEXT, "centre"
        )
        self.line2 = ui.write(
            "", centre, rect.bottom + LINE2_BOTTOM, TextSize.BODY, theme.TEXT, "centre"
        )
        self.sash_text = ui.write_in(
            self.sash_rect, "", TextSize.DISPLAY, theme.TEXT_ON_FOCUS, shadow=False
        )
        self.banner_rect = Rect(left + 4, rect.bottom + 2, PANEL_WIDTH - 8, 42)
        self.shown: tuple[str, int] | None = None
        """The fighter and costume the art shows, to notice a change."""
        self.enter_tick = 0
        self.ready_tick: int | None = None


class CharacterSelectView(MenuView):
    """Up to four players join with their own device, pick a character (and a team), and
    press confirm when ready. The match goes on to stage select once everyone is ready.

    A device that has not joined joins the first free slot with confirm. Back un-readies,
    then leaves the slot; with nobody joined it goes back to the main menu. Slots remember
    their device between visits and between sessions.

    A joined player moves their cursor over the roster with the stick; strong (or the up
    and down modifiers) changes costume. Up from the roster reaches the rules chip, which
    confirm opens; in a team match down reaches the player's team.

    A joined player adds a CPU to the first free slot with grab (plan note 13: player type
    Human/CPU/Off and CPU level per slot) and then sets it up: left and right change the row,
    up and down move between character, level and team, confirm goes back to the player's
    own slot and back removes the CPU. CPUs are always ready, and leave with their player.
    """

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Build the roster, the detail strip and four panels, and rejoin the devices that
        were here last time."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.setup = setup
        self.character_ids = tuple(list_character_ids())
        self.tiles = roster_model.roster_tiles(self.character_ids)
        characters = [load_character(name) for name in self.character_ids]
        self.character_names = tuple(character.display_name for character in characters)
        self.entries = roster_model.roster_entries(characters)
        self._banks: dict[str, SpriteBank | None] = {}
        self._swatches: dict[str, list[theme.Rgb]] = {}
        self.slots = [Slot(team=index % len(TEAM_NAMES)) for index in range(MAX_PLAYERS)]
        self.focus: dict[str, int] = {}
        """For a player editing one of their CPUs: which slot."""
        self._message = ""
        self.detail_slot = 0
        """The slot whose cursor the detail strip follows: whoever moved last."""
        for index, device in enumerate(flow.settings.slot_devices):
            if device and self.hub.connected(device) and not self._slot_of(device):
                self.slots[index].device = device
        for index, name in enumerate(setup.characters[:MAX_PLAYERS]):
            if name in self.tiles:
                self.slots[index].character = self.tiles.index(name)
        if not setup.training:
            for index, level in enumerate(setup.cpus[:MAX_PLAYERS]):
                owner = next((slot.device for slot in self.slots if slot.device), "")
                if level > 0 and owner and not self.slots[index].taken:
                    self.slots[index].cpu, self.slots[index].owner = level, owner
        for index, team in enumerate(setup.teams[:MAX_PLAYERS]):
            self.slots[index].team = team
        for index, slot in enumerate(self.slots):
            wanted = setup.costumes[index] if index < len(setup.costumes) else None
            slot.costume = self._default_costume(index) if wanted is None else wanted
        for index in range(MAX_PLAYERS):
            self._settle_costume(index)

        self.header("TRAINING: CHARACTER" if setup.training else "CHARACTER SELECT")
        ui = self.ui
        self.chip: Button | None = None
        if not setup.training:
            self.chip = Button(ui, CHIP, "", "gear")
        rows = -(-len(self.tiles) // roster_model.TILES_PER_ROW)
        needed = rows * TILE[1] + (rows - 1) * TILE_GAP
        top = ROSTER_TOP
        if needed <= ROSTER_FRAME.height - 2 * theme.PAD:
            top = ROSTER_FRAME.top - (ROSTER_FRAME.height - needed) // 2
        columns = min(len(self.tiles), roster_model.TILES_PER_ROW)
        row_width = columns * TILE[0] + (columns - 1) * TILE_GAP
        left = ROSTER_FRAME.left + (ROSTER_FRAME.width - row_width) // 2
        self.tile_rects = roster_model.tile_rects(len(self.tiles), left, top, *TILE, TILE_GAP)
        add_panel(ui, ROSTER_FRAME)
        self.tile_backs: list[Picture] = []
        for tile, rect in zip(self.tiles, self.tile_rects, strict=True):
            self.tile_backs.append(Picture(ui, rect))
            bank = None if tile == RANDOM else self._bank(tile)
            texture = None if bank is None else bank.portrait("tile", 0)
            if texture is not None:
                ui.image(texture, rect.left + 3, rect.bottom + 3)
            else:
                ui.write_in(rect, "?", TextSize.DISPLAY, theme.TEXT_MUTED)
            strip = Rect(rect.left + 1, rect.bottom + 1, rect.width - 2, NAME_STRIP)
            ui.picture(
                ("tile-strip", strip.width),
                lambda strip=strip: kit_art.filled(
                    kit_art.shape_mask(strip.width, strip.height, 0), theme.PANEL_DEEP
                ),
                strip.left,
                strip.bottom,
            )
            name = roster_model.RANDOM_NAME if tile == RANDOM else self.entries[tile].name
            ui.write_in(strip, name.upper(), TextSize.SMALL, pad=0)
        self.cursors = [Picture(ui, Rect(0, 0, 1, 1)) for _ in range(MAX_PLAYERS)]
        self.cursor_tags = [
            ui.write("", 0, 0, TextSize.SMALL, theme.player_color(index))
            for index in range(MAX_PLAYERS)
        ]

        add_panel(ui, DETAIL)
        left, top = DETAIL.left + theme.PAD, DETAIL.top
        self.detail_accent = Picture(ui, Rect(left, top - 21, 4, 16))
        self.detail_name = ui.write("", left + 9, top - 20, TextSize.TITLE, theme.HEADING)
        self.detail_kind = ui.write("", left, top - 19, TextSize.BODY, theme.TEXT)
        self.detail_blurb = [
            ui.write("", left, top - 34 - row * 12, TextSize.BODY, theme.TEXT_MUTED)
            for row in range(2)
        ]
        self.gauges: dict[str, Gauge] = {}
        self.gauge_labels: dict[str, TextLabel] = {}
        for index, stat in enumerate(STAT_NAMES):
            column, row = index % 2, index // 2
            x = left + column * 146
            y = DETAIL.bottom + 22 - row * 14
            ui.icon(STAT_ICONS[stat], x, y - 3, theme.TEXT_MUTED)
            self.gauge_labels[stat] = ui.write(
                STAT_LABELS[stat], x + 15, y, TextSize.SMALL, theme.TEXT_MUTED
            )
            self.gauges[stat] = Gauge(ui, Rect(x + 52, y - 1, GAUGE_WIDTH, 8), segmented=True)

        self.panels = [PlayerPanel(self, index) for index in range(MAX_PLAYERS)]
        # The hints start in the keys of a device that is really in (decision D-062).
        joined = [slot.device for slot in self.people]
        if joined and self.active_device not in joined:
            self.active_device = joined[0]
        self.footer(*text.footer_template(self._footer_state(), setup.training))
        self.refresh()

    # --- helpers ---------------------------------------------------------------------------

    def _bank(self, character_id: str) -> SpriteBank | None:
        if character_id not in self._banks:
            try:
                sprite_set = load_sprite_set(character_id)
            except SpriteSheetError:
                sprite_set = None
            self._banks[character_id] = None if sprite_set is None else SpriteBank(sprite_set)
        return self._banks[character_id]

    def _slot_of(self, device: str) -> Slot | None:
        return next((slot for slot in self.slots if slot.device == device), None)

    @property
    def joined(self) -> list[Slot]:
        """The slots that have a player or a CPU, packed in order: slot order is player
        order."""
        return [slot for slot in self.slots if slot.taken]

    @property
    def people(self) -> list[Slot]:
        """The slots that people joined."""
        return [slot for slot in self.slots if slot.device]

    def _teams(self) -> bool:
        """Whether players pick a team here (a team match, outside training)."""
        return self.setup.team_play and not self.setup.training

    @property
    def controls_row(self) -> int:
        """A person's last row: the controls chooser (after the team row in a team match)."""
        return 2 if self._teams() else 1

    @property
    def message(self) -> str:
        """The message in the bottom band right now ("" once it has gone)."""
        return self._message if self.notice_shown else ""

    @message.setter
    def message(self, value: str) -> None:
        self._message = value
        self.notify(value)

    def pointer_device(self) -> str:
        """Enter, Escape and the mouse act for the first person who has joined (not always
        the WASD keyboard: decision D-062); with nobody in, for the keyboard in use."""
        people = self.people
        return people[0].device if people else super().pointer_device()

    def poll(self) -> dict[str, InputFrame]:
        """Read every device. A keyboard layout that has not joined ignores the keys a
        joined layout also binds, so one press of a shared key cannot be "back" for a player
        and "join" for nobody (decision D-062)."""
        keys = self._keys.keys()
        joined = {slot.device for slot in self.slots if slot.device}
        taken: set[int] = set()
        for device in joined:
            if device in self.hub.keyboards:
                taken.update(self.hub.keyboards[device].keys())
        frames = {}
        for device in self.hub.ids():
            unjoined_keyboard = device in self.hub.keyboards and device not in joined
            frames[device] = self.hub.frame(device, keys - taken if unjoined_keyboard else keys)
        return frames

    def free_devices(self) -> list[str]:
        """The devices nobody has joined on, in the hub's order."""
        joined = {slot.device for slot in self.slots if slot.device}
        return [device for device in self.hub.ids() if device not in joined]

    def _free_slot(self) -> Slot | None:
        return next((free for free in self.slots if not free.taken), None)

    def character_of(self, slot: Slot) -> str:
        """Return the roster tile a slot is on: a character id, or ``"random"``."""
        return self.tiles[slot.character % len(self.tiles)]

    def _costume_count(self, slot: Slot) -> int:
        tile = self.character_of(slot)
        bank = None if tile == RANDOM else self._bank(tile)
        return 1 if bank is None else len(bank.sprite_set.costumes)

    def _default_costume(self, index: int) -> int:
        return costume_index(index, False, max(self._costume_count(self.slots[index]), 1))

    def _taken_costumes(self, index: int) -> list[int]:
        """The costumes other taken slots wear on the same character as slot ``index``."""
        mine = self.character_of(self.slots[index])
        return [
            other.costume
            for position, other in enumerate(self.slots)
            if position != index and other.taken and self.character_of(other) == mine
        ]

    def _settle_costume(self, index: int) -> None:
        """Keep a slot's costume valid and its own: nobody else on its character wears it."""
        slot = self.slots[index]
        count = self._costume_count(slot)
        taken = self._taken_costumes(index) if slot.taken else []
        slot.costume = roster_model.free_costume(slot.costume, count, taken)

    def shown_costume(self, index: int) -> int:
        """Return the costume a slot's art is drawn in: its team's colour in a team match,
        else the one it picked."""
        slot = self.slots[index]
        count = self._costume_count(slot)
        if self._teams():
            return costume_index(slot.team, True, count)
        return slot.costume % max(count, 1)

    # --- input -----------------------------------------------------------------------------

    def act(self, device: str, action: MenuAction) -> None:
        """Join, move the device's own cursor (or a CPU's it added), change costume, toggle
        ready, add or remove a CPU, open the rules, or leave."""
        slot = self._slot_of(device)
        if slot is None:
            if action is MenuAction.CONFIRM:
                free = self._free_slot()
                if free is not None:
                    free.clear()
                    free.device = device
                    index = self.slots.index(free)
                    self._settle_costume(index)
                    self.detail_slot = index
                    self._announce(self._shared_warning(device), text.joined(index, device))
            elif action is MenuAction.BACK and not self.people:
                self.flow.show_main_menu()
            elif action in (MenuAction.EXTRA, MenuAction.ALT, MenuAction.ALT_BACK):
                # Never silence: a device that is not in is told how to get in.
                self.message = text.join_first(self.flow.settings, device)
            return
        self.message = ""
        if action is MenuAction.EXTRA and not slot.ready and not self.setup.training:
            self._add_cpu(device)
            return
        focused = self.focus.get(device)
        if focused is not None and self.slots[focused].owner == device:
            self._edit_cpu(device, self.slots[focused], action)
            return
        self.focus.pop(device, None)
        index = self.slots.index(slot)
        self.detail_slot = index
        if action is MenuAction.BACK:
            if slot.ready:
                slot.ready = False
            elif slot.row == CHIP_ROW:
                slot.row = ROSTER_ROW
            else:
                slot.clear()
                for cpu in self.slots:
                    if cpu.owner == device:
                        cpu.clear()
            return
        if action is MenuAction.CONFIRM:
            if slot.row == CHIP_ROW and not slot.ready:
                self.open_rules()
                return
            slot.ready = True
            self._maybe_start()
            return
        if slot.ready:
            return
        if action in (MenuAction.ALT, MenuAction.ALT_BACK):
            self._change_costume(index, 1 if action is MenuAction.ALT else -1)
        elif slot.row == ROSTER_ROW:
            self._move_on_roster(
                index, action, low=CHIP_ROW if self.chip else 0, high=self.controls_row
            )
        elif action is MenuAction.UP:
            slot.row = max(slot.row - 1, CHIP_ROW if self.chip else 0)
        elif action is MenuAction.DOWN:
            slot.row = min(slot.row + 1, self.controls_row)
        elif action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = -1 if action is MenuAction.LEFT else 1
            if slot.row == self.controls_row:
                self.switch_device(index, step)
            elif slot.row > ROSTER_ROW:
                slot.team = (slot.team + step) % len(TEAM_NAMES)

    def switch_device(self, index: int, step: int) -> None:
        """Give a person's slot the next (or previous) free device: the controls chooser.
        The player keeps character, costume and team and is un-readied; the CPUs they added
        follow them; the hints follow at once; and the choice is remembered."""
        slot = self.slots[index]
        old = slot.device
        choices = [
            device for device in self.hub.ids() if device == old or device in self.free_devices()
        ]
        if not old or len(choices) < 2:
            self.message = "NO OTHER CONTROLS ARE FREE"
            return
        new = choices[(choices.index(old) + step) % len(choices)]
        slot.device, slot.ready = new, False
        for cpu in self.slots:
            if cpu.owner == old:
                cpu.owner = new
        if old in self.focus:
            self.focus[new] = self.focus.pop(old)
        self.active_device = new
        self.audio.play("ui_pick")
        remembered = tuple(each.device for each in self.slots)
        self.flow.update_settings(replace(self.flow.settings, slot_devices=remembered))
        self._announce(self._shared_warning(new), text.switched(index, new))

    def _announce(self, warning: str, news: str) -> None:
        """Show a warning if there is one (red), else a piece of news (gold)."""
        self._message = warning or news
        self.notify(self._message, warning=bool(warning))

    def _shared_warning(self, device: str) -> str:
        """Return the warning if ``device`` and another joined keyboard share keys."""
        for other in self.people:
            if other.device != device:
                warning = text.shared_message(self.flow.settings, other.device, device)
                if warning:
                    return warning
        return ""

    def _move_on_roster(self, index: int, action: MenuAction, low: int, high: int) -> None:
        """Move a slot's cursor over the tiles; off the top or bottom of the grid it goes
        on to the row above or below the roster, if there is one."""
        slot = self.slots[index]
        target = roster_model.move_cursor(slot.character, action, len(self.tiles))
        if target is None:
            row = slot.row + (1 if action is MenuAction.DOWN else -1)
            slot.row = min(max(row, low), high)
        elif target != slot.character:
            slot.character = target
            self._settle_costume(index)

    def _change_costume(self, index: int, step: int) -> None:
        slot = self.slots[index]
        if self._teams() or self.character_of(slot) == RANDOM:
            return
        before = slot.costume
        slot.costume = roster_model.next_costume(
            slot.costume, step, self._costume_count(slot), self._taken_costumes(index)
        )
        if slot.costume != before:
            self.audio.play("ui_pick")

    def _add_cpu(self, owner: str) -> None:
        """Put a CPU in the first free slot and let ``owner`` set it up."""
        free = self._free_slot()
        if free is None:
            return
        index = self.slots.index(free)
        free.clear()
        free.cpu, free.owner = CPU_DEFAULT_LEVEL, owner
        free.character = index % len(self.character_ids)
        free.costume = self._default_costume(index)
        self._settle_costume(index)
        self.focus[owner] = index
        self.detail_slot = index

    def _edit_cpu(self, owner: str, cpu: Slot, action: MenuAction) -> None:
        """Set up a CPU: character, level and (in team play) team."""
        rows = 3 if self._teams() else 2
        index = self.slots.index(cpu)
        self.detail_slot = index
        if action is MenuAction.BACK:
            cpu.clear()
            self.focus.pop(owner, None)
        elif action is MenuAction.CONFIRM:
            self.focus.pop(owner, None)
        elif action in (MenuAction.ALT, MenuAction.ALT_BACK):
            self._change_costume(index, 1 if action is MenuAction.ALT else -1)
        elif cpu.row == ROSTER_ROW and action in (MenuAction.LEFT, MenuAction.RIGHT):
            self._move_on_roster(index, action, low=0, high=rows - 1)
        elif action in (MenuAction.UP, MenuAction.DOWN):
            moved = roster_model.move_cursor(cpu.character, action, len(self.tiles))
            if cpu.row == ROSTER_ROW and moved is not None and moved != cpu.character:
                cpu.character = moved
                self._settle_costume(index)
            else:
                cpu.row = (cpu.row + (1 if action is MenuAction.DOWN else -1)) % rows
        elif action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = -1 if action is MenuAction.LEFT else 1
            if cpu.row == 1:
                span = CPU_MAX_LEVEL - CPU_MIN_LEVEL + 1
                cpu.cpu = (cpu.cpu - CPU_MIN_LEVEL + step) % span + CPU_MIN_LEVEL
            else:
                cpu.team = (cpu.team + step) % len(TEAM_NAMES)

    def open_rules(self) -> None:
        """Go to the rules screen; BACK there comes back here with everyone still joined."""
        self.flow.setup = with_saved(self.flow.setup, self.flow.settings.rules)
        self.flow.show_rules(self.resume)

    def resume(self) -> None:
        """Come back from the rules screen: take the rules as they are now."""
        self.setup = with_saved(self.setup, self.flow.settings.rules)
        for slot in self.slots:
            slot.row = min(max(slot.row, 0), self.controls_row) if slot.device else slot.row
            slot.ready = False
        self.menu_input.reset()
        self._footer_shown = None
        self.window.show_view(self)

    def hover(self, x: int, y: int) -> bool:
        """Return whether the mouse is over something it can click."""
        return self._hit(x, y) is not None

    def _hit(self, x: int, y: int) -> tuple[str, int] | None:
        """Return what is at a native pixel: a roster tile, the rules chip, or, on the
        panel of the player the mouse acts for, a costume swatch, the strip (the controls)
        or the foot (ready)."""
        if self.chip is not None and CHIP.contains(x, y):
            return ("chip", 0)
        for index, rect in enumerate(self.tile_rects):
            if rect.contains(x, y):
                return ("tile", index)
        slot = self._slot_of(self.pointer_device())
        if slot is not None:
            panel = self.panels[self.slots.index(slot)]
            for costume, rect in enumerate(panel.swatch_rects):
                if rect.contains(x, y):
                    return ("swatch", costume)
            if panel.strip_rect.contains(x, y):
                return ("strip", 0)
            if panel.banner_rect.contains(x, y):
                return ("ready", 0)
        return None

    def click(self, x: int, y: int) -> None:
        """The mouse plays the first person who has joined (or joins the keyboard in use,
        if nobody has): a click on a tile picks that fighter, on a swatch that costume, on
        the panel's strip the next controls, on its foot readies, and on the chip opens the
        rules."""
        hit = self._hit(x, y)
        if hit is None:
            return
        kind, value = hit
        self.audio.play("ui_select")
        if kind == "chip":
            self.open_rules()
            return
        device = self.pointer_device()
        slot = self._slot_of(device)
        if slot is None:
            self.act(device, MenuAction.CONFIRM)
            slot = self._slot_of(device)
            if slot is None:
                return
        index = next(place for place, each in enumerate(self.slots) if each is slot)
        self.focus.pop(device, None)
        if kind == "ready":
            self.act(device, MenuAction.CONFIRM)
        elif kind == "strip":
            self.switch_device(index, 1)
        elif slot.ready:
            return
        elif kind == "tile":
            slot.character, slot.row = value, ROSTER_ROW
            self._settle_costume(index)
            self.detail_slot = index
        elif kind == "swatch" and not self._teams() and value < self._costume_count(slot):
            count = self._costume_count(slot)
            slot.costume = roster_model.free_costume(value, count, self._taken_costumes(index))

    # --- starting --------------------------------------------------------------------------

    def current_setup(self, resolve: bool = False) -> MatchSetup:
        """Return the setup as the joined slots have it now. Training adds a dummy as
        player 2 when only one player has joined. With ``resolve`` a slot on Random gets a
        character (from the session's seeded generator) and keeps it."""
        if resolve:
            for index, slot in enumerate(self.slots):
                if slot.taken and self.character_of(slot) == RANDOM:
                    slot.character = self.flow.rng.below(len(self.character_ids))
                    slot.costume = self._default_costume(index)
                    self._settle_costume(index)
        joined = self.joined
        characters = [self.character_of(slot) for slot in joined]
        devices = [slot.device for slot in joined]
        teams = [slot.team for slot in joined]
        cpus = [slot.cpu for slot in joined]
        costumes = [slot.costume for slot in joined]
        if self.setup.training and len(joined) == 1:
            characters.append(characters[0])
            devices.append("")
            teams.append(1)
            cpus.append(0)
            count = self._costume_count(joined[0])
            costumes.append(roster_model.next_costume(costumes[0], 1, count))
        return replace(
            self.setup,
            characters=tuple(characters),
            devices=tuple(devices),
            teams=tuple(teams),
            cpus=tuple(cpus) if any(cpus) else (),
            costumes=tuple(costumes),
        )

    def _maybe_start(self) -> None:
        people = self.people
        if not people or not all(slot.ready for slot in people):
            return
        reason = can_start(self.current_setup(), len(self.joined))
        if reason:
            self.message = text.start_problem(reason, self.flow.settings, self.active_device)
            for slot in people:
                slot.ready = False
            return
        setup = self.current_setup(resolve=True)
        remembered = tuple(slot.device for slot in self.slots)
        self.flow.update_settings(replace(self.flow.settings, slot_devices=remembered))
        self.flow.show_stage_select(setup)

    # --- drawing ---------------------------------------------------------------------------

    def slot_color(self, index: int) -> theme.Rgb:
        """Return a slot's colour: its team's in a team match, else its player's."""
        return theme.player_color(self.slots[index].team if self._teams() else index)

    def refresh(self) -> None:
        """Redraw everything from the slots. A slot whose controller was unplugged is
        emptied."""
        for slot in self.slots:
            if slot.device and not self.hub.connected(slot.device):
                for cpu in self.slots:
                    if cpu.owner == slot.device:
                        cpu.clear()
                slot.clear()
        # Stage select's pictures are drawn now, one a tick, so it opens without a pause.
        stage_preview.warm_next(self.window)
        editing = {index: owner for owner, index in self.focus.items()}
        for index in range(MAX_PLAYERS):
            self._refresh_panel(index, index in editing)
        self._refresh_cursors(editing)
        self._refresh_detail()
        if self.chip is not None:
            self.chip.label.text = "  ".join(rule_chips(self.setup))
            on_chip = any(
                slot.device and slot.row == CHIP_ROW and not slot.ready for slot in self.slots
            )
            self.chip.focus(on_chip)
        named = self.active_device if len(self.people) > 1 else ""
        template, drop = text.footer_template(self._footer_state(), self.setup.training, named)
        if template != self._footer_template:
            self.footer(template, drop)
        self._sync_footer()

    def _footer_state(self) -> str:
        """Return what the player on the active device is doing (a key of
        ``select_text.FOOTERS``), which decides what the footer explains."""
        device = self.active_device
        slot = self._slot_of(device)
        if slot is None:
            return "unjoined"
        if device in self.focus:
            return "cpu"
        if slot.ready:
            return "ready"
        if slot.row == CHIP_ROW:
            return "chip"
        if slot.row == self.controls_row:
            return "controls"
        return "team" if slot.row > ROSTER_ROW else "roster"

    def _stepper(self, text: str, focused: bool) -> str:
        return f"{ARROW_LEFT} {text} {ARROW_RIGHT}" if focused else text

    def slot_ramp(self, index: int) -> theme.Ramp:
        """Return the colour ramp a slot's panel is painted in: greys while it is empty."""
        if not self.slots[index].taken:
            return theme.EMPTY_RAMP
        return theme.player_ramp(self.slots[index].team if self._teams() else index)

    def _refresh_panel(self, index: int, editing: bool) -> None:
        slot, panel = self.slots[index], self.panels[index]
        color = self.slot_color(index)
        ramp = self.slot_ramp(index)
        rect = panel.rect
        taken = slot.taken
        ticks = self.flow.menu_ticks
        border = theme.FOCUS if slot.ready else ramp[1]
        panel.frame.show(
            ("select-panel", rect.width, rect.height, ramp, border, taken),
            lambda: select_art.panel_backdrop(rect.width, rect.height, ramp, border, taken),
        )
        strip = panel.strip_rect
        strip_color, stripes = (ramp[1], ramp[2]) if taken else (theme.SLATE, theme.ASH)
        panel.strip.show(
            ("select-strip", strip.width, strip.height, strip_color, stripes),
            lambda: select_art.strip(strip.width, strip.height, strip_color, stripes),
        )
        panel.isle.show(
            ("select-isle", ISLE_WIDTH, ramp), lambda: select_art.isle(ISLE_WIDTH, ramp)
        )
        rise = anim.wave(ticks, index, 1, FLOAT_PERIOD, FLOAT_PERIOD // 5)
        isle = panel.isle_rect
        panel.isle.sprite.center_y = isle.bottom + isle.height / 2 + rise
        teams = self._teams()
        tile = self.character_of(slot)
        settings = self.flow.settings
        for line in panel.prompt:
            line.text = ""
        plate = panel.plate_rect
        self._show_sash(index)
        if not taken:
            panel.plate.hide()
            panel.icon.visible = False
            panel.tag.text, panel.tag.color = f"P{index + 1}", theme.TEXT_MUTED
            panel.tag.move_to(
                strip.left + strip.width // 2 - panel.tag.width // 2, panel.tag.bottom
            )
            panel.name.text = ""
            panel.line1.text = panel.line2.text = ""
            panel.unknown.visible = False
            panel.art.visible = False
            panel.shown = None
            for swatch in panel.swatches:
                swatch.hide()
            # The next slot to fill lists how to join on each free device, each in that
            # device's own keys; the slots after it are just open.
            first_free = next(place for place, each in enumerate(self.slots) if not each.taken)
            lines = [OPEN_SLOT]
            if index == first_free:
                people = self.people
                adder = people[0].device if people and not self.setup.training else ""
                lines = text.join_lines(settings, self.free_devices(), adder) or [OPEN_SLOT]
            for line, words in zip(panel.prompt, lines, strict=False):
                line.text = words
                line.color = theme.TEXT_MUTED if words == OPEN_SLOT else theme.TEXT
            if lines[0] == text.JOIN_HEADING:
                blink = anim.blink(ticks, JOIN_BLINK)
                panel.prompt[0].color = theme.FOCUS if blink else theme.TEXT_MUTED
            return

        panel.plate.show(
            ("select-plate", plate.width, plate.height, color),
            lambda: select_art.name_plate(plate.width, plate.height, color),
        )
        icon = "cpu" if slot.cpu else "controller" if slot.device.startswith("pad") else "keyboard"
        texture = icon_texture(icon, theme.INK)
        panel.icon.visible = texture is not None
        if texture is not None and panel.icon.texture is not texture:
            panel.icon.texture = texture
        panel.tag.color = theme.TEXT_ON_FOCUS
        if slot.cpu:
            panel.tag.text = f"P{index + 1}  CPU {slot.cpu}"
        else:
            panel.tag.text = f"P{index + 1}  {text.device_name(slot.device)}"
        panel.tag.move_to(strip.left + 22, panel.tag.bottom)
        if tile == RANDOM:
            panel.name.text = "RANDOM"
        else:
            panel.name.text = self.entries[tile].name.upper()
        self._show_art(index)
        self._show_swatches(index)

        team_text = f"{TEAM_NAMES[slot.team].upper()} TEAM"
        if slot.cpu:
            panel.line1.text = self._stepper(f"LEVEL {slot.cpu}", editing and slot.row == 1)
            panel.line1.color = theme.FOCUS if editing and slot.row == 1 else theme.TEXT
            if teams:
                panel.line2.text = self._stepper(team_text, editing and slot.row == 2)
                panel.line2.color = theme.FOCUS if editing and slot.row == 2 else color
            else:
                # A CPU's hints are in its owner's keys: attack ends the set-up.
                panel.line2.text = (
                    text.panel_line(text.CPU_EDIT_LINE, settings, slot.owner) if editing else "CPU"
                )
                panel.line2.color = theme.TEXT_MUTED
            return
        # A person's hints are in that person's own keys, whoever acted last.
        device = slot.device
        busy = device in self.focus
        here = not slot.ready and not busy
        if teams:
            panel.line1.text = self._stepper(team_text, here and slot.row == 1)
            panel.line1.color = theme.FOCUS if here and slot.row == 1 else color
        else:
            panel.line1.text = text.CONTROLS_HINT if here and slot.row == ROSTER_ROW else ""
            panel.line1.color = theme.TEXT_DIM
        panel.line2.color = theme.TEXT_MUTED
        if slot.ready:
            panel.line2.text = text.panel_line(text.CANCEL_LINE, settings, device)
        elif busy:
            panel.line2.text = text.OWNER_WAITS
        elif slot.row == self.controls_row:
            panel.line2.text = self._stepper(text.device_name(device), True)
            panel.line2.color = theme.FOCUS
        else:
            panel.line2.text = text.panel_line(text.READY_LINE, settings, device)

    def device_name(self, device: str) -> str:
        """Return a device's name as a panel's strip shows it."""
        return text.device_name(device)

    def _show_art(self, index: int) -> None:
        """Show the slot's character in the costume it will wear: its hero art, or a
        question mark for Random or a character without art."""
        slot, panel = self.slots[index], self.panels[index]
        tile = self.character_of(slot)
        bank = None if tile == RANDOM else self._bank(tile)
        texture = None
        if bank is not None:
            texture = bank.portrait("hero", self.shown_costume(index))
        panel.art.visible = texture is not None
        panel.unknown.visible = texture is None
        panel.unknown.color = self.slot_ramp(index)[0]
        ticks = self.flow.menu_ticks
        shown = (tile, self.shown_costume(index))
        if shown != panel.shown:
            # A new fighter (or costume) slides in from the left.
            panel.shown = shown
            panel.enter_tick = ticks
        if texture is not None:
            if panel.art.texture is not texture:
                panel.art.texture = texture
            slide = anim.slide(ticks, panel.enter_tick, ENTER_TICKS, -ENTER_SLIDE, 0)
            rise = anim.wave(ticks, index, 1, FLOAT_PERIOD, FLOAT_PERIOD // 5)
            x = panel.rect.left + PANEL_WIDTH // 2 + (texture.width % 2) / 2 + slide
            y = panel.rect.bottom + ART_BOTTOM + rise + texture.height / 2
            panel.art.position = (x, y)
            panel.art.alpha = round(255 * anim.progress(ticks, panel.enter_tick, ENTER_TICKS))

    def _show_sash(self, index: int) -> None:
        """Lay the READY sash across a ready player's panel; it swings in from the left."""
        slot, panel = self.slots[index], self.panels[index]
        if not slot.ready:
            panel.ready_tick = None
            panel.sash.hide()
            panel.sash_text.text = ""
            return
        ticks = self.flow.menu_ticks
        if panel.ready_tick is None:
            panel.ready_tick = ticks
        rect = panel.sash_rect
        panel.sash.show(("select-sash", *SASH), lambda: select_art.sash(*SASH))
        slide = anim.slide(ticks, panel.ready_tick, SASH_TICKS, -SASH_SLIDE, 0, anim.ease_out_back)
        panel.sash.sprite.center_x = rect.left + rect.width / 2 + slide
        panel.sash_text.text = "READY!"
        panel.sash_text.move_to(rect.left + rect.width // 2 + 3 + slide, panel.sash_text.bottom)

    def _show_swatches(self, index: int) -> None:
        slot, panel = self.slots[index], self.panels[index]
        tile = self.character_of(slot)
        bank = None if tile == RANDOM else self._bank(tile)
        if bank is None or self._teams():
            for swatch in panel.swatches:
                swatch.hide()
            return
        colors = self._swatch_colors(tile, bank)
        taken = self._taken_costumes(index)
        for costume, swatch in enumerate(panel.swatches):
            if costume >= len(colors):
                swatch.hide()
                continue
            color = colors[costume]
            chosen = costume == slot.costume
            used = costume in taken
            swatch.show(
                ("swatch", SWATCH, color, chosen, used),
                lambda color=color, chosen=chosen, used=used: kit_art.swatch(
                    SWATCH, theme.SLATE if used else color, chosen
                ),
            )

    def _swatch_colors(self, tile: str, bank: SpriteBank) -> list[theme.Rgb]:
        """Return a character's swatch colours (worked out once from its hero picture)."""
        if tile not in self._swatches:
            area: dict[int, int] = {}
            path = bank.sprite_set.portrait_path("hero")
            if path is not None:
                with Image.open(path) as picture:
                    for count, entry in picture.convert("P").getcolors() or []:
                        area[int(entry)] = count
            self._swatches[tile] = roster_model.costume_swatches(
                bank.sprite_set.costumes, area or None
            )
        return self._swatches[tile]

    def _refresh_cursors(self, editing: dict[int, str]) -> None:
        """Put a frame in each player's colour on the tile their cursor is on (a CPU's shows
        while it is being set up). Cursors on the same tile nest."""
        on_tile: dict[int, int] = {}
        lit_tiles: dict[int, theme.Ramp] = {}
        for index, slot in enumerate(self.slots):
            cursor, tag = self.cursors[index], self.cursor_tags[index]
            shown = bool(slot.device) or index in editing
            if not shown:
                cursor.hide()
                tag.text = ""
                continue
            tile = slot.character % len(self.tiles)
            order = on_tile.get(tile, 0)
            on_tile[tile] = order + 1
            rect = self.tile_rects[tile].inset(-(1 + 2 * order))
            color = self.slot_color(index)
            active = not slot.ready and (index in editing or slot.device not in self.focus)
            cursor.sprite.center_x = rect.left + rect.width / 2
            cursor.sprite.center_y = rect.bottom + rect.height / 2
            if tile not in lit_tiles:
                lit_tiles[tile] = self.slot_ramp(index)
            cursor.show(
                ("select-cursor", rect.width, rect.height, color, active),
                lambda rect=rect, color=color, active=active: kit_art.focus_frame(
                    rect.width, rect.height, color if active else theme.DUST, theme.SMALL_CORNER
                ),
            )
            tag.text = "CPU" if slot.cpu else f"P{index + 1}"
            tag.color = color
            tag.move_to(self.tile_rects[tile].left + order * 16, self.tile_rects[tile].top + 2)
        for tile, back in enumerate(self.tile_backs):
            rect, ramp = self.tile_rects[tile], lit_tiles.get(tile)
            back.show(
                ("select-tile", rect.width, rect.height, ramp),
                lambda rect=rect, ramp=ramp: select_art.roster_tile(rect.width, rect.height, ramp),
            )

    def _refresh_detail(self) -> None:
        slot = self.slots[self.detail_slot]
        if not slot.taken:
            slot = next((each for each in self.slots if each.taken), slot)
        tile = self.character_of(slot)
        entry = RANDOM_ENTRY if tile == RANDOM else self.entries[tile]
        ramp = self.slot_ramp(next(i for i, each in enumerate(self.slots) if each is slot))
        self.detail_accent.show(
            ("select-accent", 4, 16, ramp), lambda: select_art.accent_bar(4, 16, ramp)
        )
        self.detail_name.text = entry.name.upper()
        self.detail_kind.text = entry.archetype
        self.detail_kind.move_to(
            self.detail_name.left + self.detail_name.width + 8, DETAIL.top - 19
        )
        words = entry.blurb.split()
        lines, line = [], ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > 40 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
        for label, words in zip(self.detail_blurb, [*lines, "", ""], strict=False):
            label.text = words
        for stat in STAT_NAMES:
            known = stat in entry.stats
            self.gauges[stat].value = entry.stats.get(stat, 0.0)
            self.gauge_labels[stat].color = theme.TEXT_MUTED if known else theme.TEXT_DIM


assert PANEL_LEFT + MAX_PLAYERS * (PANEL_WIDTH + PANEL_GAP) - PANEL_GAP <= NATIVE_W
