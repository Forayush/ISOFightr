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
and move data from disk, C toggles the camera clamp, H hides the help text. In training mode
``-`` and ``=`` change the dummies' damage by 10%, ``0`` resets it and Tab switches them
between standing still and their own controls. Player controls are in
:mod:`isofightr.input.devices`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import arcade

from isofightr.ai.dummy import DummyBehavior, dummy_frame
from isofightr.config import NATIVE_H, NATIVE_W, Z_PX
from isofightr.data.character_loader import load_character
from isofightr.data.replay_io import save_replay
from isofightr.data.sprite_sheet import SpriteSheetError, load_sprite_set
from isofightr.data.validation import DataError
from isofightr.input.devices import DeviceHub, InputSource
from isofightr.render import placeholder_art as art
from isofightr.render.camera import FollowCamera, bounds_on_screen
from isofightr.render.debug_overlay import StageOverlay
from isofightr.render.effect_renderer import EffectRenderer
from isofightr.render.effects import BattleEffects
from isofightr.render.fighter_look import costume_for, fighter_look
from isofightr.render.hitbox_overlay import HitboxOverlay
from isofightr.render.iso import project
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.sprite_bank import SpriteBank
from isofightr.render.world_renderer import Overlay, WorldRenderer
from isofightr.scenes.setup import MatchSetup, clock_text, countdown_text
from isofightr.scenes.ticked_view import TickedView
from isofightr.settings import Settings
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT, InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.replay import Recorder, Replay
from isofightr.sim.rules import MatchPhase
from isofightr.sim.stage import Stage
from isofightr.ui.hud import DamageHud
from isofightr.ui.menu import Menu, MenuAction, MenuInput, MenuItem
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel
from isofightr.ui.widgets import HIGHLIGHT, TextBlock, UiLayer, centred_left

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
KEY_CAMERA_CLAMP = arcade.key.C
KEY_HELP = arcade.key.H
KEY_DUMMY_DAMAGE_DOWN = arcade.key.MINUS
KEY_DUMMY_DAMAGE_UP = arcade.key.EQUAL
KEY_DUMMY_DAMAGE_RESET = arcade.key.KEY_0
KEY_DUMMY_CONTROL = arcade.key.TAB
KEYS_MENU = (arcade.key.ESCAPE, arcade.key.ENTER)

HUD_MARGIN = 4
HUD_CAPACITY = 104
LINE_HEIGHT = GLYPH_HEIGHT
HELP_LINES = (
    "WASD move  SPACE jump  I/, up/down  J attack  K special  U smash  L grab  LSHIFT shield",
    "F1 hitboxes  F2 info  F3 stage  F5 pause  F6 step  F8 restart  F9 reload data  H help",
)
TRAINING_HELP = "TRAINING  ESC menu  -/= dummy damage  0 reset damage  TAB dummy control"
DAMAGE_HUD_BOTTOM = HUD_MARGIN + (len(HELP_LINES) + 1) * LINE_HEIGHT + HUD_MARGIN
"""The damage readout sits just above the help text."""
INFO_LINES_PER_FIGHTER = 2
DUMMY_DAMAGE_STEP = 10.0
MESSAGE_TICKS = 180
"""How long a status message (such as the result of a reload) stays up."""
FIRST_DUMMY = 1
"""In training mode every player from this index on is a dummy."""
BODY_CENTRE_HEIGHT = art.BODY_HEIGHT / 2 / Z_PX
"""The camera tracks a fighter's middle rather than its feet, in units above the feet."""

BANNER_SCALE = 4
FULL_PERCENT = 100
BANNER_CAPACITY = len("SUDDEN DEATH")
BANNER_BOTTOM = NATIVE_H // 2 + 30
CLOCK_CAPACITY = len("99:59")
CLOCK_SCALE = 2
GO_TICKS = 40
"""How long "GO!" stays up after the countdown."""
SUDDEN_DEATH_TEXT_FRAMES = 60
"""The first part of a sudden-death countdown says so instead of showing a number."""
GAME_SLOW_TICKS = 60
"""After the deciding KO the sim runs at a third of its speed for this many render ticks."""
GAME_SLOW_FACTOR = 3
GAME_HOLD_TICKS = 150
"""Ticks between "GAME!" and the results screen."""
PAUSE_PANEL_WIDTH = 300
PAUSE_ROW_CAPACITY = 44

MENU_RESUME = "resume"
MENU_HELP = "help"
MENU_QUIT = "quit"
MENU_DUMMY = "dummy"
MENU_DAMAGE = "damage"
MENU_HITBOXES = "hitboxes"
MENU_INFO = "info"
MENU_RESET = "reset"
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
        self.hub = DeviceHub(self.settings) if self.devices else None
        self.inputs = None if self.devices else InputSource(len(self.characters))
        self._unplugged: set[str] = set()
        self.menu_input = MenuInput()
        self.renderer = WorldRenderer(pixel_buffer, stage, self._load_banks())
        self.camera = FollowCamera(limits=bounds_on_screen(stage.camera_bounds))
        self.camera.snap_to(self._camera_targets())
        self.effects = BattleEffects()
        self.effect_renderer = EffectRenderer()
        self.hitboxes = HitboxOverlay()
        self.show_hitboxes = False
        self.show_overlay = False
        self.show_fighter_info = False
        self.show_help = flow is None
        self.paused = False
        self.menu_open = False
        self._advance_one = False
        self._message = ""
        self._message_ticks = 0
        self._go_ticks = 0
        self._over_ticks = 0
        self._held_keys: set[int] = set()

        glyphs = GlyphAtlas()
        self.overlay = StageOverlay(stage, glyphs)
        names = [character.display_name for character in self.characters]
        colors = [fighter.color_index for fighter in self.match.fighters]
        self.hud = DamageHud(
            glyphs, len(self.characters), DAMAGE_HUD_BOTTOM, names, colors, self._stock_icons()
        )
        self._text: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        help_lines = [*HELP_LINES, TRAINING_HELP] if training else list(HELP_LINES)
        self._help_text = list(reversed(help_lines))
        self._help = [
            PixelLabel(glyphs, self._text, HUD_MARGIN, HUD_MARGIN + row * LINE_HEIGHT, len(line))
            for row, line in enumerate(self._help_text)
        ]
        top = NATIVE_H - HUD_MARGIN - LINE_HEIGHT
        rows = len(self.characters) * INFO_LINES_PER_FIGHTER + 1
        self._info_lines = [
            PixelLabel(glyphs, self._text, HUD_MARGIN, top - row * LINE_HEIGHT, HUD_CAPACITY)
            for row in range(rows)
        ]
        self.banner = PixelLabel(
            glyphs,
            self._text,
            0,
            BANNER_BOTTOM,
            BANNER_CAPACITY,
            HIGHLIGHT,
            scale=BANNER_SCALE,
        )
        self.clock = PixelLabel(
            glyphs,
            self._text,
            centred_left(CLOCK_CAPACITY, CLOCK_SCALE),
            NATIVE_H - HUD_MARGIN - GLYPH_HEIGHT * CLOCK_SCALE,
            CLOCK_CAPACITY,
            scale=CLOCK_SCALE,
        )
        self.pause_menu = self._build_pause_menu()
        self.pause_ui = UiLayer(glyphs)
        self._build_pause_ui()

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
            ]
        items.append(MenuItem(MENU_HELP, "Controls help", ON_OFF, int(self.show_help)))
        back = "Quit to character select" if self.flow is not None else "Quit"
        items.append(MenuItem(MENU_QUIT, back))
        return Menu(items)

    def _build_pause_ui(self) -> None:
        rows = len(self.pause_menu.items)
        height = (rows + 3) * (GLYPH_HEIGHT + 2) + 16
        left = (NATIVE_W - PAUSE_PANEL_WIDTH) // 2
        bottom = (NATIVE_H - height) // 2
        self.pause_ui.panel(0, 0, NATIVE_W, NATIVE_H, art.DIM_OVERLAY, art.DIM_OVERLAY)
        self.pause_ui.panel(left, bottom, PAUSE_PANEL_WIDTH, height)
        self.pause_ui.centred("PAUSED", bottom + height - GLYPH_HEIGHT * 2 - 8, HIGHLIGHT, 2)
        self._pause_rows = TextBlock(
            self.pause_ui,
            left + 16,
            bottom + height - GLYPH_HEIGHT * 2 - 16,
            rows,
            PAUSE_ROW_CAPACITY,
        )

    def open_menu(self) -> None:
        """Pause and show the pause menu."""
        self.menu_open = True
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
            dummies = self.match.fighters[FIRST_DUMMY:]
            damage = dummies[0].damage if dummies else 0.0
            menu.item(MENU_DAMAGE).label = f"Dummy damage: < {damage:.0f}% >"

    def menu_action(self, action: MenuAction) -> None:
        """Handle one navigation action in the pause menu."""
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
        elif chosen == MENU_QUIT:
            self.quit_match()
        self.show_help = bool(menu.item(MENU_HELP).index)
        if self.training:
            self.dummy = DummyBehavior(menu.item(MENU_DUMMY).value)
            self.show_hitboxes = bool(menu.item(MENU_HITBOXES).index)
            self.show_fighter_info = bool(menu.item(MENU_INFO).index)
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
        self._held_keys.add(symbol)
        if symbol in KEYS_MENU:
            if not self.menu_open:
                self.open_menu()
            elif symbol == arcade.key.ESCAPE:
                self.close_menu()
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
        self._held_keys.discard(symbol)

    def on_hide_view(self) -> None:
        """Save the recording and release the controllers when the view goes away."""
        self.save_recording()
        if self.inputs is not None:
            self.inputs.close()
        if self.hub is not None:
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
                bank.warm(costume_for(fighter, len(bank.sprite_set.costumes)))
        return banks

    def _stock_icons(self) -> list[arcade.Texture | None]:
        """Each player's stock icon: the character's head in its costume, if it has art."""
        icons: list[arcade.Texture | None] = []
        for fighter in self.match.fighters:
            bank = self.renderer.banks.get(fighter.character.id)
            costume = 0 if bank is None else costume_for(fighter, len(bank.sprite_set.costumes))
            icons.append(None if bank is None else bank.portrait("icon", costume))
        return icons

    def restart(self) -> None:
        """Start the match over (F8)."""
        self.match = self._new_match()
        self.effects.clear()
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
        if self.menu_open:
            for fired in self.menu_input.update(menu_frames):
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
        targets = self._camera_targets()
        if targets:
            self.camera.update(targets)

    def _poll(self) -> tuple[list[InputFrame], list[InputFrame]]:
        """Read the devices. Returns the players' frames, and the frames that may drive the
        pause menu (every device). A controller unplugged mid-match pauses the game."""
        if self.hub is None:
            assert self.inputs is not None
            frames = self.inputs.poll(self._held_keys)
            return frames, frames
        frames = self.hub.poll(self.devices, self._held_keys)
        frames += [NEUTRAL_INPUT] * (len(self.characters) - len(frames))
        for device in self.devices:
            if not device or self.hub.connected(device):
                self._unplugged.discard(device)
            elif device not in self._unplugged:
                self._unplugged.add(device)
                self.say(f"{device} was unplugged: plug it back in to carry on")
                if not self.menu_open and self.replay is None:
                    self.open_menu()
        return frames, list(self.hub.frames(self._held_keys).values())

    def _player_frames(self, frames: list[InputFrame]) -> list[InputFrame]:
        """Replace the dummies' input with their behaviour."""
        if self.dummy is DummyBehavior.MANUAL:
            return frames
        frame = self.match.frame
        return [
            dummy_frame(self.dummy, frame, manual) if index >= FIRST_DUMMY else manual
            for index, manual in enumerate(frames)
        ]

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

    def _screen_positions(self, fighters: Sequence[Fighter]) -> list[tuple[float, float]]:
        """Return each fighter's middle in native screen pixels."""
        centre_x, centre_y = self.camera.pixel_centre
        positions = []
        for fighter in fighters:
            pos = fighter.pos
            sx, sy = project(pos.x, pos.y, pos.z + BODY_CENTRE_HEIGHT)
            positions.append((sx - centre_x + NATIVE_W / 2, sy - centre_y + NATIVE_H / 2))
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
                0 if bank is None else costume_for(fighter, len(bank.sprite_set.costumes)),
            )
        self.renderer.sync(fighters, frame, looks)
        # A move that has its own animation shows its swing in the sprite (a smear), so its
        # hitboxes are only drawn by the F1 overlay.
        animated = {
            entity_id
            for entity_id, look in looks.items()
            if look.sprite is not None and look.sprite.exact
        }
        self.effect_renderer.sync(self.effects, fighters, self.match.projectiles, animated)
        self.hitboxes.fighters = fighters
        self.hitboxes.projectiles = self.match.projectiles
        self.hud.update(self.match.fighters, self.effects)
        self.hud.place_bubbles(fighters, self._screen_positions(fighters))
        self._update_text()

        overlays: list[Overlay] = [self.effect_renderer]
        if self.show_hitboxes:
            overlays.append(self.hitboxes)
        if self.show_overlay:
            overlays.append(self.overlay)
        centre_x, centre_y = self.camera.pixel_centre
        strength = self.settings.screen_shake / FULL_PERCENT
        shake_x, shake_y = (round(part * strength) for part in self.effects.shake.offset)
        with self.pixel_buffer.drawing():
            self.renderer.draw((centre_x + shake_x, centre_y + shake_y), overlays)
            self.hud.draw()
            self._text.draw(pixelated=True)
            if self.menu_open:
                self._pause_rows.set_lines(self.pause_menu.lines(), self.pause_menu.cursor)
                self.pause_ui.draw()
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

        banner = self.banner_text()
        if banner != self.banner.text:
            self.banner.move_to(centred_left(len(banner), BANNER_SCALE), BANNER_BOTTOM)
            self.banner.text = banner
        time_left = self.match.time_left
        self.clock.text = "" if time_left is None else clock_text(time_left)

        lines: list[str] = []
        if self.show_fighter_info or self.show_overlay:
            for fighter in self.match.fighters:
                lines.append(fighter_info(fighter))
                lines.append(combat_info(fighter))
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
