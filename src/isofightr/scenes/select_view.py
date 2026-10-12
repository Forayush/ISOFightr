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
from isofightr.ui.font import ARROW_DOWN, ARROW_UP, TextSize
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Button,
    FocusFrame,
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
    """Where a person's cursor is: 0 the roster, -1 the rules chip above it."""
    cpu: int = 0
    """CPU level (0 = a person's slot)."""
    owner: str = ""
    """For a CPU slot: the device of the player who last set it up ("" = nobody here)."""
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
        self.options = ui.write(
            "", centre, rect.bottom + LINE1_BOTTOM + 2, text.OPTIONS_SIZE, theme.TEXT, "centre"
        )
        """A person's costume and CPU buttons, in the small font (where ``line1`` is)."""
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
    then leaves the slot (the CPUs stay); with nobody joined it goes back to the main menu.
    Slots remember their device between visits and between sessions.

    One job per button, and nothing hidden (decision D-064). The stick moves a joined
    player's cursor over the fighters and never leaves them, except that up from the top
    row reaches the rules chip, which confirm opens. Strong (or the up and down modifiers)
    changes costume, or team in a team match.

    Grab steps a player through the other slots: every CPU, then the first empty slot, then
    home. On an empty slot confirm adds a CPU. On a CPU left and right pick its fighter, up
    and down its level, strong its costume or team; back removes it and confirm goes home.
    CPUs are always ready.
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
        """For a player who has stepped onto another slot with grab (a CPU to set up, or an
        empty slot to add one to): which slot."""
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
                if level > 0 and not self.slots[index].taken:
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
        self.visit_frames = [FocusFrame(ui) for _ in range(MAX_PLAYERS)]
        """A frame in a player's colour around the slot that player has stepped onto."""
        # The hints start in the keys of a device that is really in (decision D-062).
        joined = [slot.device for slot in self.people]
        if joined and self.active_device not in joined:
            self.active_device = joined[0]
        self.footer(
            *text.footer_template(self._footer_state(), setup.training, teams=self._teams())
        )
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
        """Join, move the device's own cursor, change costume or team, toggle ready, step
        through the other slots to add or set up a CPU, open the rules, or leave."""
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
                    self._drop_visits(index)
                    self._announce(self._shared_warning(device), text.joined(index, device))
            elif action is MenuAction.BACK and not self.people:
                self.flow.show_main_menu()
            elif action in (MenuAction.EXTRA, MenuAction.ALT, MenuAction.ALT_BACK):
                # Never silence: a device that is not in is told how to get in.
                self.message = text.join_first(self.flow.settings, device)
            return
        self.message = ""
        index = self.slots.index(slot)
        if action is MenuAction.EXTRA:
            if not slot.ready and not self.setup.training:
                self._next_slot(device, index)
            return
        visited = self.focus.get(device)
        if visited is not None:
            self._act_on_slot(device, visited, action)
            return
        self.detail_slot = index
        if action is MenuAction.BACK:
            if slot.ready:
                slot.ready = False
            elif slot.row == CHIP_ROW:
                slot.row = ROSTER_ROW
            else:
                # Leaving takes nothing with it: the CPUs stay for whoever is here.
                slot.clear()
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
            self._change_look(index, 1 if action is MenuAction.ALT else -1)
        elif slot.row == CHIP_ROW:
            if action is MenuAction.DOWN:
                slot.row = ROSTER_ROW
        else:
            self._move_on_roster(index, action)

    def visit_order(self, home: int) -> list[int]:
        """Return the slots grab steps the player in slot ``home`` through, in order: every
        CPU and the first empty slot, starting after the player's own slot and wrapping
        round. A slot another player is on is left out."""
        device = self.slots[home].device
        first_free = next((i for i, each in enumerate(self.slots) if not each.taken), None)
        busy = {index for other, index in self.focus.items() if other != device}
        order = []
        for step in range(1, MAX_PLAYERS):
            index = (home + step) % MAX_PLAYERS
            if index not in busy and (self.slots[index].cpu or index == first_free):
                order.append(index)
        return order

    def _next_slot(self, device: str, home: int) -> None:
        """Step a player on to the next slot grab reaches; after the last, home."""
        order = self.visit_order(home)
        if not order:
            self.focus.pop(device, None)
            self.message = text.NO_SLOT
            return
        now = self.focus.get(device)
        place = order.index(now) if now in order else -1
        if place + 1 < len(order):
            target = order[place + 1]
            self.focus[device] = target
            self.detail_slot = target
            if self.slots[target].cpu:
                self.slots[target].owner = device
        else:
            self.focus.pop(device, None)
            self.detail_slot = home
        self.audio.play("ui_pick")

    def _act_on_slot(self, device: str, index: int, action: MenuAction) -> None:
        """What a player does on a slot they stepped onto: add a CPU to an empty one, or set
        a CPU up."""
        target = self.slots[index]
        if target.cpu:
            target.owner = device
            self._edit_cpu(device, target, action)
        elif action is MenuAction.CONFIRM:
            self._add_cpu(device, index)
        elif action is MenuAction.BACK:
            self.focus.pop(device, None)

    def _drop_visits(self, index: int) -> None:
        """Send home whoever had stepped onto a slot that someone has just joined."""
        for device in [each for each, visited in self.focus.items() if visited == index]:
            del self.focus[device]

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

    def _move_on_roster(self, index: int, action: MenuAction) -> None:
        """Move a person's cursor over the tiles. It never leaves them, except that up from
        the top row reaches the rules chip (if there is one)."""
        slot = self.slots[index]
        target = roster_model.move_cursor(slot.character, action, len(self.tiles))
        if target is None:
            if action is MenuAction.UP and self.chip is not None:
                slot.row = CHIP_ROW
        elif target != slot.character:
            slot.character = target
            self._settle_costume(index)

    def _change_look(self, index: int, step: int) -> None:
        """The costume button: the next costume, or in a team match the next team (there
        the costume is the team's colour)."""
        slot = self.slots[index]
        if self._teams():
            slot.team = (slot.team + step) % len(TEAM_NAMES)
            self.audio.play("ui_pick")
        else:
            self._change_costume(index, step)

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

    def _add_cpu(self, owner: str, index: int) -> None:
        """Put a CPU in an empty slot; ``owner`` stays on it to set it up."""
        free = self.slots[index]
        if free.taken:
            return
        free.clear()
        free.cpu, free.owner = CPU_DEFAULT_LEVEL, owner
        free.character = index % len(self.character_ids)
        free.costume = self._default_costume(index)
        self._settle_costume(index)
        self.focus[owner] = index
        self.detail_slot = index
        self.audio.play("ui_pick")

    def _edit_cpu(self, owner: str, cpu: Slot, action: MenuAction) -> None:
        """Set up a CPU: left and right its fighter, up and down its level, the costume
        button its costume or team; back removes it, confirm goes home."""
        index = self.slots.index(cpu)
        self.detail_slot = index
        if action is MenuAction.BACK:
            cpu.clear()
            self.focus.pop(owner, None)
        elif action is MenuAction.CONFIRM:
            self.focus.pop(owner, None)
        elif action in (MenuAction.ALT, MenuAction.ALT_BACK):
            self._change_look(index, 1 if action is MenuAction.ALT else -1)
        elif action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = -1 if action is MenuAction.LEFT else 1
            cpu.character = (cpu.character + step) % len(self.tiles)
            self._settle_costume(index)
        elif action in (MenuAction.UP, MenuAction.DOWN):
            step = 1 if action is MenuAction.UP else -1
            cpu.cpu = min(max(cpu.cpu + step, CPU_MIN_LEVEL), CPU_MAX_LEVEL)

    def open_rules(self) -> None:
        """Go to the rules screen; BACK there comes back here with everyone still joined."""
        self.flow.setup = with_saved(self.flow.setup, self.flow.settings.rules)
        self.flow.show_rules(self.resume)

    def resume(self) -> None:
        """Come back from the rules screen: take the rules as they are now."""
        self.setup = with_saved(self.setup, self.flow.settings.rules)
        for slot in self.slots:
            slot.row = ROSTER_ROW
            slot.ready = False
        self.menu_input.reset()
        self._footer_shown = None
        self.window.show_view(self)

    def hover(self, x: int, y: int) -> bool:
        """Return whether the mouse is over something it can click."""
        return self._hit(x, y) is not None

    def _hit(self, x: int, y: int) -> tuple[str, int] | None:
        """Return what is at a native pixel: a roster tile, the rules chip, or, on the
        panel of the player the mouse acts for, a costume swatch or the foot (ready)."""
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
            if panel.banner_rect.contains(x, y):
                return ("ready", 0)
        return None

    def click(self, x: int, y: int) -> None:
        """The mouse plays the first person who has joined (or joins the keyboard in use,
        if nobody has): a click on a tile picks that fighter, on a swatch that costume, on
        the panel's foot readies, and on the chip opens the rules."""
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
                slot.clear()
        joined = {slot.device for slot in self.people}
        for device in [each for each in self.focus if each not in joined]:
            del self.focus[device]
        # Stage select's pictures are drawn now, one a tick, so it opens without a pause.
        stage_preview.warm_next(self.window)
        editing = {index: owner for owner, index in self.focus.items()}
        for index in range(MAX_PLAYERS):
            self._refresh_panel(index, editing.get(index, ""))
        self._refresh_cursors(editing)
        self._refresh_visits()
        self._refresh_detail()
        if self.chip is not None:
            self.chip.label.text = "  ".join(rule_chips(self.setup, hazards=False))
            on_chip = any(
                slot.device and slot.row == CHIP_ROW and not slot.ready for slot in self.slots
            )
            self.chip.focus(on_chip)
        named = self.active_device if len(self.people) > 1 else ""
        template, drop = text.footer_template(
            self._footer_state(), self.setup.training, named, self._teams()
        )
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
            return "cpu" if self.slots[self.focus[device]].cpu else "empty"
        if slot.ready:
            return "ready"
        return "chip" if slot.row == CHIP_ROW else "roster"

    def _refresh_visits(self) -> None:
        """Frame, in each player's colour, the slot that player has stepped onto."""
        ticks = self.flow.menu_ticks
        for index, slot in enumerate(self.slots):
            visited = self.focus.get(slot.device) if slot.device else None
            if visited is None:
                self.visit_frames[index].hide()
            else:
                self.visit_frames[index].show(
                    self.panels[visited].rect, ticks, self.slot_color(index)
                )

    def slot_ramp(self, index: int) -> theme.Ramp:
        """Return the colour ramp a slot's panel is painted in: greys while it is empty."""
        if not self.slots[index].taken:
            return theme.EMPTY_RAMP
        return theme.player_ramp(self.slots[index].team if self._teams() else index)

    def _refresh_panel(self, index: int, visitor: str) -> None:
        """Redraw one panel. ``visitor`` is the device of the player who has stepped onto
        this slot with grab ("" = nobody)."""
        slot, panel = self.slots[index], self.panels[index]
        editing = bool(visitor)
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
            panel.line1.text = panel.line2.text = panel.options.text = ""
            panel.unknown.visible = False
            panel.art.visible = False
            panel.shown = None
            for swatch in panel.swatches:
                swatch.hide()
            # The next slot to fill lists how to join on each free device, each in that
            # device's own keys; the slots after it are just open.
            first_free = next(place for place, each in enumerate(self.slots) if not each.taken)
            lines = [OPEN_SLOT]
            if visitor:
                lines = text.add_lines(settings, visitor)
            elif index == first_free:
                people = self.people
                adder = people[0].device if people and not self.setup.training else ""
                lines = text.join_lines(settings, self.free_devices(), adder) or [OPEN_SLOT]
            for line, words in zip(panel.prompt, lines, strict=False):
                line.text = words
                line.color = theme.TEXT_MUTED if words == OPEN_SLOT else theme.TEXT
            if lines[0] in (text.JOIN_HEADING, text.ADD_HEADING):
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
        panel.options.text = panel.line1.text = ""
        if slot.cpu:
            level = f"LEVEL {slot.cpu}"
            panel.line1.text = f"{ARROW_UP}{ARROW_DOWN} {level}" if editing else level
            panel.line1.color = theme.FOCUS if editing else theme.TEXT
            panel.line2.color = theme.TEXT_MUTED
            if not editing:
                panel.line2.text = team_text if teams else "CPU"
                panel.line2.color = color if teams else theme.TEXT_MUTED
            elif teams:
                # A CPU's hints are in the keys of the player setting it up.
                line = text.CPU_TEAM_LINE.replace("{team}", team_text)
                panel.line2.text = text.panel_line(line, settings, visitor)
                panel.line2.color = color
            else:
                panel.line2.text = text.panel_line(text.CPU_EDIT_LINE, settings, visitor)
            return
        # A person's hints are in that person's own keys, whoever acted last.
        device = slot.device
        panel.line2.color = theme.TEXT_MUTED
        if slot.ready:
            panel.line2.text = text.panel_line(text.CANCEL_LINE, settings, device)
        elif device in self.focus:
            panel.line2.text = text.OWNER_WAITS
        else:
            panel.options.text = text.options_line(
                settings, device, team_text if teams else "", self.setup.training
            )
            panel.options.color = color if teams else theme.TEXT
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
            shown = bool(slot.device) or (index in editing and slot.cpu > 0)
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
