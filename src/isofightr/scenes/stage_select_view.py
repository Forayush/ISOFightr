"""The stage select screen: the stage is the screen.

Plan note "13 - Game Modes UI and Flow" ("Stage select", decisions D-061, D-063 and D-072).
The stage under the cursor fills the screen, drawn by the battle's own renderer from its
backdrop and its real tiles with the spawns marked (:mod:`isofightr.render.stage_preview`):
first its picture, then, once the cursor has rested on it, the stage itself, live. Along the
bottom, one strip of stage tiles that scrolls sideways around the cursor, each with a box
that says whether Random may pick it (grab toggles it, and the Rules screen shows the same
pool) and a badge for a stage with a mechanic; Random is the last tile and is resolved when
the match starts. Over the strip, the stage's name in the logo's lettering and one slab with
its description, its song and its size; the rules of the match as chips at the top.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render import stage_preview
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import stage_info
from isofightr.scenes.menus import MenuView
from isofightr.scenes.rules_model import rule_chips, toggle_pool
from isofightr.scenes.setup import RANDOM_STAGE, MatchSetup
from isofightr.sim.stage import Stage
from isofightr.ui import font, kit_art, logo, select_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import ARROW_LEFT, ARROW_RIGHT, TextSize, text_width
from isofightr.ui.hints import device_labels, hint_text
from isofightr.ui.menu import MenuAction
from isofightr.ui.pixel_text import GlyphAtlas
from isofightr.ui.widgets import (
    Checkbox,
    FocusFrame,
    Picture,
    SlideGroup,
    UiLayer,
    add_slab,
    slab_face,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

STAGE_TILE = (58, 42)
"""A tile of the strip: the stage's thumbnail over its name."""
TILE_GAP = 4
THUMB = (54, 29)
NAME_STRIP = 10
CHECK_SIZE = 9
STRIP_LEFT = 12
STRIP_BOTTOM = 22
"""The strip's tiles stand on this row, just over the prompts."""
HIDDEN_SHIFT = -2000
"""A tile scrolled out of view is parked this far down, off the screen."""
INFO = Rect(12, 70, 616, 38)
"""The slab over the strip: the stage's description, then its song, size and the pool."""
NAME_BOTTOM = INFO.top + 4
"""The stage's name, in the logo's lettering, stands on the slab."""
NAME_SCALE = 2
NAME_DEPTH = 4
CHIP_HEIGHT = 18
CHIP_GAP = 4
CHIP_ICONS = {
    "STOCK": "stock",
    "TIME": "clock",
    "TEAMS": "team",
    "START": "percent",
    "HAZARDS": "bolt",
}
"""Which icon a rules chip carries, by its first word (the launch rate gets ``burst``)."""
LIVE_REST_TICKS = 12
"""The live stage replaces its picture once the cursor has rested this long on it."""
SHUFFLE_TICKS = 40
"""On Random, the picture changes to another stage of the pool this often."""
FOCUS_RAMP = theme.player_ramp(2)
"""The golds: the backing of the tile under the cursor, to go with the focus frame."""


class StageSelectView(MenuView):
    """Pick the stage, or Random from the pool, and fight."""

    station = "ring"
    """The Isle is not drawn here (the stage is); the camera waits at the ring for the way
    back to character select."""
    surface = theme.STONE

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow, setup: MatchSetup) -> None:
        """Draw every stage's picture (once a session), lay out the strip, and put the
        cursor on the setup's stage."""
        super().__init__(pixel_buffer, flow)
        self.setup = setup
        self.stages: dict[str, Stage] = {name: load_stage(name) for name in list_stage_ids()}
        self.stage_ids = [*self.stages, RANDOM_STAGE]
        self.cursor = self.stage_ids.index(setup.stage) if setup.stage in self.stage_ids else 0
        self.titles = stage_info.load_music_titles()
        self.pictures = {
            name: stage_preview.stage_picture(self.window, stage, stage_preview.PREVIEW_SIZE)
            for name, stage in self.stages.items()
        }
        self.live = stage_preview.LivePreview(pixel_buffer)
        """The stage under the cursor, drawn as it is once the cursor has rested on it."""
        self.live_ticks = 0
        """Frames the live stage has run: its clouds drift and its platforms move by it."""
        self._shown_cursor = -1
        self._changed_tick = 0
        self.first = 0
        """The tile at the left end of the strip."""

        # The stage's picture is not part of the screen's own layer: the layer is what
        # stands over the stage (and what the coverage test measures).
        self.scenery = UiLayer(GlyphAtlas())
        self.preview = Picture(self.scenery, Rect(0, 0, NATIVE_W, NATIVE_H))

        self.header("Training: stage" if setup.training else "Stage select", "stage")
        ui = self.ui
        add_slab(ui, INFO)
        face = slab_face(INFO)
        self.name_banner = Picture(ui, Rect(STRIP_LEFT, NAME_BOTTOM, 1, 1))
        self.name_label = ui.write("", 0, 0, TextSize.TITLE)
        """The stage's name as text (what the banner shows in the logo's lettering)."""
        self.name_label.visible = False
        surface = self.surface
        left = face.left + theme.PAD
        self.description = ui.write(
            "", left, face.top - 16, TextSize.TEXT, surface.text, shadow=False
        )
        info_bottom = face.bottom + 5
        ui.icon("speaker", left, info_bottom + 2, surface.text_muted)
        self.music_label = ui.write(
            "", left + 16, info_bottom - 3, TextSize.TEXT, surface.text_muted, shadow=False
        )
        self.size_icon = ui.icon("stage", left + 210, info_bottom + 2, surface.text_muted)
        self.size_label = ui.write(
            "", left + 226, info_bottom - 3, TextSize.TEXT, surface.text_muted, shadow=False
        )
        self.pool_label = ui.write(
            "", face.right - theme.PAD, face.top - 16, TextSize.TEXT, surface.text, "right",
            shadow=False,
        )  # fmt: skip
        self.pool_hint = ui.write(
            "", face.right - theme.PAD, info_bottom - 3, TextSize.TEXT, surface.text_muted,
            "right", shadow=False,
        )  # fmt: skip

        self.home_rects = [
            Rect(STRIP_LEFT + index * (STAGE_TILE[0] + TILE_GAP), STRIP_BOTTOM, *STAGE_TILE)
            for index in range(len(self.stage_ids))
        ]
        """Where each tile is with the strip scrolled to its start."""
        self.tile_rects = list(self.home_rects)
        """Where each tile is now (a tile scrolled out of view is off the screen)."""
        self.groups: list[SlideGroup] = []
        self.tile_backs: list[Picture] = []
        self.checkboxes: list[Checkbox | None] = []
        self.tile_names = []
        self.badges: list[str] = []
        """What each tile says about its stage's mechanics: "", "on" or "off"."""
        for stage_id, rect in zip(self.stage_ids, self.home_rects, strict=True):
            with SlideGroup(ui) as group:
                self.groups.append(group)
                self.tile_backs.append(Picture(ui, rect))
                thumb_left = rect.left + (rect.width - THUMB[0]) // 2
                thumb_bottom = rect.top - 2 - THUMB[1]
                if stage_id == RANDOM_STAGE:
                    ui.write(
                        "?", rect.left + rect.width // 2, thumb_bottom + 6, TextSize.DISPLAY,
                        theme.MIST, "centre", shadow=True,
                    )  # fmt: skip
                    ui.icon("dice", thumb_left + 3, thumb_bottom + 3, theme.MIST)
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
                name = font.fit(name, strip.width - 2, TextSize.SMALL)
                self.tile_names.append(
                    ui.write_in(strip, name, TextSize.SMALL, theme.WHITE, shadow=False, pad=0)
                )
                box = None
                if stage_id != RANDOM_STAGE and not setup.training:
                    box = Checkbox(
                        ui, rect.right - CHECK_SIZE - 3, rect.top - CHECK_SIZE - 3, CHECK_SIZE
                    )
                self.checkboxes.append(box)
                mark = (
                    ""
                    if stage_id == RANDOM_STAGE
                    else stage_info.badge(self.stages[stage_id], setup.stage_hazards)
                )
                self.badges.append(mark)
                if mark:
                    spot = Rect(rect.left + 3, rect.top - CHECK_SIZE - 3, CHECK_SIZE, CHECK_SIZE)
                    Picture(ui, spot).show(
                        ("stage-badge", CHECK_SIZE, mark),
                        lambda mark=mark: kit_art.mechanic_badge(CHECK_SIZE, mark == "on"),
                    )
        self.box_rects: list[Rect | None] = [
            None if box is None else box.rect for box in self.checkboxes
        ]
        """Where each tile's pool box is now."""
        middle = STRIP_BOTTOM + STAGE_TILE[1] // 2 - 6
        self.more_left = ui.write("", 3, middle, TextSize.BODY, theme.WHITE, shadow=True)
        self.more_right = ui.write(
            "", NATIVE_W - 3, middle, TextSize.BODY, theme.WHITE, "right", shadow=True
        )
        self.focus = FocusFrame(ui)
        self.chips: list[Picture] = []
        self._add_chips()
        hint = "" if setup.training else "   {grab}: random pool"
        self.footer(f"{{stick}}: stage   {{attack}}: fight{hint}   {{special}}: back")
        self.refresh()

    # --- layout ----------------------------------------------------------------------------

    def _add_chips(self) -> None:
        """Lay the rules out as a row of chips at the top right: one icon and a few words
        each, on small stone blocks."""
        if self.setup.training:
            return
        texts = rule_chips(self.setup)
        widths = [theme.ICON_SIZE + 3 * theme.GAP + text_width(text) for text in texts]
        left = NATIVE_W - theme.MARGIN - sum(widths) - CHIP_GAP * (len(widths) - 1)
        bottom = NATIVE_H - theme.HEADER_HEIGHT + (theme.HEADER_HEIGHT - CHIP_HEIGHT) // 2
        for text, width in zip(texts, widths, strict=True):
            first = text.split()[0]
            icon = CHIP_ICONS.get(first, "burst")
            rect = Rect(left, bottom, width, CHIP_HEIGHT)
            chip = Picture(self.ui, rect)
            chip.show(
                ("stage-chip", width, CHIP_HEIGHT),
                lambda width=width: kit_art.block_button(width, CHIP_HEIGHT, surface=theme.STONE),
            )
            self.chips.append(chip)
            self.ui.icon(icon, left + theme.GAP, bottom + theme.LIP + 1, theme.INK)
            self.ui.write(
                text, left + theme.ICON_SIZE + 2 * theme.GAP, bottom + theme.LIP,
                TextSize.BODY, theme.INK, shadow=False,
            )  # fmt: skip
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

    @property
    def shown_stage(self) -> str:
        """The stage whose picture is on show: the cursor's, or on Random one of the pool
        in turn."""
        if self.selected != RANDOM_STAGE:
            return self.selected
        pool = self.pool
        return pool[(self.flow.menu_ticks // SHUFFLE_TICKS) % len(pool)]

    @property
    def live_shown(self) -> bool:
        """Whether the stage on show is drawn live (rather than as its picture)."""
        return self.selected != RANDOM_STAGE and self.live.ready(self.selected)

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
            self.cursor = stage_info.move_in_strip(self.cursor, action, len(self.stage_ids))
        elif action is MenuAction.EXTRA:
            self.toggle_pool(self.selected)
        elif action is MenuAction.CONFIRM:
            self.flow.begin_match(replace(self.setup, stage=self.selected))
        elif action is MenuAction.BACK:
            self.flow.show_character_select(self.setup, wipe=True)

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the stage tile under the mouse."""
        for index, rect in enumerate(self.tile_rects):
            if rect.contains(x, y):
                self.cursor = index
                return True
        return False

    def click(self, x: int, y: int) -> None:
        """A click on a tile's box toggles it in the pool; on a tile, fights there."""
        for index, box in enumerate(self.box_rects):
            if box is not None and box.inset(-2).contains(x, y):
                self.cursor = index
                self.toggle_pool(self.stage_ids[index])
                return
        super().click(x, y)

    def tick(self) -> None:
        """Run the menu; once the cursor has rested, build the stage's live preview (never
        on a tick the cursor moved: the picture already shows the same frame, so the build
        does not show), and let the live stage run."""
        super().tick()
        if self.window.current_view is not self:
            return
        rested = self.flow.menu_ticks - self._changed_tick >= LIVE_REST_TICKS
        selected = self.selected
        if rested and selected != RANDOM_STAGE and not self.live.ready(selected):
            self.live.build(self.stages[selected])
            self.live_ticks = 0
        self.live_ticks += 1

    # --- drawing ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Show the stage under the cursor and mark the pool."""
        ticks = self.flow.menu_ticks
        if self.cursor != self._shown_cursor:
            self._shown_cursor = self.cursor
            self._changed_tick = ticks
            self._show_stage()
        if self.selected == RANDOM_STAGE:
            shown = self.shown_stage
            picture = self.pictures[shown]
            self.preview.show(("stage-preview", shown), lambda: picture)
        self._scroll()
        pool = self.pool
        for index, (stage_id, rect) in enumerate(zip(self.stage_ids, self.home_rects, strict=True)):
            focused = index == self.cursor
            ramp = FOCUS_RAMP if focused else None
            self.tile_backs[index].show(
                ("stage-tile", rect.width, rect.height, ramp),
                lambda rect=rect, ramp=ramp: select_art.roster_tile(rect.width, rect.height, ramp),
            )
            self.tile_names[index].color = theme.FOCUS if focused else theme.WHITE
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

    def _scroll(self) -> None:
        """Bring the cursor's tile into view: slide the tiles that show to their places and
        park the others off the screen."""
        count = len(self.stage_ids)
        shown_count = stage_info.STRIP_SHOWN
        self.first = stage_info.strip_first(self.cursor, self.first, count, shown_count)
        shift = self.first * (STAGE_TILE[0] + TILE_GAP)
        for index, group in enumerate(self.groups):
            shown = self.first <= index < self.first + shown_count
            dx, dy = (-shift, 0) if shown else (0, HIDDEN_SHIFT)
            group.offset(dx, dy)
            home = self.home_rects[index]
            self.tile_rects[index] = Rect(home.left + dx, home.bottom + dy, *STAGE_TILE)
            box = self.checkboxes[index]
            if box is not None:
                self.box_rects[index] = Rect(
                    box.rect.left + dx, box.rect.bottom + dy, box.rect.width, box.rect.height
                )
        self.more_left.text = ARROW_LEFT if self.first > 0 else ""
        right = self.first + shown_count < count
        self.more_right.text = ARROW_RIGHT if right else ""

    def _show_stage(self) -> None:
        """Put the picture, name and facts of the stage under the cursor on screen."""
        stage_id = self.selected
        if stage_id == RANDOM_STAGE:
            name = "RANDOM"
            pool = self.pool
            self.description.text = "A stage from the random pool, picked as the match starts."
            self.music_label.text = "Each stage's own song"
            self.size_label.text = f"{len(pool)} STAGE{'' if len(pool) == 1 else 'S'}"
        else:
            stage = self.stages[stage_id]
            picture = self.pictures[stage_id]
            self.preview.show(("stage-preview", stage_id), lambda: picture)
            name = stage.display_name.upper()
            self.description.text = stage_info.describe(stage)
            self.music_label.text = stage_info.music_line(stage, self.titles)
            self.size_label.text = stage_info.size_line(stage)
        self.name_label.text = name
        self.name_banner.show(
            ("stage-name", name),
            lambda: logo.build_logo(name, NAME_SCALE, depth=NAME_DEPTH),
        )
        sprite = self.name_banner.sprite
        sprite.position = (
            STRIP_LEFT + sprite.width / 2,
            NAME_BOTTOM + sprite.height / 2,
        )

    def on_draw(self) -> None:
        """The stage under the cursor (live once it is built, its picture until then), then
        the screen over it, at native resolution; then upscale it to the window."""
        self.clear()
        with self.pixel_buffer.drawing(theme.BACKGROUND):
            if not (
                self.live_shown
                and self.live.draw(
                    self.stages[self.selected], self.live_ticks, self.setup.stage_hazards
                )
            ):
                self.scenery.draw()
            self.ui.draw()
            self.draw_fade()
        self.blit_to_window()


assert STRIP_LEFT + stage_info.STRIP_SHOWN * (STAGE_TILE[0] + TILE_GAP) - TILE_GAP <= NATIVE_W
assert STRIP_BOTTOM + STAGE_TILE[1] < INFO.bottom
