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

  Decision D-063 adds: ``key`` and ``mode`` (what the song says it is in; tests hold it to
  that), ``meter`` (``"3/4"``, ``"7/8"``...), ``swing``, a ``form`` of named
  ``[sections.<name>]`` (each with a ``kind``, what it ``play``s, and a ``level`` that may
  move ``to`` another for a build or a fade) in place of ``sequence``, ``name*0.8`` to play
  a pattern quieter in one section, and an ``[echo]`` that instruments ``send`` to.

Unknown keys are errors, like every other data file. Pure Python (no ``arcade``).
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Final

from isofightr.audio.synth import (
    SAMPLE_RATE,
    SEMITONE,
    Voice,
    add_into,
    mix,
    note_hz,
    note_midi,
    render_voice,
)

VOICE_FIELDS: Final[frozenset[str]] = frozenset(field.name for field in fields(Voice))
HOLD: Final[str] = "-"
REST: Final[str] = "."
DRUM: Final[str] = "x"
SECONDS_PER_MINUTE: Final[float] = 60.0
SYNTH_VERSION: Final[str] = "2"
"""Bump when the synthesizer changes what a recipe sounds like: every sound is rebuilt."""
MASTER_HEADROOM: Final[float] = 0.95
"""Songs and sounds are scaled down, if needed, so their loudest sample is this."""
SONG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "title",
        "tempo",
        "steps_per_beat",
        "instruments",
        "patterns",
        "sequence",
        "form",
        "sections",
        "key",
        "mode",
        "meter",
        "swing",
        "swing_steps",
        "echo",
    }
)
SECTION_KINDS: Final[tuple[str, ...]] = ("intro", "verse", "chorus", "bridge", "break", "outro")
SCALES: Final[dict[str, tuple[int, ...]]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "phrygian_dominant": (0, 1, 4, 5, 7, 8, 10),
}
"""Semitones above the tonic, by mode (decision D-063: a song states its key and mode)."""
PLAY_ENTRY: Final[re.Pattern[str]] = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z_0-9]*)(?P<shift>[+-]\d+)?(?:\*(?P<gain>\d*\.?\d+))?"
)
"""A pattern in a section: its name, then ``+3`` or ``-12`` semitones, then ``*0.8`` gain."""
MAX_SWING: Final[float] = 0.5
MAX_FEEDBACK: Final[float] = 0.8
ECHO_PASSES: Final[int] = 3
SLOW_ATTACK: Final[float] = 0.05
"""An attack this long or longer makes a voice a pad rather than a struck or blown note."""


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
class Play:
    """One pattern playing in a section."""

    pattern: str
    transpose: int = 0
    """Semitones up (or down)."""
    gain: float = 1.0
    """How loud it is here, against the instrument's own volume."""


@dataclass(frozen=True, slots=True)
class Section:
    """A part of a song: the patterns that play together, and how loud."""

    kind: str
    """One of :data:`SECTION_KINDS`."""
    plays: tuple[Play, ...]
    level: float = 1.0
    """How loud the section starts."""
    to: float = 1.0
    """How loud it ends: different from ``level`` for a build or a fade."""


@dataclass(frozen=True, slots=True)
class Echo:
    """A feedback delay that instruments send part of their sound to."""

    beats: float
    """The delay, in beats."""
    feedback: float
    """How much of each repeat comes round again (below 1)."""
    mix: float
    """How loud the repeats are."""
    lowpass: float = 0.6
    """Each repeat is duller: 1 keeps it bright."""


@dataclass(frozen=True, slots=True)
class Song:
    """A looping piece of music."""

    id: str
    title: str
    tempo: float
    steps_per_beat: int
    instruments: dict[str, Voice]
    patterns: dict[str, Pattern]
    sections: tuple[Section, ...]
    """The song's form, in order."""
    key: str = ""
    """The tonic as a note name (``D``, ``F#``); empty in a song from before D-063."""
    mode: str = ""
    """One of :data:`SCALES`."""
    meter: tuple[int, int] = (4, 4)
    """Beats in a bar and the note that counts as one (``(7, 8)`` is 7/8)."""
    swing: float = 0.0
    """0 is straight; up to 0.5 the off-beats come that much later (a shuffle)."""
    swing_steps: int = 0
    """The grid steps that swing in pairs (0 = half a beat)."""
    echo: Echo | None = None
    sends: dict[str, float] = field(default_factory=dict)
    """How much of each instrument goes to the echo."""

    @property
    def sequence(self) -> tuple[tuple[tuple[str, int], ...], ...]:
        """The form as plain ``(pattern, transpose)`` pairs per section."""
        return tuple(
            tuple((play.pattern, play.transpose) for play in section.plays)
            for section in self.sections
        )

    @property
    def step_seconds(self) -> float:
        return SECONDS_PER_MINUTE / self.tempo / self.steps_per_beat

    @property
    def bar_steps(self) -> int:
        """Grid steps in one bar of the song's meter (a beat is a quarter note)."""
        beats, unit = self.meter
        return self.steps_per_beat * 4 * beats // unit

    def section_steps(self, section: Section | tuple[tuple[str, int], ...]) -> int:
        """Return a section's length in grid steps: that of its longest pattern."""
        plays = section.plays if isinstance(section, Section) else section
        names = [play.pattern if isinstance(play, Play) else play[0] for play in plays]
        return max(self.patterns[name].length for name in names)

    @property
    def total_steps(self) -> int:
        return sum(self.section_steps(section) for section in self.sections)

    @property
    def seconds(self) -> float:
        """Length of one loop."""
        return self.total_steps * self.step_seconds

    def step_time(self, position: float) -> float:
        """Return when a grid position sounds, in seconds from the loop's start. With swing,
        each pair of ``swing_steps`` is split unevenly: the first half longer."""
        if self.swing <= 0.0:
            return position * self.step_seconds
        unit = self.swing_steps or max(self.steps_per_beat // 2, 1)
        pair, inside = divmod(position, 2 * unit)
        long, short = unit * (1.0 + self.swing), unit * (1.0 - self.swing)
        warped = inside / unit * long if inside < unit else long + (inside - unit) / unit * short
        return (pair * 2 * unit + warped) * self.step_seconds

    def pitches(self) -> list[int]:
        """Return the pitch class (0 = C .. 11 = B) of every note the song plays, drums
        aside, once for each time it sounds."""
        found = []
        for section in self.sections:
            length = self.section_steps(section)
            for play in section.plays:
                pattern = self.patterns[play.pattern]
                repeats = -(-length // pattern.length)
                for token in pattern.steps * repeats:
                    if token not in (HOLD, REST, DRUM):
                        found.append((note_midi(token) + play.transpose) % 12)
        return found

    def in_scale(self) -> float:
        """Return the share of the song's notes that belong to its key and mode (1.0 for a
        song that states none)."""
        if not self.key or not self.mode:
            return 1.0
        tonic = note_midi(f"{self.key}0") % 12
        scale = {(tonic + degree) % 12 for degree in SCALES[self.mode]}
        notes = self.pitches()
        return sum(note in scale for note in notes) / len(notes) if notes else 1.0

    def timbres(self) -> set[tuple[object, ...]]:
        """Return what kinds of voice the song uses (see :func:`timbre`)."""
        used = {self.patterns[play.pattern].instrument for s in self.sections for play in s.plays}
        return {timbre(self.instruments[name]) for name in used}


def timbre(voice: Voice) -> tuple[object, ...]:
    """Return what makes a voice sound like itself, leaving out pitch, length and volume:
    two instruments with the same timbre are the same instrument (decision D-063)."""
    extra: tuple[object, ...] = ()
    if voice.wave == "square":
        extra = (round(voice.duty, 2),)
    elif voice.wave == "noise":
        extra = (voice.noise_steps, round(voice.freq / 500.0))
    elif voice.wave == "pad":
        extra = (round(voice.detune),)
    elif voice.wave == "bell":
        extra = (round(voice.mod_ratio, 2), round(voice.mod_index, 1))
    elif voice.wave == "pluck":
        extra = (round(voice.damp, 1),)
    elif voice.wave == "drum":
        extra = (round(voice.noise, 1), round(voice.freq / 20.0))
    return (
        voice.wave,
        *extra,
        voice.arpeggio,
        voice.crush,
        round(voice.lowpass, 1),
        voice.attack >= SLOW_ATTACK,
        round(voice.vibrato_depth, 1),
    )


def _play(entry: str, patterns: Mapping[str, Pattern], where: str) -> Play:
    match = PLAY_ENTRY.fullmatch(entry)
    if match is None:
        raise RecipeError(f"{where}: cannot read {entry!r} (pattern, +3 or -12, *0.8)")
    name = match["name"]
    if name not in patterns:
        raise RecipeError(f"{where}: sequence uses unknown pattern {name!r}")
    return Play(name, int(match["shift"] or 0), float(match["gain"] or 1.0))


def _sections(data: Mapping[str, Any], patterns: Mapping[str, Pattern], name: str) -> list[Section]:
    """Read a song's form: ``sequence`` (the plain list from before D-063) or ``form``, a
    list of names from ``[sections.<name>]``."""
    if ("sequence" in data) == ("form" in data):
        raise RecipeError(f"{name}: give either sequence or form")
    if "sequence" in data:
        return [
            Section("verse", tuple(_play(entry, patterns, name) for entry in section))
            for section in data["sequence"]
        ]
    tables = data.get("sections", {})
    sections = []
    for label in data["form"]:
        if label not in tables:
            raise RecipeError(f"{name}: form uses unknown section {label!r}")
        table = tables[label]
        extra = sorted(set(table) - {"kind", "play", "level", "to"})
        if extra:
            raise RecipeError(f"{name} section {label}: unknown key(s) {', '.join(extra)}")
        kind = str(table.get("kind", label.rstrip("0123456789_")))
        if kind not in SECTION_KINDS:
            raise RecipeError(
                f"{name} section {label}: kind must be one of {', '.join(SECTION_KINDS)}"
            )
        level = float(table.get("level", 1.0))
        plays = tuple(_play(entry, patterns, f"{name} section {label}") for entry in table["play"])
        if not plays:
            raise RecipeError(f"{name} section {label}: nothing plays")
        sections.append(Section(kind, plays, level, float(table.get("to", level))))
    unused = sorted(set(tables) - set(data["form"]))
    if unused:
        raise RecipeError(f"{name}: section(s) not in the form: {', '.join(unused)}")
    return sections


def _meter(text: str, name: str) -> tuple[int, int]:
    beats, _, unit = text.partition("/")
    if not beats.isdigit() or unit not in ("4", "8") or int(beats) < 2:
        raise RecipeError(f"{name}: meter must look like 3/4 or 7/8")
    return (int(beats), int(unit))


def load_song(path: Path) -> Song:
    """Read a ``music/<id>.toml`` song."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = sorted(set(data) - SONG_KEYS)
    if unknown:
        raise RecipeError(f"{path.name}: unknown key(s) {', '.join(unknown)}")
    try:
        instruments = {}
        sends = {}
        for name, values in data["instruments"].items():
            values = dict(values)
            send = float(values.pop("send", 0.0))
            if send:
                sends[name] = send
            instruments[name] = _voice(values, f"{path.name} instrument {name}")
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
        echo = None
        if "echo" in data:
            extra = sorted(set(data["echo"]) - {"beats", "feedback", "mix", "lowpass"})
            if extra:
                raise RecipeError(f"{path.name} echo: unknown key(s) {', '.join(extra)}")
            echo = Echo(
                float(data["echo"]["beats"]),
                float(data["echo"]["feedback"]),
                float(data["echo"]["mix"]),
                float(data["echo"].get("lowpass", 0.6)),
            )
            if not 0.0 <= echo.feedback < MAX_FEEDBACK or echo.beats <= 0.0:
                raise RecipeError(f"{path.name} echo: feedback must be under {MAX_FEEDBACK}")
        if sends and echo is None:
            raise RecipeError(f"{path.name}: an instrument sends to an echo the song has not got")
        mode = str(data.get("mode", ""))
        key = str(data.get("key", ""))
        if (mode or key) and (mode not in SCALES or not key):
            raise RecipeError(f"{path.name}: mode must be one of {', '.join(SCALES)}, with a key")
        if key:
            note_hz(f"{key}4")
        swing = float(data.get("swing", 0.0))
        if not 0.0 <= swing <= MAX_SWING:
            raise RecipeError(f"{path.name}: swing must be 0 to {MAX_SWING}")
        song = Song(
            id=str(data["id"]),
            title=str(data.get("title", data["id"])),
            tempo=float(data["tempo"]),
            steps_per_beat=int(data.get("steps_per_beat", 4)),
            instruments=instruments,
            patterns=patterns,
            sections=tuple(_sections(data, patterns, path.name)),
            key=key,
            mode=mode,
            meter=_meter(str(data.get("meter", "4/4")), path.name),
            swing=swing,
            swing_steps=int(data.get("swing_steps", 0)),
            echo=echo,
            sends=sends,
        )
    except KeyError as error:
        raise RecipeError(f"{path.name}: missing key {error}") from error
    except ValueError as error:
        if isinstance(error, RecipeError):
            raise
        raise RecipeError(f"{path.name}: {error}") from error
    if song.id != path.stem:
        raise RecipeError(f"{path.name}: id {song.id!r} does not match the file name")
    if not song.sections:
        raise RecipeError(f"{path.name}: empty sequence")
    return song


def _echoed(bus: list[float], echo: Echo, delay: int) -> list[float]:
    """Return the repeats of what was sent to the echo, going round the loop: a repeat that
    runs past the end comes back in at the start, so the loop has no seam."""
    size = len(bus)
    delay = max(1, min(delay, size - 1))
    wet = [0.0] * size
    smooth = 0.0
    lowpass = min(max(echo.lowpass, 0.0), 1.0)
    # Each pass adds the repeats one loop further on; they are inaudible after a few.
    for _ in range(ECHO_PASSES):
        for index in range(size):
            source = index - delay
            heard = bus[source] + echo.feedback * wet[source]
            smooth += (heard - smooth) * lowpass
            wet[index] = smooth
    return wet


def render_song(song: Song) -> list[float]:
    """Render one loop of a song."""
    total_steps = song.total_steps
    out = [0.0] * round(song.step_time(total_steps) * SAMPLE_RATE)
    bus = [0.0] * len(out) if song.echo is not None else []
    cache: dict[tuple[str, float, int], list[float]] = {}
    start_step = 0
    for section in song.sections:
        section_length = song.section_steps(section)
        for play in section.plays:
            pattern = song.patterns[play.pattern]
            instrument = song.instruments[pattern.instrument]
            send = song.sends.get(pattern.instrument, 0.0)
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
                where = start_step + index * stride
                starts = song.step_time(where)
                if token == DRUM:
                    freq, length = instrument.freq, instrument.length
                else:
                    freq = note_hz(token) * SEMITONE**play.transpose
                    sounding = song.step_time(where + held * stride) - starts
                    length = sounding + instrument.release
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
                along = index * stride / section_length
                gain = play.gain * (section.level + (section.to - section.level) * along)
                samples = cache[key]
                if gain != 1.0:
                    samples = [sample * gain for sample in samples]
                offset = round(starts * SAMPLE_RATE)
                add_into(out, samples, offset)
                if send and bus:
                    add_into(bus, [sample * send for sample in samples], offset)
                index += held
        start_step += section_length
    if song.echo is not None:
        delay = round(song.echo.beats * SECONDS_PER_MINUTE / song.tempo * SAMPLE_RATE)
        wet = _echoed(bus, song.echo, delay)
        mix_level = song.echo.mix
        out = [dry + mix_level * repeat for dry, repeat in zip(out, wet, strict=True)]
    return normalized(out)


def source_hash(path: Path, salt: str = "") -> str:
    """A short hash of a recipe file (and the synth version), for the build manifest."""
    digest = hashlib.sha256()
    digest.update(salt.encode())
    digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


SFX_BITS: Final[int] = 16
MUSIC_BITS: Final[int] = 16
"""Songs were 8-bit until decision D-063: audibly noisy under pads and long echoes."""


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
