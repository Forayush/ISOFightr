"""What the sound test lists and says: every song and every sound effect in the game.

Plan note "14 - Audio" ("Sound test") and decision D-063: nobody had listened to the game's
music, so Settings gets a jukebox. It reads ``assets/audio/manifest.json`` (which the audio
build writes), because a packaged game has no recipes to read.

Pure Python (no ``arcade``), so it is unit tested without a window.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from isofightr.data.paths import AUDIO_MANIFEST

MUSIC: Final[str] = "music"
SOUNDS: Final[str] = "sounds"
TABS: Final[tuple[str, ...]] = (MUSIC, SOUNDS)
VISIBLE_ROWS: Final[int] = 12
"""How many rows of the list fit on the screen; the list scrolls to keep the cursor in."""
ONCE: Final[frozenset[str]] = frozenset({"victory"})
"""Songs that are played once and not looped."""
SECONDS_PER_MINUTE: Final[int] = 60
FACT_LINES: Final[int] = 5
"""The most lines of facts a track has: where it plays, tempo, key, meter, length."""


@dataclass(frozen=True, slots=True)
class Track:
    """One thing the sound test can play."""

    id: str
    """The file's name: what the sound director is asked for."""
    title: str
    kind: str
    """``"music"`` or ``"sounds"``."""
    facts: tuple[str, ...]
    """What is known about it, a line each: tempo, key and mode, meter, length."""

    @property
    def loops(self) -> bool:
        """Whether it plays round and round until stopped."""
        return self.kind == MUSIC and self.id not in ONCE


def load_manifest(path: Path = AUDIO_MANIFEST) -> dict[str, Any]:
    """Read the audio build's manifest; an unreadable one is an empty one (the sound test
    then lists nothing, and the game plays on)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def clock(seconds: float) -> str:
    """Return a length as ``m:ss`` (a sound effect's, under a second, as ``0.21 s``)."""
    if seconds < 1.0:
        return f"{seconds:.2f} s"
    whole = round(seconds)
    return f"{whole // SECONDS_PER_MINUTE}:{whole % SECONDS_PER_MINUTE:02d}"


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def music_tracks(manifest: Mapping[str, Any], uses: Mapping[str, str] | None = None) -> list[Track]:
    """Return every song, by title. ``uses`` says where a song is heard, by its id (a
    stage's name, the menus): it becomes the first of the song's facts."""
    tracks = []
    songs = manifest.get(MUSIC, {})
    for song_id, entry in songs.items() if isinstance(songs, dict) else ():
        if not isinstance(entry, dict):
            continue
        facts = []
        where = (uses or {}).get(str(song_id), "")
        if where:
            facts.append(where.upper())
        tempo = _number(entry.get("tempo"))
        if tempo:
            facts.append(f"{tempo:g} BPM")
        key, mode = str(entry.get("key", "")), str(entry.get("mode", ""))
        if key and mode:
            facts.append(f"{key} {mode.replace('_', ' ')}".upper())
        meter = str(entry.get("meter", ""))
        if meter:
            facts.append(f"{meter} TIME")
        facts.append(clock(_number(entry.get("seconds"))))
        title = str(entry.get("title", song_id))
        tracks.append(Track(str(song_id), title, MUSIC, tuple(facts)))
    return sorted(tracks, key=lambda track: track.title.lower())


def sound_tracks(manifest: Mapping[str, Any]) -> list[Track]:
    """Return every sound effect, by name."""
    table = manifest.get("sfx", {})
    sounds = table.get(SOUNDS, {}) if isinstance(table, dict) else {}
    return [
        Track(str(name), str(name).replace("_", " "), SOUNDS, (clock(_number(seconds)),))
        for name, seconds in sorted(sounds.items() if isinstance(sounds, dict) else ())
    ]


def first_shown(cursor: int, first: int, count: int, visible: int = VISIBLE_ROWS) -> int:
    """Return the first row to show so that the cursor's row is on the screen, moving the
    list as little as possible from where it was."""
    if cursor < first:
        first = cursor
    elif cursor >= first + visible:
        first = cursor - visible + 1
    return max(0, min(first, max(count - visible, 0)))


def moved(cursor: int, step: int, count: int) -> int:
    """Return the cursor one row on (or back), going round at the ends."""
    return (cursor + step) % count if count else 0


def position(cursor: int, count: int) -> str:
    """Return where the cursor is in its list, as ``3 / 68``."""
    return f"{cursor + 1} / {count}" if count else "0 / 0"
