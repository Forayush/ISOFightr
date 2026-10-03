"""Audio playback through Arcade (pyglet media).

Plan note "14 - Audio": effects are loaded once and kept; music is streamed. Any failure (no
sound device, a missing codec) is logged once and then ignored: the game plays on in silence.
"""

from __future__ import annotations

import logging
from pathlib import Path

import arcade

LOG = logging.getLogger(__name__)


class ArcadeBackend:
    """Plays sounds with :class:`arcade.Sound`."""

    def __init__(self) -> None:
        self._sounds: dict[tuple[Path, bool], arcade.Sound] = {}
        self._broken = False

    def play(
        self, path: Path, volume: float, pan: float, speed: float, loop: bool, streaming: bool
    ) -> object | None:
        """Start a sound and return its player."""
        if self._broken:
            return None
        try:
            key = (path, streaming)
            sound = self._sounds.get(key)
            if sound is None or streaming:
                # A streamed source can only be played once, so music is opened afresh.
                sound = arcade.load_sound(path, streaming=streaming)
                self._sounds[key] = sound
            return sound.play(volume=volume, pan=pan, loop=loop, speed=speed)
        except Exception:
            LOG.exception("audio playback failed; carrying on without sound")
            self._broken = True
            return None

    def set_volume(self, handle: object, volume: float) -> None:
        """Change a playing sound's volume."""
        try:
            handle.volume = volume  # type: ignore[attr-defined]
        except Exception:
            LOG.debug("could not set volume", exc_info=True)

    def stop(self, handle: object) -> None:
        """Stop a playing sound."""
        try:
            arcade.stop_sound(handle)  # type: ignore[arg-type]
        except Exception:
            LOG.debug("could not stop a sound", exc_info=True)
