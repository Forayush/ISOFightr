"""The sound director: plays cues and music, and applies the mixing rules.

Plan note "14 - Audio" ("Mixing rules"): volume categories (master, music, effects), a small
pitch variation on sounds that repeat, stereo pan from where a sound happened on screen, at
most a few copies of one sound at a time, and music that ducks on KOs and at "GAME!".

Playback goes through a backend, so everything here is plain Python:
:class:`isofightr.audio.arcade_backend.ArcadeBackend` plays through Arcade, and
:class:`NullBackend` plays nothing and remembers what it was asked to (tests, hidden windows,
machines with no sound device). A sound that fails to play is never an error.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from isofightr import config
from isofightr.audio.cues import Cue
from isofightr.data.paths import MUSIC_DIR, SFX_DIR
from isofightr.settings import VOLUME_MAX, Settings
from isofightr.sim.math3d import Vec3
from isofightr.sim.rng import Rng

LOG = logging.getLogger(__name__)
SOUND_SUFFIX = ".wav"


class AudioBackend(Protocol):
    """What actually makes noise."""

    def play(
        self, path: Path, volume: float, pan: float, speed: float, loop: bool, streaming: bool
    ) -> object | None:
        """Start a sound; return a handle for :meth:`set_volume` and :meth:`stop`."""

    def set_volume(self, handle: object, volume: float) -> None:
        """Change the volume of something that is playing."""

    def stop(self, handle: object) -> None:
        """Stop something that is playing."""


@dataclass(frozen=True, slots=True)
class Played:
    """One request a :class:`NullBackend` received."""

    name: str
    volume: float
    pan: float
    speed: float
    loop: bool


def _nothing() -> list[Played]:
    return []


@dataclass(slots=True)
class NullBackend:
    """Plays nothing; keeps a log of what was asked."""

    played: list[Played] = field(default_factory=_nothing)
    stopped: list[str] = field(default_factory=list)
    volumes: dict[str, float] = field(default_factory=dict)

    def play(
        self, path: Path, volume: float, pan: float, speed: float, loop: bool, streaming: bool
    ) -> object | None:
        self.played.append(Played(path.stem, volume, pan, speed, loop))
        return path.stem

    def set_volume(self, handle: object, volume: float) -> None:
        self.volumes[str(handle)] = volume

    def stop(self, handle: object) -> None:
        self.stopped.append(str(handle))

    def names(self) -> list[str]:
        """The names played so far, in order."""
        return [played.name for played in self.played]


class SoundDirector:
    """Plays sound effects and music for whichever scene is showing."""

    def __init__(
        self,
        backend: AudioBackend | None = None,
        settings: Settings | None = None,
        sfx_dir: Path = SFX_DIR,
        music_dir: Path = MUSIC_DIR,
    ) -> None:
        """Find the sounds on disk; nothing is loaded until it is first played."""
        self.backend: AudioBackend = backend if backend is not None else NullBackend()
        self.sfx = {path.stem: path for path in sorted(sfx_dir.glob(f"*{SOUND_SUFFIX}"))}
        self.music = {path.stem: path for path in sorted(music_dir.glob(f"*{SOUND_SUFFIX}"))}
        self.sfx_volume = 1.0
        self.music_volume = 1.0
        self.song = ""
        """The song that is playing ("" = none)."""
        self._song_handle: object | None = None
        self._duck_ticks = 0
        self._recent: dict[str, list[int]] = {}
        self._tick = 0
        self._rng = Rng.seeded(0)
        self._missing: set[str] = set()
        self.apply_settings(settings or Settings())

    # --- volume ----------------------------------------------------------------------------

    def apply_settings(self, settings: Settings) -> None:
        """Take the volume settings (0 to 10 each); the music follows at once."""
        master = settings.master_volume / VOLUME_MAX
        self.sfx_volume = master * settings.sfx_volume / VOLUME_MAX
        self.music_volume = master * settings.music_volume / VOLUME_MAX
        self._update_music_volume()

    def _music_level(self) -> float:
        duck = config.AUDIO_DUCK_VOLUME if self._duck_ticks > 0 else 1.0
        return self.music_volume * duck

    def _update_music_volume(self) -> None:
        if self._song_handle is not None:
            self.backend.set_volume(self._song_handle, self._music_level())

    # --- effects ---------------------------------------------------------------------------

    def play(self, name: str, pan: float = 0.0, vary: bool = False, duck: bool = False) -> bool:
        """Play a sound effect. Returns whether it was started (it is skipped when unknown,
        muted, or too many copies started just now)."""
        if duck:
            self._duck_ticks = config.AUDIO_DUCK_TICKS
            self._update_music_volume()
        path = self.sfx.get(name)
        if path is None:
            if name not in self._missing:
                self._missing.add(name)
                LOG.warning("no sound effect named %r", name)
            return False
        if self.sfx_volume <= 0.0:
            return False
        recent = [
            t for t in self._recent.get(name, []) if self._tick - t < config.AUDIO_INSTANCE_TICKS
        ]
        if len(recent) >= config.AUDIO_MAX_INSTANCES:
            self._recent[name] = recent
            return False
        recent.append(self._tick)
        self._recent[name] = recent
        speed = 1.0
        if vary:
            speed += (self._rng.random() * 2.0 - 1.0) * config.AUDIO_PITCH_VARIATION
        limit = config.AUDIO_MAX_PAN
        self.backend.play(path, self.sfx_volume, max(-limit, min(limit, pan)), speed, False, False)
        return True

    def play_cues(self, cues: Sequence[Cue], pan_of: Callable[[Vec3], float] | None = None) -> None:
        """Play a tick's cues; ``pan_of`` turns a world position into a pan (-1 to 1)."""
        for cue in cues:
            pan = pan_of(cue.position) if pan_of is not None and cue.position is not None else 0.0
            self.play(cue.name, pan, cue.vary, cue.duck)

    # --- music -----------------------------------------------------------------------------

    def play_music(self, song: str, loop: bool = True) -> None:
        """Switch to a song (looping by default). The same looping song just carries on."""
        if song == self.song and loop:
            return
        self.stop_music()
        path = self.music.get(song)
        if path is None:
            if song and song not in self._missing:
                self._missing.add(song)
                LOG.warning("no music named %r", song)
            return
        self.song = song
        self._song_handle = self.backend.play(path, self._music_level(), 0.0, 1.0, loop, True)

    def stop_music(self) -> None:
        """Stop the music."""
        if self._song_handle is not None:
            self.backend.stop(self._song_handle)
        self._song_handle = None
        self.song = ""

    # --- time ------------------------------------------------------------------------------

    def tick(self) -> None:
        """Advance one tick: un-duck the music when its time is up."""
        self._tick += 1
        if self._duck_ticks > 0:
            self._duck_ticks -= 1
            if self._duck_ticks == 0:
                self._update_music_volume()
