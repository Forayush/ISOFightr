"""The battle scene: runs a ``Match`` at a fixed 60 Hz and draws it.

Implements "Game loop: fixed 60 Hz simulation" in the plan note "02 - Technical
Architecture": each tick polls one ``InputFrame`` per player, steps the sim, and lets
presentation react to ``match.events``. Nothing here changes sim state except by feeding it
input, and through the two training tools the sim itself offers (``Match.set_damage`` and
``Match.reload_characters``).

Stocks are infinite for now; stock counts, countdown and results arrive in M6.

Debug keys (plan note 13, "Training mode"): F1 hitboxes and hurtboxes, F2 fighter info,
F3 stage overlay, F5 pause, F6 advance one frame, F8 restart the match, F9 reload character
and move data from disk, C toggles the camera clamp, H hides the help text. In training mode
players 2 to 4 are dummies that stand still: ``-`` and ``=`` change their damage by 10%,
``0`` resets it and Tab hands them back to their controls. Player controls are in
:mod:`isofightr.input.devices`.
"""

import logging
from collections.abc import Sequence

import arcade

from isofightr.config import NATIVE_H, Z_PX
from isofightr.data.character_loader import load_character
from isofightr.data.validation import DataError
from isofightr.input.devices import InputSource
from isofightr.render.camera import FollowCamera, bounds_on_screen
from isofightr.render.debug_overlay import StageOverlay
from isofightr.render.effect_renderer import EffectRenderer
from isofightr.render.effects import BattleEffects
from isofightr.render.fighter_look import fighter_look
from isofightr.render.hitbox_overlay import HitboxOverlay
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.placeholder_art import BODY_HEIGHT
from isofightr.render.world_renderer import Overlay, WorldRenderer
from isofightr.scenes.ticked_view import TickedView
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.fighter import Fighter, StateId
from isofightr.sim.input_frame import NEUTRAL_INPUT
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage
from isofightr.ui.hud import DamageHud
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

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

HUD_MARGIN = 4
HUD_CAPACITY = 104
LINE_HEIGHT = GLYPH_HEIGHT
HELP_LINES = (
    "WASD move  SPACE jump  I/, up/down  J attack  U smash  L grab  LSHIFT shield  H help",
    "F1 hitboxes  F2 info  F3 stage  F5 pause  F6 step  F8 restart  F9 reload data",
)
TRAINING_HELP = "TRAINING  -/= dummy damage  0 reset damage  TAB dummy control on/off"
DAMAGE_HUD_BOTTOM = HUD_MARGIN + (len(HELP_LINES) + 1) * LINE_HEIGHT + HUD_MARGIN
"""The damage readout sits just above the help text."""
INFO_LINES_PER_FIGHTER = 2
DUMMY_DAMAGE_STEP = 10.0
MESSAGE_TICKS = 180
"""How long a status message (such as the result of a reload) stays up."""
FIRST_DUMMY = 1
"""In training mode every player from this index on is a dummy."""
BODY_CENTRE_HEIGHT = BODY_HEIGHT / 2 / Z_PX
"""The camera tracks a fighter's middle rather than its feet, in units above the feet."""


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
    ) -> None:
        """Create the view. See :class:`TickedView` for ``pixel_buffer`` and ``max_ticks``.

        ``training`` turns players 2 to 4 into dummies and enables the dummy keys.
        """
        super().__init__(pixel_buffer, max_ticks)
        self.stage = stage
        self.characters = list(characters)
        self.seed = seed
        self.training = training
        self.dummies = training
        self.match = self._new_match()
        self.inputs = InputSource(len(self.characters))
        self.renderer = WorldRenderer(pixel_buffer, stage)
        self.camera = FollowCamera(limits=bounds_on_screen(stage.camera_bounds))
        self.camera.snap_to(self._camera_targets())
        self.effects = BattleEffects()
        self.effect_renderer = EffectRenderer()
        self.hitboxes = HitboxOverlay()
        self.show_hitboxes = False
        self.show_overlay = False
        self.show_fighter_info = False
        self.show_help = True
        self.paused = False
        self._advance_one = False
        self._message = ""
        self._message_ticks = 0
        self._held_keys: set[int] = set()

        glyphs = GlyphAtlas()
        self.overlay = StageOverlay(stage, glyphs)
        self.hud = DamageHud(glyphs, len(self.characters), DAMAGE_HUD_BOTTOM)
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

    def _new_match(self) -> Match:
        return Match.create(self.stage, self.characters, self.seed, MatchRules(stocks=None))

    # --- input -----------------------------------------------------------------------------

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys for the players and handle the debug and training keys."""
        self._held_keys.add(symbol)
        if symbol == KEY_HITBOXES:
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
        """Release the controllers when the view goes away."""
        self.inputs.close()

    # --- training and debug tools ------------------------------------------------------------

    def restart(self) -> None:
        """Start the match over (F8)."""
        self.match = self._new_match()
        self.effects.clear()
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
        if self.paused and not self._advance_one:
            return
        self._advance_one = False
        frames = self.inputs.poll(self._held_keys)
        if self.dummies:
            frames[FIRST_DUMMY:] = [NEUTRAL_INPUT] * len(frames[FIRST_DUMMY:])
        self.match.tick(frames)
        self.effects.tick()
        self.effects.consume(self.match.events)
        targets = self._camera_targets()
        if targets:
            self.camera.update(targets)

    def _in_play(self) -> list[Fighter]:
        return [fighter for fighter in self.match.fighters if fighter.in_play]

    def _camera_targets(self) -> list[Vec3]:
        lift = Vec3(0.0, 0.0, BODY_CENTRE_HEIGHT)
        return [fighter.pos + lift for fighter in self._in_play()]

    def on_draw(self) -> None:
        """Draw the world at native resolution, then upscale it to the window."""
        self.clear()
        fighters = self._in_play()
        frame = self.match.frame
        looks = {
            fighter.entity_id: fighter_look(
                fighter, frame, self.effects.flash.get(fighter.player_index, 0)
            )
            for fighter in fighters
        }
        self.renderer.sync(fighters, frame, looks)
        self.effect_renderer.sync(self.effects, fighters)
        self.hitboxes.fighters = fighters
        self.hud.update(self.match.fighters, self.effects)
        self._update_text()

        overlays: list[Overlay] = [self.effect_renderer]
        if self.show_hitboxes:
            overlays.append(self.hitboxes)
        if self.show_overlay:
            overlays.append(self.overlay)
        centre_x, centre_y = self.camera.pixel_centre
        shake_x, shake_y = self.effects.shake.offset
        with self.pixel_buffer.drawing():
            self.renderer.draw((centre_x + shake_x, centre_y + shake_y), overlays)
            self.hud.draw()
            self._text.draw(pixelated=True)
        self.blit_to_window()

    # --- debug text ------------------------------------------------------------------------

    def _update_text(self) -> None:
        for label, line in zip(self._help, self._help_text, strict=True):
            label.text = line if self.show_help else ""

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
