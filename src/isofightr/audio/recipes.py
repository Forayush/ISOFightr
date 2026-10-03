"""Sound and song recipes: the text sources in ``art_src/audio/`` and how they are rendered.

Plan note "14 - Audio", decision D-055. Two kinds of file:

- ``sfx.toml``: one table per sound, with ``[[name.layers]]`` voices
  (:class:`isofightr.audio.synth.Voice` fields) and/or ``include = ["other", ...]`` to layer
  whole sounds (``hit_heavy_fire`` is ``hit_heavy`` plus ``fire``).
- ``music/<id>.toml``: a song. ``tempo`` and ``steps_per_beat`` set the grid; each
  ``[instruments.<name>]`` is a voice template; each ``[patterns.<name>]`` plays one
  instrument over a string of steps (a note such as ``A4``, ``-`` to hold it, ``.`` for a
  rest, ``x`` to hit a drum at the instrument's own pitch), each ``stride`` grid steps long
  (default 1); ``sequence`` lists, section by section, the patterns that play together
  (``name+3`` transposes by semitones). A section lasts as long as its longest pattern and
  shorter ones repeat to fill it (a one-bar drum beat under a four-bar melody). The song
  loops, so note tails wrap around to the start.

Unknown keys are errors, like every other data file. Pure Python (no ``arcade``).
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Final

from isofightr.audio.synth import SAMPLE_RATE, SEMITONE, Voice, add_into, mix, note_hz, render_voice

VOICE_FIELDS: Final[frozenset[str]] = frozenset(field.name for field in fields(Voice))
HOLD: Final[str] = "-"
REST: Final[str] = "."
DRUM: Final[str] = "x"
SECONDS_PER_MINUTE: Final[float] = 60.0
SYNTH_VERSION: Final[str] = "1"
"""Bump when the synthesizer changes what a recipe sounds like: every sound is rebuilt."""
MASTER_HEADROOM: Final[float] = 0.95
"""Songs and sounds are scaled down, if needed, so their loudest sample is this."""


class RecipeError(ValueError):
    """A sound or song recipe is malformed."""


def _voice(values: Mapping[str, Any], where: str, base: Voice | None = None) -> Voice:
    unknown = sorted(set(values) - VOICE_FIELDS)
    if unknown:
        raise RecipeError(f"{where}: unknown key(s) {', '.join(unknown)}")
    cleaned = dict(values)
    if "arpeggio" in cleaned:
        cleaned["arpeggio"] = tuple(cleaned["arpeggio"])
    for key in ("freq", "freq_end"):
        if isinstance(cleaned.get(key), str):
            cleaned[key] = note_hz(cleaned[key])
    try:
        return replace(base, **cleaned) if base is not None else Voice(**cleaned)
    except TypeError as error:
        raise RecipeError(f"{where}: {error}") from error


def load_sfx(path: Path) -> dict[str, tuple[Voice, ...]]:
    """Read ``sfx.toml`` into the voices of every sound, includes resolved."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw: dict[str, tuple[tuple[Voice, ...], tuple[str, ...]]] = {}
    for name, table in data.items():
        if not isinstance(table, dict):
            raise RecipeError(f"{name}: expected a table")
        unknown = sorted(set(table) - {"layers", "include"})
        if unknown:
            raise RecipeError(f"{name}: unknown key(s) {', '.join(unknown)}")
        layers = tuple(
            _voice(layer, f"{name} layer {index + 1}")
            for index, layer in enumerate(table.get("layers", []))
        )
        raw[name] = (layers, tuple(table.get("include", [])))

    def resolve(name: str, seen: tuple[str, ...]) -> tuple[Voice, ...]:
        if name not in raw:
            raise RecipeError(f"{seen[-1] if seen else name}: includes unknown sound {name!r}")
        if name in seen:
            raise RecipeError(f"{name}: includes itself")
        layers, includes = raw[name]
        voices = list(layers)
        for other in includes:
            voices += resolve(other, (*seen, name))
        if not voices:
            raise RecipeError(f"{name}: no layers")
        return tuple(voices)

    return {name: resolve(name, ()) for name in raw}


def normalized(samples: list[float]) -> list[float]:
    """Scale samples down so the loudest is at ``MASTER_HEADROOM`` (never up)."""
    peak = max((abs(sample) for sample in samples), default=0.0)
    if peak <= MASTER_HEADROOM:
        return samples
    scale = MASTER_HEADROOM / peak
    return [sample * scale for sample in samples]


def render_sfx(voices: tuple[Voice, ...]) -> list[float]:
    """Render one sound."""
    return normalized(mix(voices))


@dataclass(frozen=True, slots=True)
class Pattern:
    """Steps for one instrument."""

    instrument: str
    steps: tuple[str, ...]
    stride: int = 1
    """Grid steps per token."""

    @property
    def length(self) -> int:
        """Length in grid steps."""
        return len(self.steps) * self.stride


@dataclass(frozen=True, slots=True)
class Song:
    """A looping piece of music."""

    id: str
    title: str
    tempo: float
    steps_per_beat: int
    instruments: dict[str, Voice]
    patterns: dict[str, Pattern]
    sequence: tuple[tuple[tuple[str, int], ...], ...]
    """Sections; each is the (pattern name, transpose) pairs that play together."""

    @property
    def step_seconds(self) -> float:
        return SECONDS_PER_MINUTE / self.tempo / self.steps_per_beat

    def section_steps(self, section: tuple[tuple[str, int], ...]) -> int:
        return max(self.patterns[name].length for name, _ in section)

    @property
    def seconds(self) -> float:
        """Length of one loop."""
        return sum(self.section_steps(section) for section in self.sequence) * self.step_seconds


def load_song(path: Path) -> Song:
    """Read a ``music/<id>.toml`` song."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    allowed = {"id", "title", "tempo", "steps_per_beat", "instruments", "patterns", "sequence"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise RecipeError(f"{path.name}: unknown key(s) {', '.join(unknown)}")
    try:
        instruments = {
            name: _voice(values, f"{path.name} instrument {name}")
            for name, values in data["instruments"].items()
        }
        patterns = {}
        for name, table in data["patterns"].items():
            extra = sorted(set(table) - {"instrument", "steps", "stride"})
            if extra:
                raise RecipeError(f"{path.name} pattern {name}: unknown key(s) {', '.join(extra)}")
            if table["instrument"] not in instruments:
                raise RecipeError(
                    f"{path.name} pattern {name}: unknown instrument {table['instrument']!r}"
                )
            steps = tuple(table["steps"].split())
            for step in steps:
                if step not in (HOLD, REST, DRUM):
                    note_hz(step)
            if not steps:
                raise RecipeError(f"{path.name} pattern {name}: no steps")
            patterns[name] = Pattern(table["instrument"], steps, int(table.get("stride", 1)))
        sequence = []
        for section in data["sequence"]:
            entries = []
            for entry in section:
                name, sign, shift = entry.partition("+") if "+" in entry else entry.partition("-")
                transpose = int(shift) * (1 if sign == "+" else -1) if sign else 0
                if name not in patterns:
                    raise RecipeError(f"{path.name}: sequence uses unknown pattern {name!r}")
                entries.append((name, transpose))
            sequence.append(tuple(entries))
        song = Song(
            id=str(data["id"]),
            title=str(data.get("title", data["id"])),
            tempo=float(data["tempo"]),
            steps_per_beat=int(data.get("steps_per_beat", 4)),
            instruments=instruments,
            patterns=patterns,
            sequence=tuple(sequence),
        )
    except KeyError as error:
        raise RecipeError(f"{path.name}: missing key {error}") from error
    except ValueError as error:
        if isinstance(error, RecipeError):
            raise
        raise RecipeError(f"{path.name}: {error}") from error
    if song.id != path.stem:
        raise RecipeError(f"{path.name}: id {song.id!r} does not match the file name")
    if not song.sequence:
        raise RecipeError(f"{path.name}: empty sequence")
    return song


def render_song(song: Song) -> list[float]:
    """Render one loop of a song."""
    step = song.step_seconds
    total_steps = sum(song.section_steps(section) for section in song.sequence)
    out = [0.0] * round(total_steps * step * SAMPLE_RATE)
    cache: dict[tuple[str, float, int], list[float]] = {}
    start_step = 0
    for section in song.sequence:
        section_length = song.section_steps(section)
        for name, transpose in section:
            pattern = song.patterns[name]
            instrument = song.instruments[pattern.instrument]
            repeats = -(-section_length // pattern.length)
            steps = pattern.steps * repeats
            stride = pattern.stride
            index = 0
            while index < len(steps) and index * stride < section_length:
                token = steps[index]
                if token in (REST, HOLD):
                    index += 1
                    continue
                held = 1
                while index + held < len(steps) and steps[index + held] == HOLD:
                    held += 1
                if token == DRUM:
                    freq, length = instrument.freq, instrument.length
                else:
                    freq = note_hz(token) * SEMITONE**transpose
                    length = held * stride * step + instrument.release
                key = (pattern.instrument, round(freq, 3), round(length * SAMPLE_RATE))
                if key not in cache:
                    ratio = freq / instrument.freq if instrument.freq > 0.0 else 1.0
                    voice = replace(
                        instrument,
                        freq=freq,
                        freq_end=instrument.freq_end * ratio
                        if token != DRUM
                        else instrument.freq_end,
                        length=length,
                    )
                    cache[key] = render_voice(voice)
                where = start_step + index * stride
                add_into(out, cache[key], round(where * step * SAMPLE_RATE))
                index += held
        start_step += song.section_steps(section)
    return normalized(out)


def source_hash(path: Path, salt: str = "") -> str:
    """A short hash of a recipe file (and the synth version), for the build manifest."""
    digest = hashlib.sha256()
    digest.update(salt.encode())
    digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


SFX_BITS: Final[int] = 16
MUSIC_BITS: Final[int] = 8
"""Songs are long: 8-bit keeps a 40 second loop under a megabyte, and suits chiptune."""


def sfx_wavs(source: Path) -> dict[str, bytes]:
    """Render every sound of an ``sfx.toml`` to WAV bytes."""
    from isofightr.audio.synth import wav_bytes

    return {
        name: wav_bytes(render_sfx(voices), SFX_BITS) for name, voices in load_sfx(source).items()
    }


def song_wav(song: Song) -> bytes:
    """Render a song to WAV bytes."""
    from isofightr.audio.synth import wav_bytes

    return wav_bytes(render_song(song), MUSIC_BITS)
