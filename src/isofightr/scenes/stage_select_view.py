"""The stage select screen.

Plan note "13 - Game Modes UI and Flow" ("Stage select", decision D-061, wireframe
``m13_wf_stageselect.png``): a large preview of the stage under the cursor, drawn by the
battle's own renderer from its backdrop and its real tiles with the spawns marked
(:mod:`isofightr.render.stage_preview`); its name on a banner with a one-line description,
its song and its size; a grid of stage tiles, each with a box that says whether Random may
pick it (grab toggles it, and the Rules screen shows the same pool); and the rules of the
match as a row of chips. Random is the last tile; it is resolved when the match starts.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from PIL import Image

from isofightr.config import NATIVE_H
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render import stage_preview
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import stage_info
from isofightr.scenes.menus import MenuView
from isofightr.scenes.rules_model import rule_chips, toggle_pool
from isofightr.scenes.setup import RANDOM_STAGE, MatchSetup
from isofightr.sim.stage import Stage
from isofightr.ui import anim, kit_art, select_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import TextSize, text_width
from isofightr.ui.hints import device_labels, hint_text
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import (
    Checkbox,
    FocusFrame,
    Picture,
    add_panel,
    icon_image,
    text_bottom,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

PREVIEW = Rect(16, 122, *stage_preview.PREVIEW_SIZE)
"""The stage picture; its frame is drawn 4 px outside it."""
FRAME_PAD = 4
BANNER = Rect(10, 106, 250, 26)
"""The name banner, laid over the preview's lower-left corner."""
INFO = Rect(12, 52, 616, 46)
"""The panel under the preview and the grid: description, song, size, the pool."""
DESCRIPTION_BOTTOM = 80
INFO_BOTTOM = 62
GRID_LEFT = 432
GRID_TOP = 330
STAGE_TILE = (94, 68)
TILE_GAP = 6
THUMB = (86, 45)
NAME_STRIP = 12
CHECK_SIZE = 11
CHIP_BOTTOM = 26
CHIP_HEIGHT = 18
CHIP_GAP = 6
POOL_BOTTOM = 80
POOL_HINT_BOTTOM = 62
SLIDE_TICKS = 8
SLIDE_PIXELS = 10
CHIP_ICONS = {"STOCK": "stock", "TIME": "clock", "TEAMS": "team", "START": "percent"}
"""Which icon a rules chip carries, by its first word (the launch rate gets ``burst``)."""
MOSAIC_COLUMNS = 3
DICE_SCALE = 4
"""The dice in the Random preview's spare cell is the 12 px icon this many times over."""
FOCUS_RAMP = theme.player_ramp(2)
"""The golds: the backing of the tile under the cursor, to go with the focus frame."""


class StageSelectView(MenuView):
    """Pick the stage, or Random from the pool, and fight."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Draw every stage's picture (once a session), lay out the grid, and put the
        cursor on the setup's stage."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        self.setup = setup
        self.stages: dict[str, Stage] = {name: load_stage(name) for name in list_stage_ids()}
        self.stage_ids = [*self.stages, RANDOM_STAGE]
        self.cursor = self.stage_ids.index(setup.stage) if setup.stage in self.stage_ids else 0
        self.titles = stage_info.load_music_titles()
        self.pictures = {
            name: stage_preview.stage_picture(self.window, stage, (PREVIEW.width, PREVIEW.height))
            for name, stage in self.stages.items()
        }
        self._shown_cursor = -1
        self._changed_tick = 0

        self.header("TRAINING: STAGE" if setup.training else "STAGE SELECT", "stage")
        ui = self.ui
        add_panel(ui, PREVIEW.inset(-FRAME_PAD))
        add_panel(ui, INFO)
        self.preview = Picture(ui, PREVIEW)
        self.banner = Picture(ui, BANNER)
        self.name_label = ui.write(
            "",
            BANNER.left + BANNER.height + 6,
            text_bottom(BANNER, TextSize.DISPLAY),
            TextSize.DISPLAY,
            theme.HEADING,
        )
        self.description = ui.write("", PREVIEW.left, DESCRIPTION_BOTTOM, TextSize.BODY, theme.TEXT)
        ui.icon("speaker", PREVIEW.left, INFO_BOTTOM - 1, theme.TEXT_MUTED)
        self.music_label = ui.write(
            "", PREVIEW.left + 16, INFO_BOTTOM, TextSize.BODY, theme.TEXT_MUTED
        )
        self.size_icon = ui.icon("stage", PREVIEW.left + 230, INFO_BOTTOM - 1, theme.TEXT_MUTED)
        self.size_label = ui.write(
            "", PREVIEW.left + 246, INFO_BOTTOM, TextSize.BODY, theme.TEXT_MUTED
        )

        self.tile_rects = stage_info.grid_rects(
            len(self.stage_ids), GRID_LEFT, GRID_TOP, *STAGE_TILE, TILE_GAP
        )
        self.tile_backs: list[Picture] = []
        self.checkboxes: list[Checkbox | None] = []
        self.tile_names = []
        for stage_id, rect in zip(self.stage_ids, self.tile_rects, strict=True):
            self.tile_backs.append(Picture(ui, rect))
            thumb_left = rect.left + (rect.width - THUMB[0]) // 2
            thumb_bottom = rect.top - 4 - THUMB[1]
            if stage_id == RANDOM_STAGE:
                ui.write(
                    "?",
                    rect.left + rect.width // 2,
                    thumb_bottom + 12,
                    TextSize.DISPLAY,
                    theme.TEXT_MUTED,
                    "centre",
                )
                ui.icon("dice", thumb_left + 4, thumb_bottom + 4, theme.TEXT_MUTED)
                name = "RANDOM"
            else:
                picture = self.pictures[stage_id]
                ui.picture(
                    ("stage-thumb", stage_id, *THUMB),
                    lambda picture=picture: stage_preview.thumbnail(picture, THUMB),
                    thumb_left,
                    thumb_bottom,
                )
                name = self.stages[stage_id].display_name.upper()
            strip = Rect(rect.left + 1, rect.bottom + 1, rect.width - 2, NAME_STRIP)
            ui.picture(
                ("stage-strip", strip.width, strip.height),
                lambda strip=strip: kit_art.filled(
                    kit_art.shape_mask(strip.width, strip.height, 0), theme.PANEL_DEEP
                ),
                strip.left,
                strip.bottom,
            )
            self.tile_names.append(ui.write_in(strip, name, TextSize.SMALL, pad=0))
            box = None
            if stage_id != RANDOM_STAGE and not setup.training:
                box = Checkbox(
                    ui, rect.right - CHECK_SIZE - 5, rect.top - CHECK_SIZE - 5, CHECK_SIZE
                )
            self.checkboxes.append(box)
        self.focus = FocusFrame(ui)
        self.pool_label = ui.write("", GRID_LEFT, POOL_BOTTOM, TextSize.BODY, theme.TEXT)
        self.pool_hint = ui.write("", GRID_LEFT, POOL_HINT_BOTTOM, TextSize.BODY, theme.TEXT_MUTED)
        self.chips: list[Picture] = []
        self._add_chips()
        hint = "" if setup.training else "   {grab}: random pool"
        self.footer(f"{{stick}}: stage   {{attack}}: fight{hint}   {{special}}: back")
        self.refresh()

    # --- layout ----------------------------------------------------------------------------

    def _add_chips(self) -> None:
        """Lay the rules out as a row of chips along the bottom: one icon and a few words
        each."""
        if self.setup.training:
            return
        left = PREVIEW.left - FRAME_PAD
        for text in rule_chips(self.setup):
            first = text.split()[0]
            icon = CHIP_ICONS.get(first, "burst")
            width = theme.ICON_SIZE + 3 * theme.GAP + text_width(text)
            rect = Rect(left, CHIP_BOTTOM, width, CHIP_HEIGHT)
            chip = Picture(self.ui, rect)
            chip.show(
                ("stage-chip", width, CHIP_HEIGHT),
                lambda width=width: kit_art.filled(
                    kit_art.shape_mask(width, CHIP_HEIGHT, theme.SMALL_CORNER),
                    theme.PANEL_DEEP,
                    theme.PANEL_BORDER,
                ),
            )
            self.chips.append(chip)
            self.ui.icon(icon, left + theme.GAP, CHIP_BOTTOM + 3, theme.HEADING)
            self.ui.write(
                text, left + theme.ICON_SIZE + 2 * theme.GAP, CHIP_BOTTOM + 4, TextSize.BODY
            )
            left += width + CHIP_GAP

    # --- state -----------------------------------------------------------------------------

    @property
    def selected(self) -> str:
        """The stage id under the cursor."""
        return self.stage_ids[self.cursor]

    @property
    def pool(self) -> list[str]:
        """The stages Random may pick."""
        return self.setup.pool(list(self.stages))

    def toggle_pool(self, stage_id: str) -> None:
        """Put a stage in the random pool or take it out (never the last one), and save it
        with the rules, which share the pool."""
        if stage_id == RANDOM_STAGE or self.setup.training:
            return
        before = self.setup.random_pool
        self.setup = toggle_pool(self.setup, stage_id, list(self.stages))
        if self.setup.random_pool != before:
            self.audio.play("ui_pick")
            self.flow.set_rules(self.setup)
        else:
            self.audio.play("ui_back")

    def act(self, device: str, action: MenuAction) -> None:
        """Move the cursor, toggle the highlighted stage in the random pool, fight, or go
        back."""
        if action in (MenuAction.LEFT, MenuAction.RIGHT, MenuAction.UP, MenuAction.DOWN):
            self.cursor = stage_info.move_in_grid(self.cursor, action, len(self.stage_ids))
        elif action is MenuAction.EXTRA:
            self.toggle_pool(self.selected)
        elif action is MenuAction.CONFIRM:
            self.flow.begin_match(replace(self.setup, stage=self.selected))
        elif action is MenuAction.BACK:
            self.flow.show_character_select(self.setup)

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the stage tile under the mouse."""
        for index, rect in enumerate(self.tile_rects):
            if rect.contains(x, y):
                self.cursor = index
                return True
        return False

    def click(self, x: int, y: int) -> None:
        """A click on a tile's box toggles it in the pool; on a tile, fights there."""
        for index, box in enumerate(self.checkboxes):
            if box is not None and box.rect.inset(-2).contains(x, y):
                self.cursor = index
                self.toggle_pool(self.stage_ids[index])
                return
        super().click(x, y)

    # --- drawing ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Show the stage under the cursor and mark the pool."""
        ticks = self.flow.menu_ticks
        if self.cursor != self._shown_cursor:
            self._shown_cursor = self.cursor
            self._changed_tick = ticks
            self._show_stage()
        slide = anim.slide(ticks, self._changed_tick, SLIDE_TICKS, SLIDE_PIXELS, 0)
        self.preview.sprite.center_x = PREVIEW.left + PREVIEW.width / 2 + slide
        self.preview.sprite.alpha = round(
            255 * anim.progress(ticks, self._changed_tick, SLIDE_TICKS)
        )
        pool = self.pool
        for index, (stage_id, rect) in enumerate(zip(self.stage_ids, self.tile_rects, strict=True)):
            focused = index == self.cursor
            ramp = FOCUS_RAMP if focused else None
            self.tile_backs[index].show(
                ("stage-tile", rect.width, rect.height, ramp),
                lambda rect=rect, ramp=ramp: select_art.roster_tile(rect.width, rect.height, ramp),
            )
            self.tile_names[index].color = theme.FOCUS if focused else theme.TEXT
            box = self.checkboxes[index]
            if box is not None:
                box.set(stage_id in pool, focused)
        self.focus.show(self.tile_rects[self.cursor], ticks)
        if not self.setup.training:
            count = stage_info.pool_text(pool, list(self.stages))
            self.pool_label.text = f"RANDOM POOL {count}"
            self.pool_hint.text = hint_text(
                "{grab}: in / out", device_labels(self.flow.settings, self.active_device)
            )

    def _show_stage(self) -> None:
        """Put the picture, name and facts of the stage under the cursor on screen."""
        stage_id = self.selected
        self.banner.show(
            ("stage-banner", BANNER.width, BANNER.height),
            lambda: select_art.name_plate(BANNER.width, BANNER.height, theme.FOCUS),
        )
        if stage_id == RANDOM_STAGE:
            pool = tuple(self.pool)
            self.preview.show(
                ("stage-preview-random", pool),
                lambda: random_mosaic(self.pictures, pool, (PREVIEW.width, PREVIEW.height)),
            )
            self.name_label.text = "RANDOM"
            self.description.text = "A stage from the random pool, picked as the match starts."
            self.music_label.text = "each stage's own song"
            self.size_label.text = f"{len(pool)} STAGE{'' if len(pool) == 1 else 'S'}"
            return
        stage = self.stages[stage_id]
        picture = self.pictures[stage_id]
        self.preview.show(("stage-preview", stage_id), lambda: picture)
        self.name_label.text = stage.display_name.upper()
        self.description.text = stage_info.describe(stage)
        self.music_label.text = stage_info.music_line(stage, self.titles)
        self.size_label.text = stage_info.size_line(stage)


def random_mosaic(
    pictures: dict[str, Image.Image], pool: tuple[str, ...], size: tuple[int, int]
) -> Image.Image:
    """Return the Random preview: every stage as a small picture, those outside the pool
    darkened."""
    width, height = size
    image = Image.new("RGBA", size, (*theme.INK, 255))
    names = list(pictures)
    rows = -(-len(names) // MOSAIC_COLUMNS)
    gap = 6
    cell_w = (width - gap * (MOSAIC_COLUMNS + 1)) // MOSAIC_COLUMNS
    cell_h = (height - gap * (rows + 1)) // max(rows, 1)
    for index, name in enumerate(names):
        row, column = divmod(index, MOSAIC_COLUMNS)
        small = stage_preview.thumbnail(pictures[name], (cell_w, cell_h))
        if name not in pool:
            veil = Image.new("RGBA", small.size, (0, 0, 0, 0))
            for y in range(small.height):
                for x in range(small.width):
                    if select_art.lit(x, y, 0.75):
                        veil.putpixel((x, y), (*theme.INK, 255))
            small.alpha_composite(veil)
        image.alpha_composite(small, (gap + column * (cell_w + gap), gap + row * (cell_h + gap)))
    dice = icon_image("dice")
    if dice is not None and len(names) < rows * MOSAIC_COLUMNS:
        row, column = divmod(len(names), MOSAIC_COLUMNS)
        big = kit_art.tint(dice, theme.FOCUS).resize(
            (dice.width * DICE_SCALE, dice.height * DICE_SCALE), Image.Resampling.NEAREST
        )
        x = gap + column * (cell_w + gap) + (cell_w - big.width) // 2
        y = gap + row * (cell_h + gap) + (cell_h - big.height) // 2
        image.alpha_composite(big, (x, y))
    return image


assert GRID_TOP <= NATIVE_H - theme.HEADER_HEIGHT
