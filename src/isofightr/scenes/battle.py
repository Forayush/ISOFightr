"""The battle scene: runs a ``Match`` at a fixed 60 Hz and draws it.

Implements "Game loop: fixed 60 Hz simulation" in the plan note "02 - Technical
Architecture": each tick polls one ``InputFrame`` per player, steps the sim, and lets
presentation react. Nothing here changes sim state except by feeding it input.

Stocks are infinite for now; stock counts, the HUD, countdown and results arrive in M6.

Debug keys: F2 fighter info, F3 stage overlay, F8 restart the match, C toggles the camera
clamp. Player controls are in :mod:`isofightr.input.devices`.
"""

from collections.abc import Sequence

import arcade

from isofightr.config import NATIVE_H, Z_PX
from isofightr.input.devices import InputSource
from isofightr.render.camera import FollowCamera, bounds_on_screen
from isofightr.render.debug_overlay import StageOverlay
from isofightr.render.pixel_buffer import PixelBuffer
from isofightr.render.placeholder_art import BODY_HEIGHT
from isofightr.render.world_renderer import WorldRenderer
from isofightr.scenes.ticked_view import TickedView
from isofightr.sim.character_def import CharacterDef
from isofightr.sim.fighter import Fighter
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.stage import Stage
from isofightr.ui.pixel_font import GLYPH_HEIGHT
from isofightr.ui.pixel_text import GlyphAtlas, PixelLabel

KEY_FIGHTER_INFO = arcade.key.F2
KEY_OVERLAY = arcade.key.F3
KEY_RESET = arcade.key.F8
KEY_CAMERA_CLAMP = arcade.key.C

HUD_MARGIN = 4
HUD_CAPACITY = 104
LINE_HEIGHT = GLYPH_HEIGHT
HELP_TEXT = "WASD move  SPACE jump  I/, up/down  LCTRL walk  F2 info  F3 stage  F8 restart"
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
    ) -> None:
        """Create the view. See :class:`TickedView` for ``pixel_buffer`` and ``max_ticks``."""
        super().__init__(pixel_buffer, max_ticks)
        self.stage = stage
        self.characters = list(characters)
        self.seed = seed
        self.match = self._new_match()
        self.inputs = InputSource(len(self.characters))
        self.renderer = WorldRenderer(pixel_buffer, stage)
        self.camera = FollowCamera(limits=bounds_on_screen(stage.camera_bounds))
        self.camera.snap_to(self._camera_targets())
        self.show_overlay = False
        self.show_fighter_info = False
        self._held_keys: set[int] = set()

        glyphs = GlyphAtlas()
        self.overlay = StageOverlay(stage, glyphs)
        self._hud: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        self._help = PixelLabel(glyphs, self._hud, HUD_MARGIN, HUD_MARGIN, len(HELP_TEXT))
        self._help.text = HELP_TEXT
        top = NATIVE_H - HUD_MARGIN - LINE_HEIGHT
        self._info_lines = [
            PixelLabel(glyphs, self._hud, HUD_MARGIN, top - row * LINE_HEIGHT, HUD_CAPACITY)
            for row in range(len(self.characters) + 1)
        ]

    def _new_match(self) -> Match:
        return Match.create(self.stage, self.characters, self.seed, MatchRules(stocks=None))

    # --- input -----------------------------------------------------------------------------

    def on_key_press(self, symbol: int, modifiers: int) -> None:
        """Track held keys for the players and handle the debug keys."""
        self._held_keys.add(symbol)
        if symbol == KEY_OVERLAY:
            self.show_overlay = not self.show_overlay
        elif symbol == KEY_FIGHTER_INFO:
            self.show_fighter_info = not self.show_fighter_info
        elif symbol == KEY_RESET:
            self.match = self._new_match()
            self.camera.snap_to(self._camera_targets())
        elif symbol == KEY_CAMERA_CLAMP:
            self.camera.clamped = not self.camera.clamped

    def on_key_release(self, symbol: int, modifiers: int) -> None:
        """Stop tracking a released key."""
        self._held_keys.discard(symbol)

    def on_hide_view(self) -> None:
        """Release the controllers when the view goes away."""
        self.inputs.close()

    # --- loop ------------------------------------------------------------------------------

    def tick(self) -> None:
        """Advance one fixed step: poll input, step the sim, move the camera."""
        self.match.tick(self.inputs.poll(self._held_keys))
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
        self.renderer.sync(self._in_play(), self.match.frame)
        self._update_info()
        with self.pixel_buffer.drawing():
            self.renderer.draw(
                self.camera.pixel_centre, overlay=self.overlay if self.show_overlay else None
            )
            self._hud.draw(pixelated=True)
        self.blit_to_window()

    # --- debug text ------------------------------------------------------------------------

    def _update_info(self) -> None:
        lines = [fighter_info(fighter) for fighter in self.match.fighters]
        if self.show_overlay:
            clamp = "on" if self.camera.clamped else "off"
            lines.append(f"frame {self.match.frame}  camera clamp {clamp}")
        if not (self.show_fighter_info or self.show_overlay):
            lines = []
        for index, label in enumerate(self._info_lines):
            label.text = lines[index] if index < len(lines) else ""


def fighter_info(fighter: Fighter) -> str:
    """Return the F2 debug line for a fighter: state, frame, position, velocity and more."""
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
