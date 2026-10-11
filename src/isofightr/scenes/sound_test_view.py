"""The sound test: a jukebox for every song and sound effect (decision D-063).

Plan note "14 - Audio" ("Sound test"). Opened from Settings. Two lists, MUSIC and SOUNDS
(left and right change between them); confirm plays the row under the cursor, back stops
what is playing and, with nothing playing, leaves. What it lists and says is
:mod:`isofightr.scenes.sound_test_model`.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from isofightr.config import AUDIO_MENU_SONG, AUDIO_VICTORY_SONG, NATIVE_W
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.scenes import sound_test_model as model
from isofightr.scenes.menus import MenuView
from isofightr.ui import kit_art, theme
from isofightr.ui.font import TextSize
from isofightr.ui.hud_layout import Rect
from isofightr.ui.menu import MenuAction
from isofightr.ui.widgets import Picture, Tab, TextLabel, add_panel

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LIST = Rect(24, 34, 300, 288)
INFO = Rect(336, 174, NATIVE_W - 336 - 24, 148)
TAB_HEIGHT = 20
ROW = 20
ROW_GAP = 2
BARS = 9
BAR_WIDTH = 8
BAR_GAP = 4
BAR_HEIGHT = 34
BAR_TICKS = 7
"""How long one swing of a level bar takes, in ticks (it only says "something is playing")."""
SOUND_CHECK_SONG = "sound_check"
"""The tune that plays each new instrument by itself (decision D-063)."""
FOOTER = "{stick}: pick, change list   {attack}: play   {special}: stop, then back"


class SoundTestView(MenuView):
    """Lists the game's music and sounds and plays what is picked."""

    def __init__(self, pixel_buffer: PixelBuffer, flow: GameFlow) -> None:
        """Read the audio manifest and lay the two lists out."""
        super().__init__(pixel_buffer, flow)
        self.dim = None
        manifest = model.load_manifest()
        uses = {AUDIO_MENU_SONG: "The menus", AUDIO_VICTORY_SONG: "The results"}
        for stage_id in list_stage_ids():
            stage = load_stage(stage_id)
            if stage.music:
                uses[stage.music] = stage.display_name
        uses.setdefault(SOUND_CHECK_SONG, "The sound test")
        self.tracks = {
            model.MUSIC: model.music_tracks(manifest, uses),
            model.SOUNDS: model.sound_tracks(manifest),
        }
        self.tab = model.MUSIC
        self.cursors = dict.fromkeys(model.TABS, 0)
        self.firsts = dict.fromkeys(model.TABS, 0)
        self.playing: model.Track | None = None
        """The song this screen started, until it is stopped."""
        self.header("SOUND TEST", "speaker")
        add_panel(self.ui, LIST)
        add_panel(self.ui, INFO)

        tab_width = (LIST.width - 2 * theme.GAP) // len(model.TABS)
        self.tabs = {
            name: Tab(
                self.ui,
                Rect(
                    LIST.left + theme.GAP + index * tab_width,
                    LIST.top - theme.GAP - TAB_HEIGHT,
                    tab_width,
                    TAB_HEIGHT,
                ),
                name.upper(),
                theme.FOCUS,
                name == self.tab,
            )
            for index, name in enumerate(model.TABS)
        }
        self.row_rects = [
            Rect(
                LIST.left + theme.GAP,
                LIST.top - theme.GAP - TAB_HEIGHT - theme.GAP - (index + 1) * ROW + ROW_GAP,
                LIST.width - 2 * theme.GAP,
                ROW - ROW_GAP,
            )
            for index in range(model.VISIBLE_ROWS)
        ]
        self._strips = [Picture(self.ui, rect) for rect in self.row_rects]
        self._names: list[TextLabel] = []
        self._lengths: list[TextLabel] = []
        for rect in self.row_rects:
            self._names.append(self.ui.write_in(rect, "", align="left"))
            self._lengths.append(
                self.ui.write_in(rect, "", TextSize.BODY, theme.TEXT_MUTED, "right")
            )
        self.count_label = self.ui.write(
            "",
            LIST.right - theme.PAD,
            LIST.bottom + theme.GAP + 2,
            TextSize.SMALL,
            theme.TEXT_MUTED,
            "right",
        )

        left = INFO.left + theme.PAD
        self.status = self.ui.write("", left, INFO.top - 18, TextSize.SMALL, theme.TEXT_MUTED)
        self.title = self.ui.write("", left, INFO.top - 42, TextSize.TITLE, theme.TEXT)
        self.facts = [
            self.ui.write("", left, INFO.top - 62 - index * 14, TextSize.BODY, theme.FOG)
            for index in range(model.FACT_LINES)
        ]
        bars_left = INFO.right - theme.PAD - BARS * (BAR_WIDTH + BAR_GAP) + BAR_GAP
        self.bars = [
            Picture(
                self.ui,
                Rect(
                    bars_left + index * (BAR_WIDTH + BAR_GAP),
                    INFO.bottom + theme.PAD,
                    BAR_WIDTH,
                    BAR_HEIGHT,
                ),
            )
            for index in range(BARS)
        ]
        self.bar_levels = [0] * BARS
        """How many pixels of each level bar are lit (0 while nothing plays)."""
        self.footer(FOOTER)
        self.refresh()

    # --- state ---------------------------------------------------------------------------

    @property
    def listed(self) -> list[model.Track]:
        """The rows of the tab that is showing."""
        return self.tracks[self.tab]

    @property
    def selected(self) -> model.Track | None:
        """The row under the cursor."""
        rows = self.listed
        return rows[self.cursors[self.tab]] if rows else None

    def act(self, device: str, action: MenuAction) -> None:
        """Move, change list, play, or stop and leave."""
        if action in (MenuAction.UP, MenuAction.DOWN):
            step = 1 if action is MenuAction.DOWN else -1
            self.cursors[self.tab] = model.moved(self.cursors[self.tab], step, len(self.listed))
        elif action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = 1 if action is MenuAction.RIGHT else -1
            self.tab = model.TABS[(model.TABS.index(self.tab) + step) % len(model.TABS)]
        elif action is MenuAction.CONFIRM:
            self.play_selected()
        elif action is MenuAction.BACK:
            if self.playing is not None:
                self.stop()
            else:
                self.flow.show_settings()

    def play_selected(self) -> None:
        """Play the row under the cursor: a song takes over from whatever music is on, a
        sound effect plays over it."""
        track = self.selected
        if track is None:
            return
        if track.kind == model.MUSIC:
            self.audio.stop_music()
            self.audio.play_music(track.id, track.loops)
            self.playing = track
        else:
            self.audio.play(track.id)

    def stop(self) -> None:
        """Stop the song this screen started."""
        self.audio.stop_music()
        self.playing = None

    def hover(self, x: int, y: int) -> bool:
        """Put the cursor on the row under the mouse, or change to the tab under it."""
        for name, tab in self.tabs.items():
            if _inside(tab.rect, x, y):
                self.tab = name
                return False  # a click on a tab changes list; it does not play anything
        for index, rect in enumerate(self.row_rects):
            row = self.firsts[self.tab] + index
            if _inside(rect, x, y) and row < len(self.listed):
                self.cursors[self.tab] = row
                return True
        return False

    # --- drawing ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Show the list from the cursor's row, and what is under it or playing."""
        rows, cursor = self.listed, self.cursors[self.tab]
        first = model.first_shown(cursor, self.firsts[self.tab], len(rows))
        self.firsts[self.tab] = first
        for name, tab in self.tabs.items():
            tab.active = name == self.tab
        for index, rect in enumerate(self.row_rects):
            row = first + index
            track = rows[row] if row < len(rows) else None
            focused = track is not None and row == cursor
            if track is None:
                self._strips[index].hide()
            else:
                self._strips[index].show(
                    ("sound-row", rect.width, rect.height, focused),
                    lambda rect=rect, focused=focused: kit_art.list_row(
                        rect.width, rect.height, focused
                    ),
                )
            playing = track is not None and track == self.playing
            self._names[index].text = "" if track is None else track.title.upper()
            self._names[index].color = (
                theme.FOCUS if focused else theme.LEAF if playing else theme.TEXT
            )
            self._lengths[index].text = "" if track is None else track.facts[-1]
        self.count_label.text = model.position(cursor, len(rows))

        shown = self.playing if self.playing is not None else self.selected
        self.status.text = "NOW PLAYING" if self.playing is not None else "UNDER THE CURSOR"
        self.status.color = theme.LEAF if self.playing is not None else theme.TEXT_MUTED
        self.title.text = "" if shown is None else shown.title.upper()
        facts = () if shown is None else shown.facts
        for index, label in enumerate(self.facts):
            label.text = facts[index] if index < len(facts) else ""
        tick = self.flow.menu_ticks
        for index, bar in enumerate(self.bars):
            lit = 0
            if self.playing is not None:
                swing = math.sin(tick / BAR_TICKS + index * 1.7) * math.sin(tick / 23 + index)
                lit = round((BAR_HEIGHT - 2) * (0.2 + 0.8 * abs(swing)))
            self.bar_levels[index] = lit
            bar.show(
                ("level-bar", BAR_WIDTH, BAR_HEIGHT, lit),
                lambda lit=lit: kit_art.level_bar(BAR_WIDTH, BAR_HEIGHT, lit),
            )


def _inside(rect: Rect, x: float, y: float) -> bool:
    return rect.left <= x < rect.right and rect.bottom <= y < rect.top
