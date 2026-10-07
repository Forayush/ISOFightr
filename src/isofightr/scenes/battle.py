"""The battle scene: runs a ``Match`` at a fixed 60 Hz and draws it.

Implements "Game loop: fixed 60 Hz simulation" in the plan note "02 - Technical
Architecture": each tick polls one ``InputFrame`` per player, steps the sim, and lets
presentation react to ``match.events``. Nothing here changes sim state except by feeding it
input, and through the two training tools the sim itself offers (``Match.set_damage`` and
``Match.reload_characters``).

Match flow (plan note 13): the countdown, the clock, "GAME!" with a short slow-motion, and
then the results screen are all driven by ``match.phase``; this scene only shows them.
Escape or Enter opens the pause menu, which in training mode holds the training tools.

Debug keys (plan note 13, "Training mode"): F1 hitboxes and hurtboxes, F2 fighter info,
F3 stage overlay, F5 pause, F6 advance one frame, F8 restart the match, F9 reload character
and move data from disk, C toggles the camera clamp, Z the stepped zoom, H hides the help
text. In training mode
``-`` and ``=`` change the dummies' damage by 10%, ``0`` resets it and Tab switches them
between standing still and their own controls. Player controls are in
:mod:`isofightr.input.devices`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import arcade

from isofightr.ai.controller import CpuController
from isofightr.ai.dummy import DummyBehavior, dummy_frame
from isofightr.ai.view import observe
from isofightr.audio.cues import MatchSounds, event_cues
from isofightr.config import (
    CPU_DEFAULT_LEVEL,
    CPU_MAX_LEVEL,
    CPU_MIN_LEVEL,
    NATIVE_H,
    NATIVE_W,
    Z_PX,
)
from isofightr.data.character_loader import load_character
from isofightr.data.replay_io import save_replay
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.data.validation import DataError
from isofightr.input.devices import (
    KEYBOARD_PREFIX,
    PAD_PREFIX,
    DeviceHub,
    InputSource,
)
from isofightr.input.keyboard import KeyLatch
from isofightr.render import placeholder_art as art
from isofightr.render.camera import FollowCamera, StepZoom, bounds_on_screen
from isofightr.render.debug_overlay import StageOverlay
from isofightr.render.effect_renderer import EffectRenderer
from isofightr.render.effects import BattleEffects
from isofightr.render.fighter_look import costume_for, fighter_look
from isofightr.render.ground_items import GroundItem, decal_items, projectile_items
from isofightr.render.hitbox_overlay import HitboxOverlay
from isofightr.render.iso import project, project_point
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.render.world_renderer import Overlay, WorldRenderer
from isofightr.scenes.setup import QUIT_HINT, MatchSetup, clock_text, countdown_text, quit_chord
from isofightr.scenes.ticked_view import TickedView
from isofightr.settings import KEYBOARD_ARROWS, KEYBOARD_SOLO, ZOOM_STEPPED, Settings
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.replay import Recorder, Replay
from isofightr.sim.rules import MatchPhase
from isofightr.sim.stage import Stage
from isofightr.ui import font, kit_art, theme
from isofightr.ui.focus import Rect
from isofightr.ui.font import ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT, TextSize
from isofightr.ui.hints import HELP_TEMPLATES, battle_help, device_labels, hint_text
from isofightr.ui.hud import CardInfo, DamageHud
from isofightr.ui.hud_extras import HudExtras
from isofightr.ui.hud_layout import (
    CAMERA_LIFT,
    GO_TICKS,
    HUD_BAND,
    pause_row_parts,
    tag_anchor,
    tag_text,
)
from isofightr.ui.hud_state import HudState
from isofightr.ui.input_display import input_lines
from isofightr.ui.menu import MENU_SOUNDS, Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.move_list import (
    build_move_list,
    page_columns,
)
from isofightr.ui.pixel_font import GLYPH_ADVANCE, GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel
from isofightr.ui.widgets import (
    HIGHLIGHT,
    Picture,
    TextBlock,
    TextLabel,
    UiLayer,
    add_panel,
    text_bottom,
)

if TYPE_CHECKING:
    from isofightr.scenes.flow import GameFlow

LOG = logging.getLogger(__name__)

KEY_HITBOXES = arcade.key.F1
KEY_FIGHTER_INFO = arcade.key.F2
KEY_OVERLAY = arcade.key.F3
KEY_PAUSE = arcade.key.F5
KEY_FRAME_ADVANCE = arcade.key.F6
KEY_RESET = arcade.key.F8
KEY_RELOAD = arcade.key.F9
KEY_INPUTS = arcade.key.F10
KEY_CAMERA_CLAMP = arcade.key.C
KEY_ZOOM = arcade.key.Z
KEY_HELP = arcade.key.H
KEY_DUMMY_DAMAGE_DOWN = arcade.key.MINUS
KEY_DUMMY_DAMAGE_UP = arcade.key.EQUAL
KEY_DUMMY_DAMAGE_RESET = arcade.key.KEY_0
KEY_DUMMY_CONTROL = arcade.key.TAB
KEYS_MENU = (arcade.key.ESCAPE, arcade.key.ENTER)
TAG_PLATE_PAD = 3
"""Pixels of plate around a name tag's text."""
TAG_PLATE_HEIGHT = 14

HUD_MARGIN = 4
HUD_CAPACITY = 104
LINE_HEIGHT = GLYPH_HEIGHT
DEBUG_HELP = (
    "F1 hitboxes  F2 info  F3 stage  F5 pause  F6 step  F8 restart  F9 reload  F10 inputs  "
    "Z zoom  H help"
)
HELP_LINES = (*HELP_TEMPLATES, DEBUG_HELP)
"""The help text's lines; the control lines are filled in with player 1's own bindings."""
TRAINING_HELP = "TRAINING  ESC menu  -/= dummy damage  0 reset damage  TAB dummy control"
HELP_BOTTOM = HUD_BAND + HUD_MARGIN
"""The help text (sandboxes) sits just above the player cards."""
INFO_LINES_PER_FIGHTER = 2
DUMMY_DAMAGE_STEP = 10.0
MESSAGE_TICKS = 180
"""How long a status message (such as the result of a reload) stays up."""
FIRST_DUMMY = 1
"""In training mode every player from this index on is a dummy."""
BODY_CENTRE_HEIGHT = art.BODY_HEIGHT / 2 / Z_PX
"""The camera tracks a fighter's middle rather than its feet, in units above the feet."""

FULL_PERCENT = 100
SUDDEN_DEATH_TEXT_FRAMES = 60
"""The first part of a sudden-death countdown says so instead of showing a number."""
GAME_SLOW_TICKS = 60
"""After the deciding KO the sim runs at a third of its speed for this many render ticks."""
GAME_SLOW_FACTOR = 3
GAME_HOLD_TICKS = 150
"""Ticks between "GAME!" and the results screen."""
PAUSE_PANEL_WIDTH = 300
PAUSE_HEADER = 30
"""Height of the pause panel's title bar."""
PAUSE_FOOT = 24
"""Room under the pause menu's rows for the controls line."""
MOVES_COLUMN_CAPACITY = 48
MOVES_MAX_ROWS = 18
MOVES_COLUMN_GAP = 12
MOVES_TITLE_CAPACITY = 100
SANDBOX_KEYBOARDS = (KEYBOARD_SOLO, KEYBOARD_ARROWS)
"""Keyboard layout of each player in a battle started without a setup (``InputSource``)."""

MENU_RESUME = "resume"
MENU_HELP = "help"
MENU_QUIT = "quit"
MENU_DUMMY = "dummy"
MENU_DAMAGE = "damage"
MENU_HITBOXES = "hitboxes"
MENU_INFO = "info"
MENU_RESET = "reset"
BATTLE_FADE_TICKS = 20
MENU_DUMMY_LEVEL = "dummy_level"
CPU_LEVEL_CHOICES = tuple(str(level) for level in range(CPU_MIN_LEVEL, CPU_MAX_LEVEL + 1))
MENU_MOVES = "moves"
ON_OFF = ("off", "on")


class BattleView(TickedView):
    """Runs the fixed 60 Hz loop over a match and draws the stage and fighters."""

    def __init__(
        self,
        pixel_buffer: PixelBuffer,
        stage: Stage,
        characters: Sequence[CharacterDef],
        seed: int = 0,
        max_ticks: int | None = None,
        training: bool = False,
        rules: MatchRules | None = None,
        flow: GameFlow | None = None,
        setup: MatchSetup | None = None,
        record: Path | None = None,
        replay: Replay | None = None,
        placeholder_art: bool = False,
        cpus: Sequence[int] | None = None,
        banks: Mapping[str, SpriteBank] | None = None,
    ) -> None:
        """Create the view. See :class:`TickedView` for ``pixel_buffer`` and ``max_ticks``.

        Args:
            stage: where the match is played.
            characters: one character per player.
            seed: the match seed.
            training: players 2 to 4 are dummies, and the pause menu has the training tools.
            rules: the match rules; by default endless stocks and no countdown (a sandbox).
            flow: the scene router to go to results or back to the menus with, if any.
            setup: what the menus chose, kept for "Rematch".
            placeholder_art: draw every fighter as the placeholder capsule, even characters
                that have sprites (tests that sample the capsule's pixels).
            record: file to save this match's replay to (never in training, whose tools
                change the match from outside).
            replay: a replay to play back instead of reading the players' devices.
            cpus: CPU level per player (0 = a person); by default the setup's.
        """
        super().__init__(pixel_buffer, max_ticks)
        self.stage = stage
        self.characters = list(characters)
        self.seed = seed
        self.training = training
        self.rules = rules or MatchRules(stocks=None)
        self.flow = flow
        self.setup = setup
        self.dummy = DummyBehavior.STAND if training else DummyBehavior.MANUAL
        self.dummy_level = CPU_DEFAULT_LEVEL
        # A match started from the menus fades in; a sandbox (and the tests) cuts in.
        self.fade_ticks = BATTLE_FADE_TICKS if flow is not None else 0
        self._sounds = MatchSounds()
        chosen = cpus if cpus is not None else (setup.cpus if setup is not None else ())
        self.cpu_levels = tuple(chosen) + (0,) * (len(self.characters) - len(chosen))
        self._cpus: dict[int, CpuController] = {}
        self._cpu_match: Match | None = None
        self.record_path = None if training else record
        self.replay = replay
        self.replay_matches: bool | None = None
        """Once a replay has played out: whether it ended on its recorded state."""
        self.recorder: Recorder | None = None
        self.placeholder_art = placeholder_art
        self.match = self._new_match()
        self.settings = flow.settings if flow is not None else Settings()
        # From the menus every player has the device it joined with; a sandbox match uses
        # the fixed default assignment (keyboards plus controllers in order).
        self.devices = tuple(setup.devices) if setup is not None and setup.devices else ()
        # A match from the menus reads the session's devices; a sandbox opens its own.
        self._owns_hub = flow is None
        self.hub = None
        if self.devices:
            self.hub = flow.hub() if flow is not None else DeviceHub(self.settings)
        self._menu_extras: list[frozenset[MenuAction] | None] | None = None
        self._start_tapped = False
        self._quit_chord = False
        self.inputs = None if self.devices else InputSource(len(self.characters))
        self._unplugged: set[str] = set()
        self.menu_input = MenuInput()
        # The loading screen hands over the sprites it has already opened and coloured.
        loaded = dict(banks) if banks is not None and not placeholder_art else None
        self.renderer = WorldRenderer(
            pixel_buffer, stage, self._load_banks() if loaded is None else loaded
        )
        self.camera = FollowCamera(limits=bounds_on_screen(stage.camera_bounds))
        self.zoom = StepZoom(enabled=self.settings.camera_zoom == ZOOM_STEPPED)
        self.camera.snap_to(self._camera_targets())
        self.effects = BattleEffects()
        self.effect_renderer = EffectRenderer()
        self.effect_renderer.plain_projectiles = placeholder_art
        self.hitboxes = HitboxOverlay()
        self.show_hitboxes = False
        self.show_overlay = False
        self.show_fighter_info = False
        self.show_inputs = False
        self.show_help = flow is None
        self.paused = False
        self.menu_open = False
        self._advance_one = False
        self._message = ""
        self._message_ticks = 0
        self._go_ticks = 0
        self._over_ticks = 0
        self._keys = KeyLatch()

        glyphs = GlyphAtlas()
        self.overlay = StageOverlay(stage, glyphs)
        self.hud = DamageHud(glyphs, self._card_infos())
        self.hud_state = HudState(names=self._feed_names())
        self.extras = HudExtras(self.hud.ramps, self._feed_names())
        self._text: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        controls = battle_help(device_labels(self.settings, self.move_list_device(0)))
        help_lines = [*controls, DEBUG_HELP, *([TRAINING_HELP] if training else [])]
        self._help_text = list(reversed(help_lines))
        self._help = [
            PixelLabel(glyphs, self._text, HUD_MARGIN, HELP_BOTTOM + row * LINE_HEIGHT, len(line))
            for row, line in enumerate(self._help_text)
        ]
        top = NATIVE_H - HUD_MARGIN - LINE_HEIGHT
        rows = len(self.characters) * (INFO_LINES_PER_FIGHTER + 1) + 1
        self._info_lines = [
            PixelLabel(glyphs, self._text, HUD_MARGIN, top - row * LINE_HEIGHT, HUD_CAPACITY)
            for row in range(rows)
        ]
        self.banner = self.extras.banner
        """The big text in the middle (``banner.text``): countdown, GO!, GAME!."""
        self.clock = self.extras.clock
        # The Rules screen's display options (decision D-061). Sandboxes and training show
        # the HUD and can always pause.
        versus = setup is not None and not training
        self.hud_display = setup.hud_display if versus and setup is not None else True
        self.score_display = setup.score_display if versus and setup is not None else False
        self.player_tags = setup.player_tags if versus and setup is not None else False
        self.can_pause = setup.pausing if versus and setup is not None else True
        self.tags_ui = UiLayer(glyphs)
        self._tag_plates: list[arcade.Sprite] = []
        for index, fighter in enumerate(self.match.fighters):
            color = theme.player_color(fighter.color_index)
            width = font.text_width(tag_text(index, self.cpu_levels[index])) + 2 * TAG_PLATE_PAD
            self._tag_plates.append(
                self.tags_ui.picture(
                    ("tag-plate", width, color),
                    lambda width=width, color=color: kit_art.tag_plate(
                        width, TAG_PLATE_HEIGHT, color
                    ),
                    0,
                    0,
                )
            )
        self._tags = [
            (
                self.tags_ui.write(
                    tag_text(index, self.cpu_levels[index]),
                    0,
                    0,
                    TextSize.BODY,
                    theme.player_color(fighter.color_index),
                    "centre",
                ),
                self.tags_ui.write(
                    ARROW_DOWN,
                    0,
                    0,
                    TextSize.SMALL,
                    theme.player_color(fighter.color_index),
                    "centre",
                ),
            )
            for index, fighter in enumerate(self.match.fighters)
        ]
        self.pause_menu = self._build_pause_menu()
        self.pause_ui = UiLayer(GlyphAtlas())
        self._build_pause_ui()
        self.move_list_player: int | None = None
        self.moves_ui = UiLayer(glyphs)
        self._build_moves_ui()

    def _new_match(self) -> Match:
        if self.record_path is not None:
            names = tuple(character.id for character in self.characters)
            self.recorder = Recorder(self.stage.id, names, self.seed, self.rules)
        return Match.create(self.stage, self.characters, self.seed, self.rules)

    def save_recording(self) -> None:
        """Write the replay of the match so far, if this match is being recorded."""
        if self.recorder is None or self.record_path is None or not self.recorder.inputs:
            return
        save_replay(self.record_path, self.recorder.finish(self.match))
        LOG.info("recorded %d ticks to %s", len(self.recorder.inputs), self.record_path)

    @property
    def dummies(self) -> bool:
        """Whether players 2 to 4 are run by a dummy behaviour instead of their devices."""
        return self.dummy is not DummyBehavior.MANUAL

    @dummies.setter
    def dummies(self, value: bool) -> None:
        self.dummy = DummyBehavior.STAND if value else DummyBehavior.MANUAL

    # --- pause menu ------------------------------------------------------------------------

    def _build_pause_menu(self) -> Menu:
        items = [MenuItem(MENU_RESUME, "Resume")]
        if self.training:
            behaviors = tuple(behavior.value for behavior in DummyBehavior)
            items += [
                MenuItem(MENU_DUMMY, "Dummy", behaviors, behaviors.index(self.dummy.value)),
                MenuItem(MENU_DAMAGE, ""),
                MenuItem(MENU_HITBOXES, "Hitboxes", ON_OFF),
                MenuItem(MENU_INFO, "Fighter info", ON_OFF),
                MenuItem(MENU_RESET, "Reset positions"),
                MenuItem(
                    MENU_DUMMY_LEVEL,
                    "Dummy CPU level",
                    CPU_LEVEL_CHOICES,
                    CPU_LEVEL_CHOICES.index(str(self.dummy_level)),
                ),
            ]
        items.append(MenuItem(MENU_MOVES, "Move list"))
        items.append(MenuItem(MENU_HELP, "Controls help", ON_OFF, int(self.show_help)))
        back = "Quit to character select" if self.flow is not None else "Quit"
        items.append(MenuItem(MENU_QUIT, back))
        return Menu(items)

    def _build_pause_ui(self) -> None:
        """The pause menu (decision D-061): the battle dimmed, a panel with a title bar, one
        strip per row (lit under the cursor, a setting's value at its right end with arrows
        while it is selected) and the controls along its foot."""
        ui = self.pause_ui
        rows = len(self.pause_menu.items)
        height = PAUSE_HEADER + rows * (theme.ROW_HEIGHT + 2) + PAUSE_FOOT
        rect = Rect((NATIVE_W - PAUSE_PANEL_WIDTH) // 2, (NATIVE_H - height) // 2,
                    PAUSE_PANEL_WIDTH, height)  # fmt: skip
        ui.picture(
            ("pause-veil", NATIVE_W, NATIVE_H),
            lambda: kit_art.filled(kit_art.shape_mask(NATIVE_W, NATIVE_H, 0), theme.DIM_OVERLAY),
            0,
            0,
        )
        add_panel(ui, rect)
        title = "TRAINING" if self.training else "PAUSED"
        ui.icon("pause", rect.left + theme.PAD, rect.top - 19, theme.HEADING)
        ui.write(title, rect.left + theme.PAD + 18, rect.top - 22, TextSize.TITLE, theme.HEADING)
        ui.picture(
            ("pause-rule", rect.width - 16),
            lambda: kit_art.divider(rect.width - 16),
            rect.left + 8,
            rect.top - PAUSE_HEADER + 4,
        )
        self._pause_strips: list[Picture] = []
        self._pause_labels: list[tuple[TextLabel, TextLabel]] = []
        top = rect.top - PAUSE_HEADER
        for row in range(rows):
            strip = Rect(rect.left + 8, top - (row + 1) * (theme.ROW_HEIGHT + 2), rect.width - 16,
                         theme.ROW_HEIGHT)  # fmt: skip
            self._pause_strips.append(Picture(ui, strip))
            bottom = text_bottom(strip, TextSize.BODY)
            self._pause_labels.append(
                (
                    ui.write("", strip.left + theme.PAD, bottom, TextSize.BODY),
                    ui.write(
                        "", strip.right - theme.PAD, bottom, TextSize.BODY, theme.TEXT, "right"
                    ),
                )
            )
        self._pause_hint = ui.write(
            "", rect.left + rect.width // 2, rect.bottom + 6, TextSize.BODY, theme.TEXT_MUTED,
            "centre",
        )  # fmt: skip

    def _sync_pause_rows(self) -> None:
        """Show the pause menu's rows as they are now."""
        menu = self.pause_menu
        for index, (item, strip, (label, value)) in enumerate(
            zip(menu.items, self._pause_strips, self._pause_labels, strict=True)
        ):
            focused = index == menu.cursor
            rect = strip.rect
            strip.show(
                ("pause-row", rect.width, rect.height, focused),
                lambda rect=rect, focused=focused: kit_art.list_row(
                    rect.width, rect.height, focused
                ),
            )
            name, shown = pause_row_parts(item)
            label.text = name.upper()
            label.color = theme.FOCUS if focused else theme.TEXT
            if shown and focused:
                shown = f"{ARROW_LEFT} {shown} {ARROW_RIGHT}"
            value.text = shown.upper()
            value.color = theme.FOCUS if focused else theme.TEXT_MUTED
        labels = device_labels(self.settings, self.move_list_device(0))
        self._pause_hint.text = hint_text(
            "{stick}: move   {attack}: pick   {special}: resume", labels
        )

    def _build_moves_ui(self) -> None:
        width = MOVES_COLUMN_CAPACITY * 2 * GLYPH_ADVANCE + MOVES_COLUMN_GAP + 32
        height = (MOVES_MAX_ROWS + 3) * (GLYPH_HEIGHT + 2) + 16
        left = (NATIVE_W - width) // 2
        bottom = (NATIVE_H - height) // 2
        top = bottom + height - GLYPH_HEIGHT - 8
        self.moves_ui.panel(0, 0, NATIVE_W, NATIVE_H, art.DIM_OVERLAY, art.DIM_OVERLAY)
        self.moves_ui.panel(left, bottom, width, height)
        self._moves_title = self.moves_ui.label(left + 16, top, MOVES_TITLE_CAPACITY, HIGHLIGHT)
        column_left = (
            left + 16,
            left + 16 + MOVES_COLUMN_CAPACITY * GLYPH_ADVANCE + MOVES_COLUMN_GAP,
        )
        self._moves_columns = [
            TextBlock(self.moves_ui, x, top - 6, MOVES_MAX_ROWS, MOVES_COLUMN_CAPACITY)
            for x in column_left
        ]

    def move_list_players(self) -> list[int]:
        """Return the players who get a move list page: everyone with a device (not the
        training dummies), or everyone in a battle started without a setup."""
        players = range(len(self.characters))
        if not self.devices:
            return list(players)
        with_device = [p for p in players if p < len(self.devices) and self.devices[p]]
        return with_device or [0]

    def move_list_device(self, player: int) -> str:
        """Return the device whose labels a player's move list shows."""
        if self.devices:
            return self.devices[player] if player < len(self.devices) else ""
        if player < len(SANDBOX_KEYBOARDS):
            return KEYBOARD_PREFIX + SANDBOX_KEYBOARDS[player]
        return f"{PAD_PREFIX}{player}"

    def move_list_lines(self, player: int) -> tuple[str, list[str], list[str]]:
        """Return the title and the two columns of a player's move list page."""
        device = self.move_list_device(player)
        labels = device_labels(self.settings, device)
        source = "keys" if device.startswith(KEYBOARD_PREFIX) else "gamepad"
        character = self.match.fighters[player].character
        sections = build_move_list(character.moveset, labels, self.match.rules.short_hop_macro)
        left, right = page_columns(sections, MOVES_COLUMN_CAPACITY)
        switch = "  < > player" if len(self.move_list_players()) > 1 else ""
        title = (
            f"P{player + 1} {character.display_name.upper()} MOVES ({source}){switch}  back: close"
        )
        return title, left, right

    def show_move_list(self, player: int) -> None:
        """Show a player's move list page over the pause menu."""
        self.move_list_player = player
        title, left, right = self.move_list_lines(player)
        self._moves_title.text = title
        self._moves_columns[0].set_lines(left)
        self._moves_columns[1].set_lines(right)

    def _move_list_action(self, action: MenuAction) -> None:
        players = self.move_list_players()
        assert self.move_list_player is not None
        if action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = 1 if action is MenuAction.RIGHT else -1
            index = players.index(self.move_list_player) if self.move_list_player in players else 0
            self.show_move_list(players[(index + step) % len(players)])
        elif action in (MenuAction.BACK, MenuAction.CONFIRM):
            self.move_list_player = None

    def request_pause(self) -> None:
        """A player asked to pause (Escape, Enter or a gamepad's Start): open the menu,
        unless the rules have pausing off."""
        if self.can_pause or self.match.phase is MatchPhase.OVER:
            self.open_menu()
        else:
            self.say(QUIT_HINT)

    def open_menu(self) -> None:
        """Pause and show the pause menu."""
        self.menu_open = True
        self.audio.play("ui_select")
        self.move_list_player = None
        self.pause_menu.cursor = 0
        self.menu_input.reset()
        self._sync_pause_menu()

    def close_menu(self) -> None:
        """Hide the pause menu and carry on."""
        self.menu_open = False

    def _sync_pause_menu(self) -> None:
        """Make the menu rows show the scene's current settings."""
        menu = self.pause_menu
        menu.item(MENU_HELP).index = int(self.show_help)
        if self.training:
            behaviors = [behavior.value for behavior in DummyBehavior]
            menu.item(MENU_DUMMY).index = behaviors.index(self.dummy.value)
            menu.item(MENU_HITBOXES).index = int(self.show_hitboxes)
            menu.item(MENU_INFO).index = int(self.show_fighter_info)
            menu.item(MENU_DUMMY_LEVEL).index = CPU_LEVEL_CHOICES.index(str(self.dummy_level))
            dummies = self.match.fighters[FIRST_DUMMY:]
            damage = dummies[0].damage if dummies else 0.0
            menu.item(MENU_DAMAGE).label = f"Dummy damage: < {damage:.0f}% >"

    def menu_action(self, action: MenuAction) -> None:
        """Handle one navigation action in the pause menu."""
        if MENU_SOUNDS[action]:
            self.audio.play(MENU_SOUNDS[action])
        if self.move_list_player is not None:
            self._move_list_action(action)
            return
        menu = self.pause_menu
        if action is MenuAction.BACK:
            self.close_menu()
            return
        if menu.selected.key == MENU_DAMAGE and action in (MenuAction.LEFT, MenuAction.RIGHT):
            step = -DUMMY_DAMAGE_STEP if action is MenuAction.LEFT else DUMMY_DAMAGE_STEP
            self.change_dummy_damage(step)
        chosen = menu.apply(action)
        if chosen == MENU_RESUME:
            self.close_menu()
        elif chosen == MENU_RESET:
            self.restart()
            self.close_menu()
        elif chosen == MENU_MOVES:
            self.show_move_list(self.move_list_players()[0])
        elif chosen == MENU_QUIT:
            self.quit_match()
        self.show_help = bool(menu.item(MENU_HELP).index)
        if self.training:
            self.dummy = DummyBehavior(menu.item(MENU_DUMMY).value)
            self.show_hitboxes = bool(menu.item(MENU_HITBOXES).index)
            self.show_fighter_info = bool(menu.item(MENU_INFO).index)
            self.dummy_level = int(menu.item(MENU_DUMMY_LEVEL).value)
        self._sync_pause_menu()

    def quit_match(self) -> None:
        """Leave the match: back to character select, or close the window in a sandbox."""
        if self.flow is not None and self.setup is not None:
            self.flow.show_character_select(self.setup)
        else:
            self.window.close()

    # --- input -----------------------------------------------------------------------------

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys for the players and handle the menu, debug and training keys."""
        self._keys.press(symbol)
        if symbol in KEYS_MENU:
            if not self.menu_open:
                self.request_pause()
            elif symbol == arcade.key.ESCAPE:
                self.menu_action(MenuAction.BACK)
            else:
                self.menu_action(MenuAction.CONFIRM)
        elif symbol == KEY_HITBOXES:
            self.show_hitboxes = not self.show_hitboxes
        elif symbol == KEY_OVERLAY:
            self.show_overlay = not self.show_overlay
        elif symbol == KEY_FIGHTER_INFO:
            self.show_fighter_info = not self.show_fighter_info
        elif symbol == KEY_HELP:
            self.show_help = not self.show_help
        elif symbol == KEY_PAUSE:
            self.paused = not self.paused
        elif symbol == KEY_FRAME_ADVANCE:
            self.paused = True
            self._advance_one = True
        elif symbol == KEY_RESET:
            self.restart()
        elif symbol == KEY_RELOAD:
            self.reload_data()
        elif symbol == KEY_CAMERA_CLAMP:
            self.camera.clamped = not self.camera.clamped
        elif symbol == KEY_INPUTS:
            self.show_inputs = not self.show_inputs
        elif symbol == KEY_ZOOM:
            self.zoom.enabled = not self.zoom.enabled
            self.say("stepped zoom " + ("on" if self.zoom.enabled else "off"))
        elif self.training:
            self._on_training_key(symbol)

    def _on_training_key(self, symbol: int) -> None:
        if symbol == KEY_DUMMY_CONTROL:
            self.dummies = not self.dummies
            self.say("dummies stand still" if self.dummies else "dummies use their controls")
        elif symbol == KEY_DUMMY_DAMAGE_UP:
            self.change_dummy_damage(DUMMY_DAMAGE_STEP)
        elif symbol == KEY_DUMMY_DAMAGE_DOWN:
            self.change_dummy_damage(-DUMMY_DAMAGE_STEP)
        elif symbol == KEY_DUMMY_DAMAGE_RESET:
            self.change_dummy_damage(None)

    def on_key_release(self, symbol: int, modifiers: int) -> None:
        """Stop tracking a released key."""
        self._keys.release(symbol)

    def on_show_view(self) -> None:
        """Start the stage's music (silence for a stage without any)."""
        self.audio.play_music(self.stage.music or "")

    def _pan_of(self, position: Vec3) -> float:
        """Where a world position is on screen, from -1 (left edge) to 1 (right edge)."""
        screen_x = project_point(position)[0] - self.camera.pixel_centre[0]
        return screen_x * self.camera.zoom / (NATIVE_W / 2)

    def on_hide_view(self) -> None:
        """Save the recording and release the controllers when the view goes away."""
        self.save_recording()
        if self.inputs is not None:
            self.inputs.close()
        if self.hub is not None and self._owns_hub:
            self.hub.close()

    # --- training and debug tools ------------------------------------------------------------

    def _load_banks(self) -> dict[str, SpriteBank]:
        """Load the packed sprites of every character that has them, and make the textures
        of the costumes in play now rather than mid-fight."""
        banks: dict[str, SpriteBank] = {}
        if self.placeholder_art:
            return banks
        for character in self.characters:
            if character.id in banks:
                continue
            try:
                sprite_set = load_sprite_set(character.id)
            except SpriteSheetError as error:
                LOG.error("%s: sprites not loaded: %s", character.id, error)
                continue
            if sprite_set is not None:
                banks[character.id] = SpriteBank(sprite_set)
        for fighter in self.match.fighters:
            bank = banks.get(fighter.character.id)
            if bank is not None:
                bank.warm(self.costume(fighter, len(bank.sprite_set.costumes)))
        return banks

    def costume(self, fighter: Fighter, count: int) -> int:
        """Return the costume a fighter wears: the one its player picked on character select
        (a match from the menus), else the one of its colour."""
        if self.setup is not None and not self.training:
            return self.setup.costume_of(fighter.player_index, count)
        return costume_for(fighter, count)

    def _card_infos(self) -> list[CardInfo]:
        """What each player's HUD card shows: name, colour, bust and stock icon in the
        fighter's costume (if it has art), CPU level and team."""
        cards = []
        team_play = self.match.rules.teams is not None
        for index, fighter in enumerate(self.match.fighters):
            bank = self.renderer.banks.get(fighter.character.id)
            costume = 0 if bank is None else self.costume(fighter, len(bank.sprite_set.costumes))
            level = self.cpu_levels[index] if index < len(self.cpu_levels) else 0
            cards.append(
                CardInfo(
                    name=fighter.character.display_name,
                    color=fighter.color_index,
                    bust=None if bank is None else bank.portrait("bust", costume),
                    icon=None if bank is None else bank.portrait("icon", costume),
                    cpu=level,
                    team=fighter.team if team_play else None,
                )
            )
        return cards

    def _feed_names(self) -> list[str]:
        """Each player's name as the KO feed shows it."""
        return [
            f"P{index + 1} {fighter.character.display_name.upper()}"
            for index, fighter in enumerate(self.match.fighters)
        ]

    def restart(self) -> None:
        """Start the match over (F8)."""
        self.match = self._new_match()
        self._sounds.reset()
        self.effects.clear()
        self.hud_state = HudState(names=self._feed_names())
        self._go_ticks = 0
        self._over_ticks = 0
        self.camera.snap_to(self._camera_targets())

    def reload_data(self) -> None:
        """Reload every character and its moves from disk into the running match (F9).

        A file with a mistake leaves the match as it was and shows the error.
        """
        try:
            characters = [load_character(character.id) for character in self.characters]
        except DataError as error:
            LOG.error("reload failed: %s", error)
            self.say(f"reload FAILED: {error}")
            return
        self.characters = characters
        self.match.reload_characters(characters)
        self._cpu_match = None  # the CPUs learn the reloaded moves again
        self.renderer.banks = self._load_banks()
        if self.recorder is not None:
            self.recorder = None  # a replay cannot reproduce a mid-match data change
            self.say("recording stopped: data was reloaded")
            return
        self.say("reloaded " + ", ".join(sorted({character.id for character in characters})))

    def change_dummy_damage(self, change: float | None) -> None:
        """Add ``change`` percent to every dummy's damage, or reset it to zero for ``None``."""
        for fighter in self.match.fighters[FIRST_DUMMY:]:
            percent = 0.0 if change is None else fighter.damage + change
            self.match.set_damage(fighter.player_index, percent)
        dummies = self.match.fighters[FIRST_DUMMY:]
        if dummies:
            self.say(f"dummy damage {dummies[0].damage:.0f}%")

    def say(self, message: str) -> None:
        """Show a status message for a few seconds."""
        self._message = message
        self._message_ticks = MESSAGE_TICKS

    # --- loop ------------------------------------------------------------------------------

    def tick(self) -> None:
        """Advance one fixed step: poll input, step the sim, update effects and the camera."""
        if self._message_ticks > 0:
            self._message_ticks -= 1
        frames, menu_frames = self._poll()
        if self._quit_chord and not self.can_pause and not self.menu_open:
            self.quit_match()
            return
        if self._start_tapped:
            # Start is a gamepad's pause button: it opens the menu, and closes it again.
            self._start_tapped = False
            if self.menu_open:
                self.menu_action(MenuAction.BACK)
            else:
                self.request_pause()
            return
        if self.menu_open:
            for fired in self.menu_input.update(menu_frames, self._menu_extras):
                for action in MenuAction:
                    if action in fired and self.menu_open:
                        self.menu_action(action)
            return
        if self.paused and not self._advance_one:
            return
        self._advance_one = False
        if self.match.phase is MatchPhase.OVER and self._after_game():
            return
        was_counting = self.match.phase is MatchPhase.COUNTDOWN
        if self.replay is not None:
            if self.match.frame >= self.replay.ticks:
                if self.replay_matches is None:
                    self.replay_matches = self.match.state_hash() == self.replay.final_hash
                return
            played = list(self.replay.inputs[self.match.frame])
        else:
            played = self._player_frames(frames)
            if self.recorder is not None:
                self.recorder.record(played)
        self.match.tick(played)
        if was_counting and self.match.phase is MatchPhase.PLAYING:
            self._go_ticks = GO_TICKS
        elif self._go_ticks > 0:
            self._go_ticks -= 1
        self.effects.tick()
        self.effects.consume(self.match.events)
        self.hud_state.step(
            self.match.fighters, self.match.events, self.match.phase is MatchPhase.OVER
        )
        self.effects.observe(self.match.fighters, self.stage)
        looks = self.effect_renderer.projectile_looks
        looks.learn(self.characters)
        self.effects.observe_projectiles(self.match.projectiles, looks)
        cues = event_cues(self.match.events) + self._sounds.observe(self.match)
        self.audio.play_cues(cues, self._pan_of)
        targets = self._camera_targets()
        if targets:
            self.camera.zoom = self.zoom.update(targets)
            self.camera.update(targets)

    def _poll(self) -> tuple[list[InputFrame], list[InputFrame]]:
        """Read the devices. Returns the players' frames, and the frames that may drive the
        pause menu (every device). A controller unplugged mid-match pauses the game."""
        keys = self._keys.keys()
        self._keys.end_tick()
        if self.hub is None:
            assert self.inputs is not None
            frames = self.inputs.poll(keys)
            self.inputs.end_tick()
            self._menu_extras = None
            return frames, frames
        frames = self.hub.poll(self.devices, keys)
        by_device = self.hub.frames(keys)
        menu_frames = list(by_device.values())
        self._menu_extras = self.hub.menu_extras(list(by_device), start_confirms=False)
        self._start_tapped = self.hub.start_tapped()
        backspace = arcade.key.BACKSPACE in keys
        quit_held = []
        for device in self.devices:
            state = self.hub.pad_state(device) if device else None
            quit_held.append(state.start if state is not None else bool(device) and backspace)
        self._quit_chord = quit_chord(frames, quit_held)
        self.hub.end_tick()
        frames += [NEUTRAL_INPUT] * (len(self.characters) - len(frames))
        for device in self.devices:
            if not device or self.hub.connected(device):
                self._unplugged.discard(device)
            elif device not in self._unplugged:
                self._unplugged.add(device)
                self.say(f"{device} was unplugged: plug it back in to carry on")
                if not self.menu_open and self.replay is None:
                    self.open_menu()
        return frames, menu_frames

    def cpu_level_of(self, player: int) -> int:
        """The CPU level playing ``player`` (0 = a person or a scripted dummy)."""
        if player < len(self.cpu_levels) and self.cpu_levels[player] > 0:
            return self.cpu_levels[player]
        if self.training and player >= FIRST_DUMMY and self.dummy is DummyBehavior.CPU:
            return self.dummy_level
        return 0

    def _cpu(self, player: int, level: int) -> CpuController:
        """The controller for a CPU player, made fresh for each match (and each level)."""
        if self._cpu_match is not self.match:
            self._cpus = {}
            self._cpu_match = self.match
        controller = self._cpus.get(player)
        if controller is None or controller.level.level != level:
            controller = CpuController(player, level, self.seed, self.stage)
            self._cpus[player] = controller
        return controller

    def _player_frames(self, frames: list[InputFrame]) -> list[InputFrame]:
        """Replace CPU players' and the dummies' input with what they decide."""
        played = []
        world = None
        for index, manual in enumerate(frames):
            level = self.cpu_level_of(index)
            if level > 0:
                world = world or observe(self.match)  # one snapshot for all the CPUs
                played.append(self._cpu(index, level).think(self.match, world))
            elif self.training and index >= FIRST_DUMMY and self.dummies:
                played.append(dummy_frame(self.dummy, self.match.frame, manual))
            else:
                played.append(manual)
        return played

    def _after_game(self) -> bool:
        """Run the "GAME!" slow-motion and move on to the results. Returns whether to skip
        this tick's sim step."""
        self._over_ticks += 1
        if self.replay is not None:
            return False
        if self._over_ticks > GAME_HOLD_TICKS and self.flow is not None and self.setup is not None:
            self.flow.show_results(self.setup, self.match)
            return True
        slow = self._over_ticks <= GAME_SLOW_TICKS
        return slow and self._over_ticks % GAME_SLOW_FACTOR != 0

    def _in_play(self) -> list[Fighter]:
        return [fighter for fighter in self.match.fighters if fighter.in_play]

    def _camera_targets(self) -> list[Vec3]:
        lift = Vec3(0.0, 0.0, BODY_CENTRE_HEIGHT)
        return [fighter.pos + lift for fighter in self._in_play()]

    def _place_tags(self, fighters: Sequence[Fighter]) -> None:
        """Put each fighter's name tag over its head (hidden for fighters out of play or
        off screen)."""
        shown = {fighter.player_index: fighter for fighter in fighters}
        for index, (name, arrow) in enumerate(self._tags):
            fighter = shown.get(index)
            spot = None
            if fighter is not None:
                top = fighter.character.body.height
                head_x, head_y = self._screen_positions([fighter], top)[0]
                spot = tag_anchor(head_x, head_y, NATIVE_W, NATIVE_H)
            plate = self._tag_plates[index]
            name.visible = arrow.visible = plate.visible = spot is not None
            if spot is not None:
                arrow.move_to(spot[0], spot[1])
                bottom = spot[1] + font.line_height(TextSize.SMALL)
                name.move_to(spot[0], bottom + TAG_PLATE_PAD - 1)
                left = spot[0] - int(plate.width) // 2
                plate.position = (left + plate.width / 2, bottom + plate.height / 2)

    def tag_shown(self, player_index: int) -> bool:
        """Return whether a player's name tag is showing."""
        return self.player_tags and self._tags[player_index][0].visible

    def view_centre(self) -> tuple[int, int]:
        """Return the world pixel at the middle of the screen: the camera's centre, lowered
        so the world is drawn :data:`CAMERA_LIFT` pixels higher and the fight is centred in
        the play area between the HUD's bands (decision D-061)."""
        centre_x, centre_y = self.camera.pixel_centre
        return (centre_x, centre_y - round(CAMERA_LIFT / self.camera.zoom))

    def _point_on_screen(self, point: Vec3) -> tuple[float, float]:
        """Return where a world point is on the screen, in native pixels."""
        centre_x, centre_y = self.view_centre()
        sx, sy = project(point.x, point.y, point.z)
        zoom = self.camera.zoom
        return ((sx - centre_x) * zoom + NATIVE_W / 2, (sy - centre_y) * zoom + NATIVE_H / 2)

    def _screen_positions(
        self, fighters: Sequence[Fighter], height: float = BODY_CENTRE_HEIGHT
    ) -> list[tuple[float, float]]:
        """Return each fighter's middle (or the point ``height`` units above its feet) in
        native screen pixels."""
        centre_x, centre_y = self.view_centre()
        positions = []
        for fighter in fighters:
            pos = fighter.pos
            sx, sy = project(pos.x, pos.y, pos.z + height)
            zoom = self.camera.zoom
            positions.append(
                ((sx - centre_x) * zoom + NATIVE_W / 2, (sy - centre_y) * zoom + NATIVE_H / 2)
            )
        return positions

    def on_draw(self) -> None:
        """Draw the world at native resolution, then upscale it to the window."""
        self.clear()
        fighters = self._in_play()
        frame = self.match.frame
        looks = {}
        for fighter in fighters:
            bank = self.renderer.banks.get(fighter.character.id)
            looks[fighter.entity_id] = fighter_look(
                fighter,
                frame,
                self.effects.flash.get(fighter.player_index, 0),
                None if bank is None else bank.sprite_set.anims,
                0 if bank is None else self.costume(fighter, len(bank.sprite_set.costumes)),
                self.settings.reduce_flashing,
                self.effects.hit_hitlag.get(fighter.player_index, 0),
            )
        colors = {fighter.player_index: fighter.color_index for fighter in self.match.fighters}
        ground: list[GroundItem] = []
        if not self.placeholder_art:
            projectile_looks = self.effect_renderer.projectile_looks
            projectile_looks.learn(self.characters)
            ground = projectile_items(self.stage, self.match.projectiles, projectile_looks, colors)
            ground += decal_items(
                self.stage,
                [
                    (d.decal_id, d.position.x, d.position.y, d.position.z, d.fade)
                    for d in self.effects.decals
                ],
            )
        self.renderer.sync(fighters, frame, looks, ground)
        # A move that has its own animation shows its swing in the sprite (a smear), so its
        # hitboxes are only drawn by the F1 overlay.
        animated = {
            entity_id
            for entity_id, look in looks.items()
            if look.sprite is not None and look.sprite.exact
        }
        self.effect_renderer.sync(
            self.effects,
            fighters,
            self.match.projectiles,
            animated,
            colors,
            self.view_centre(),
        )
        self.hitboxes.fighters = fighters
        self.hitboxes.projectiles = self.match.projectiles
        scores = [stats.score for stats in self.match.stats] if self.score_display else None
        calm = self.settings.reduce_flashing
        self.hud_state.roll(self.match.fighters)
        self.hud.update(
            self.match.fighters,
            self.effects,
            scores,
            self.hud_state,
            self.settings.screen_shake / FULL_PERCENT,
            flashing=not calm,
        )
        self.hud.place_bubbles(fighters, self._screen_positions(fighters), self.hud_state)
        time_left = self.match.time_left
        self.extras.update(
            self.hud_state,
            time_left,
            "" if time_left is None else clock_text(time_left),
            self.banner_text(),
            self._point_on_screen,
            flashing=not calm,
        )
        if self.player_tags:
            self._place_tags(fighters)
        self._update_text()

        overlays: list[Overlay] = [self.effect_renderer]
        if self.show_hitboxes:
            overlays.append(self.hitboxes)
        if self.show_overlay:
            overlays.append(self.overlay)
        centre_x, centre_y = self.view_centre()
        strength = self.settings.screen_shake / FULL_PERCENT
        if self.settings.reduce_flashing:
            strength = 0.0  # the calm setting: no screen shake either (D-059)
        shake_x, shake_y = (round(part * strength) for part in self.effects.shake.offset)
        with self.pixel_buffer.drawing():
            self.renderer.draw((centre_x + shake_x, centre_y + shake_y), overlays, self.camera.zoom)
            if self.player_tags and self.hud_display:
                self.tags_ui.draw()
            if self.hud_display:
                self.hud.draw()
            self.extras.draw(self.hud_display)
            self._text.draw(pixelated=True)
            if self.menu_open:
                self._sync_pause_rows()
                if self.move_list_player is None:
                    self.pause_ui.draw()
                else:
                    self.moves_ui.draw()
            self.draw_fade()
        self.blit_to_window()

    # --- text ------------------------------------------------------------------------------

    def banner_text(self) -> str:
        """Return the big text in the middle of the screen: the countdown, GO!, or GAME!."""
        match = self.match
        if self.replay_matches is not None:
            return "REPLAY END"
        if match.phase is MatchPhase.OVER:
            return "GAME!"
        if match.phase is MatchPhase.COUNTDOWN:
            announcing = match.rules.countdown_frames - match.countdown < SUDDEN_DEATH_TEXT_FRAMES
            if match.sudden_death and announcing:
                return "SUDDEN DEATH"
            return countdown_text(match.countdown)
        return "GO!" if self._go_ticks > 0 else ""

    def _update_text(self) -> None:
        for label, line in zip(self._help, self._help_text, strict=True):
            label.text = line if self.show_help else ""

        lines: list[str] = []
        if self.show_fighter_info or self.show_overlay:
            for fighter in self.match.fighters:
                lines.append(fighter_info(fighter))
                lines.append(combat_info(fighter))
        if self.show_inputs:
            lines += input_lines(self.match.fighters, HUD_CAPACITY)
        status = self.status_line()
        if status:
            lines.append(status)
        for index, label in enumerate(self._info_lines):
            label.text = lines[index] if index < len(lines) else ""

    def status_line(self) -> str:
        """Return the one-line status shown under the fighter info: pause, frame, messages."""
        parts = []
        if self.paused:
            parts.append(f"PAUSED frame {self.match.frame} (F6 step, F5 resume)")
        elif self.show_overlay:
            clamp = "on" if self.camera.clamped else "off"
            parts.append(f"frame {self.match.frame}  camera clamp {clamp}")
        if self.replay is not None:
            verdict = {None: "", True: "  matches the recording", False: "  DOES NOT MATCH"}
            parts.append(
                f"REPLAY {self.match.frame}/{self.replay.ticks}{verdict[self.replay_matches]}"
            )
        if self._message_ticks > 0:
            parts.append(self._message)
        return "  ".join(parts)


def fighter_info(fighter: Fighter) -> str:
    """Return the first F2 debug line for a fighter: state, frame, position and velocity."""
    pos, vel = fighter.pos, fighter.vel
    ground = fighter.ground.name.lower()
    flags = ("fastfall " if fighter.fast_falling else "") + (
        f"inv {fighter.invincible_frames} " if fighter.invincible_frames else ""
    )
    return (
        f"P{fighter.player_index + 1} {fighter.state.value} f{fighter.state_frame} "
        f"pos {pos.x:.2f} {pos.y:.2f} {pos.z:.2f} "
        f"vel {vel.x:+.3f} {vel.y:+.3f} {vel.z:+.3f} "
        f"{fighter.facing.name} {ground} jumps {fighter.air_jumps_left} {flags}"
    ).rstrip()


def combat_info(fighter: Fighter) -> str:
    """Return the second F2 debug line for a fighter: damage, move, hitlag, hitstun, knockback."""
    move = fighter.move_id if fighter.state is StateId.ATTACK else "-"
    charge = f" charge {fighter.charge_frames}" if fighter.charge_frames else ""
    kb_vel = fighter.kb_vel
    intangible = f" intang {fighter.intangible_frames}" if fighter.intangible else ""
    return (
        f"   dmg {fighter.damage:.1f} move {move}{charge} hitlag {fighter.hitlag} "
        f"hitstun {fighter.hitstun} kb {fighter.last_knockback:.1f} "
        f"kbvel {kb_vel.x:+.3f} {kb_vel.y:+.3f} {kb_vel.z:+.3f} stale {len(fighter.stale_queue)} "
        f"shield {fighter.shield_hp:.0f}{intangible}"
    )
