"""A tiny chiptune synthesizer: the source of every sound and song in the game.

Plan note "14 - Audio" and decision D-055: sounds are not recorded or downloaded but written
as text recipes (``art_src/audio/``) and rendered here, the way the art is rendered from text
by Blender. One :class:`Voice` is an oscillator (square with a duty cycle, triangle, saw,
sine, or an LFSR noise channel like an old console's) shaped by an attack-decay-sustain-
release envelope, with an optional pitch slide, vibrato, arpeggio, low-pass filter and
bit crush. Sounds layer voices; songs sequence notes on instruments.

Decision D-063 adds six instrument waves, so songs can differ in kind and not only in notes:
``pluck`` (a Karplus-Strong string), ``bell`` (two-operator FM), ``pad`` (a stack of detuned
saws, for a slow attack), ``reed`` (odd harmonics, nasal), ``ping`` (inharmonic partials,
metallic) and ``drum`` (a sine thump with a noise skin, for hand drums). The five original
waves render exactly as before.

Pure Python and the standard library only (no ``arcade``, no numpy) and deterministic: the
same recipe always renders the same bytes.
"""

from __future__ import annotations

import io
import math
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

SAMPLE_RATE: Final[int] = 22050
CLASSIC_WAVES: Final[tuple[str, ...]] = ("square", "triangle", "saw", "sine", "noise")
INSTRUMENT_WAVES: Final[tuple[str, ...]] = ("pluck", "bell", "pad", "reed", "ping", "drum")
"""The waves decision D-063 added (see the module's text)."""
WAVES: Final[tuple[str, ...]] = (*CLASSIC_WAVES, *INSTRUMENT_WAVES)
PAD_SAWS: Final[int] = 5
PAD_SPREAD: Final[tuple[float, ...]] = (-1.0, -0.5, 0.0, 0.5, 1.0)
"""Each saw of a pad is detuned by this share of the voice's ``detune``."""
PAD_PHASES: Final[tuple[float, ...]] = (0.0, 0.37, 0.71, 0.13, 0.59)
REED_HARMONICS: Final[tuple[tuple[int, float], ...]] = (
    (1, 1.0),
    (2, 0.14),
    (3, 0.55),
    (5, 0.3),
    (7, 0.14),
)
"""``(harmonic, level)``: mostly odd, which is what makes a reed sound hollow and nasal."""
PING_PARTIALS: Final[tuple[tuple[float, float, float], ...]] = (
    (1.0, 1.0, 3.0),
    (2.76, 0.6, 7.0),
    (5.4, 0.4, 12.0),
    (8.93, 0.25, 18.0),
)
"""``(frequency ratio, level, decay per second)``: a struck bar's inharmonic partials."""
PING_LEVEL: Final[float] = 0.44
"""Scales a ping so that all its partials together stay within range."""
BELL_INDEX_DECAY: Final[float] = 4.0
"""How fast a bell's brightness dies away, per second."""
PLUCK_SUSTAIN: Final[float] = 0.999
PLUCK_LOSS: Final[float] = 0.012
"""A string loses this much more per cycle at ``damp`` 1 than at 0."""
NOISE_SEED: Final[int] = 0x4A5B
"""Start state of the 15-bit noise shift register."""
NOISE_REGISTER_MASK: Final[int] = 0x7FFF
SEMITONE: Final[float] = 2.0 ** (1.0 / 12.0)
A4_HZ: Final[float] = 440.0
A4_MIDI: Final[int] = 69
NOTE_NAMES: Final[dict[str, int]] = {
    "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Voice:
    """One oscillator with its envelope and effects. Times are in seconds."""

    wave: str = "square"
    freq: float = 440.0
    freq_end: float = 0.0
    """Pitch at the end of the voice (0 = no slide). The slide is exponential."""
    length: float = 0.2
    """Total duration, release included."""
    duty: float = 0.5
    attack: float = 0.002
    decay: float = 0.0
    sustain: float = 1.0
    release: float = 0.02
    volume: float = 0.5
    vibrato_depth: float = 0.0
    """In semitones."""
    vibrato_rate: float = 6.0
    arpeggio: tuple[int, ...] = ()
    """Semitone offsets cycled at ``arpeggio_rate`` (a chord on one voice)."""
    arpeggio_rate: float = 30.0
    lowpass: float = 1.0
    """One-pole smoothing, 0 to 1: 1 lets everything through, small values muffle."""
    crush: int = 0
    """Quantize to this many levels (0 = no bit crush)."""
    delay: float = 0.0
    """When the voice starts inside its sound."""
    repeat: int = 1
    """Play the voice this many times..."""
    repeat_gap: float = 0.0
    """...this far apart (a stutter)."""
    noise_steps: int = 0
    """For noise: how many shift-register steps a ``freq`` cycle takes (0 = 1: hiss);
    larger values give pitched, metallic noise."""
    detune: float = 14.0
    """For a pad: how far its outer saws are tuned from the note, in cents."""
    mod_ratio: float = 3.5
    """For a bell: the modulator's frequency as a multiple of the note's."""
    mod_index: float = 4.0
    """For a bell: how bright the strike is (it dies away to a plain sine)."""
    damp: float = 0.5
    """For a pluck: 0 rings long and bright, 1 is short and dull."""
    noise: float = 0.3
    """For a drum: the share of noise (the skin's slap) against the sine (its thump)."""


def note_midi(name: str) -> int:
    """The MIDI number of a note name such as ``A4`` (69), ``C#5`` or ``Bb3``."""
    letter = name[0].upper()
    if letter not in NOTE_NAMES:
        raise ValueError(f"not a note: {name!r}")
    rest = name[1:]
    shift = 0
    while rest and rest[0] in "#b":
        shift += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    if not rest.lstrip("-").isdigit():
        raise ValueError(f"not a note: {name!r}")
    return (int(rest) + 1) * 12 + NOTE_NAMES[letter] + shift


def note_hz(name: str) -> float:
    """The frequency of a note name such as ``A4``, ``C#5`` or ``Bb3``."""
    return A4_HZ * SEMITONE ** (note_midi(name) - A4_MIDI)


def _envelope(voice: Voice, index: int, total: int) -> float:
    t = index / SAMPLE_RATE
    attack, decay, release = voice.attack, voice.decay, voice.release
    if t < attack:
        level = t / attack if attack > 0.0 else 1.0
    elif t < attack + decay:
        level = 1.0 - (1.0 - voice.sustain) * (t - attack) / decay
    else:
        level = voice.sustain
    remaining = (total - index) / SAMPLE_RATE
    if remaining < release:
        level *= remaining / release if release > 0.0 else 0.0
    return level


def _noise_bits(count: int) -> list[float]:
    """Return ``count`` samples of the shift register's noise (always the same)."""
    register = NOISE_SEED
    out = []
    for _ in range(count):
        bit = (register ^ (register >> 1)) & 1
        register = ((register >> 1) | (bit << 14)) & NOISE_REGISTER_MASK
        out.append(1.0 if register & 1 else -1.0)
    return out


def _pluck(voice: Voice, total: int) -> list[float]:
    """A plucked string (Karplus-Strong): a burst of noise going round a delay line one
    cycle long, losing its high end a little every time round.

    A delay line is a whole number of samples, which would leave high notes badly out of
    tune, so the string is played at the nearest pitch it can hold and then read back at
    the speed that makes it the note asked for.
    """
    freq = max(voice.freq, 20.0)
    # Averaging each sample with the next shortens the loop by half a sample.
    size = max(2, round(SAMPLE_RATE / freq + 0.5))
    speed = freq * (size - 0.5) / SAMPLE_RATE
    line = _noise_bits(size)
    damp = min(max(voice.damp, 0.0), 1.0)
    # Take the edge off the burst, more for a duller string.
    soften = 1.0 - (0.5 + 0.4 * damp) * 0.6
    previous = 0.0
    for index in range(size):
        previous = line[index] = previous + (line[index] - previous) * soften
    keep = PLUCK_SUSTAIN - PLUCK_LOSS * damp
    count = int(total * speed) + 2
    string = [0.0] * count
    at = 0
    for index in range(count):
        value = line[at]
        following = line[at + 1] if at + 1 < size else line[0]
        line[at] = (value + following) * 0.5 * keep
        string[index] = value
        at = at + 1 if at + 1 < size else 0
    out = [0.0] * total
    for index in range(total):
        place = index * speed
        whole = int(place)
        part = place - whole
        out[index] = string[whole] * (1.0 - part) + string[whole + 1] * part
    return out


def _instrument(voice: Voice, total: int) -> list[float]:
    """Render the raw wave of a bell, pad, reed, ping or drum (before envelope and filter)."""
    kind = voice.wave
    start = voice.freq
    end = voice.freq_end if voice.freq_end > 0.0 else voice.freq
    ratio = math.log(end / start) if start > 0.0 and end > 0.0 else 0.0
    two_pi = 2.0 * math.pi
    arpeggio = voice.arpeggio
    out = [0.0] * total
    phase = 0.0
    mod_phase = 0.0
    saw_phases = list(PAD_PHASES)
    saw_tunes = [SEMITONE ** (spread * voice.detune / 100.0) for spread in PAD_SPREAD]
    partial_phases = [0.0] * len(PING_PARTIALS)
    noise = _noise_bits(total) if kind == "drum" else []
    skin = 0.0
    mix_noise = min(max(voice.noise, 0.0), 1.0)
    for index in range(total):
        t = index / SAMPLE_RATE
        freq = start * math.exp(ratio * index / total) if ratio else start
        if voice.vibrato_depth:
            freq *= SEMITONE ** (voice.vibrato_depth * math.sin(two_pi * voice.vibrato_rate * t))
        if arpeggio:
            freq *= SEMITONE ** arpeggio[int(t * voice.arpeggio_rate) % len(arpeggio)]
        step = freq / SAMPLE_RATE
        if kind == "bell":
            index_now = voice.mod_index * math.exp(-BELL_INDEX_DECAY * t)
            value = math.sin(two_pi * phase + index_now * math.sin(two_pi * mod_phase))
            mod_phase = (mod_phase + step * voice.mod_ratio) % 1.0
        elif kind == "pad":
            value = 0.0
            for saw in range(PAD_SAWS):
                value += 2.0 * saw_phases[saw] - 1.0
                saw_phases[saw] = (saw_phases[saw] + step * saw_tunes[saw]) % 1.0
            value /= PAD_SAWS
        elif kind == "reed":
            value = 0.0
            for harmonic, level in REED_HARMONICS:
                if freq * harmonic < SAMPLE_RATE / 2:
                    value += level * math.sin(two_pi * phase * harmonic)
            value *= 0.5
        elif kind == "ping":
            value = 0.0
            for number, (multiple, level, decay) in enumerate(PING_PARTIALS):
                if freq * multiple < SAMPLE_RATE / 2:
                    value += (
                        level * math.exp(-decay * t) * math.sin(two_pi * partial_phases[number])
                    )
                partial_phases[number] = (partial_phases[number] + step * multiple) % 1.0
            value *= PING_LEVEL
        else:  # drum
            skin += (noise[index] - skin) * 0.35
            value = math.sin(two_pi * phase) * (1.0 - mix_noise) + skin * mix_noise
        phase = (phase + step) % 1.0
        out[index] = value
    return out


def _shaped(voice: Voice, raw: list[float]) -> list[float]:
    """Apply a voice's filter, envelope, volume and crush to a raw wave."""
    total = len(raw)
    lowpass = min(max(voice.lowpass, 0.0), 1.0)
    smoothed = 0.0
    out = [0.0] * total
    for index, value in enumerate(raw):
        smoothed += (value - smoothed) * lowpass
        out[index] = smoothed * _envelope(voice, index, total) * voice.volume
    if voice.crush > 1:
        levels = voice.crush
        out = [round(sample * levels) / levels for sample in out]
    return out


def render_voice(voice: Voice) -> list[float]:
    """Render one voice (one repeat) to samples in [-1, 1]."""
    if voice.wave not in WAVES:
        raise ValueError(f"unknown wave {voice.wave!r}; expected one of {', '.join(WAVES)}")
    total = max(1, round(voice.length * SAMPLE_RATE))
    if voice.wave == "pluck":
        return _shaped(voice, _pluck(voice, total))
    if voice.wave in INSTRUMENT_WAVES:
        return _shaped(voice, _instrument(voice, total))
    out = [0.0] * total
    start = voice.freq
    end = voice.freq_end if voice.freq_end > 0.0 else voice.freq
    ratio = math.log(end / start) if start > 0.0 and end > 0.0 else 0.0
    phase = 0.0
    register = NOISE_SEED
    noise_value = 1.0
    steps = max(1, voice.noise_steps)
    smoothed = 0.0
    lowpass = min(max(voice.lowpass, 0.0), 1.0)
    two_pi = 2.0 * math.pi
    arpeggio = voice.arpeggio
    for index in range(total):
        progress = index / total
        freq = start * math.exp(ratio * progress) if ratio else start
        t = index / SAMPLE_RATE
        if voice.vibrato_depth:
            freq *= SEMITONE ** (voice.vibrato_depth * math.sin(two_pi * voice.vibrato_rate * t))
        if arpeggio:
            freq *= SEMITONE ** arpeggio[int(t * voice.arpeggio_rate) % len(arpeggio)]
        step = freq / SAMPLE_RATE
        previous = phase
        phase = (phase + step) % 1.0
        kind = voice.wave
        if kind == "square":
            value = 1.0 if phase < voice.duty else -1.0
        elif kind == "triangle":
            value = 4.0 * phase - 1.0 if phase < 0.5 else 3.0 - 4.0 * phase
        elif kind == "saw":
            value = 2.0 * phase - 1.0
        elif kind == "sine":
            value = math.sin(two_pi * phase)
        else:
            # Step the shift register ``steps`` times per cycle (each wrap of a sub-phase).
            if int(previous * steps) != int(phase * steps) or phase < previous:
                bit = (register ^ (register >> 1)) & 1
                register = ((register >> 1) | (bit << 14)) & NOISE_REGISTER_MASK
                noise_value = 1.0 if register & 1 else -1.0
            value = noise_value
        smoothed += (value - smoothed) * lowpass
        out[index] = smoothed * _envelope(voice, index, total) * voice.volume
    if voice.crush > 1:
        levels = voice.crush
        out = [round(sample * levels) / levels for sample in out]
    return out


def mix(voices: Sequence[Voice]) -> list[float]:
    """Render and layer voices (with their delays and repeats) into one sound."""
    rendered: list[tuple[int, list[float]]] = []
    for voice in voices:
        samples = render_voice(voice)
        for repeat in range(max(1, voice.repeat)):
            offset = round((voice.delay + repeat * voice.repeat_gap) * SAMPLE_RATE)
            rendered.append((offset, samples))
    length = max((offset + len(samples) for offset, samples in rendered), default=0)
    out = [0.0] * length
    for offset, samples in rendered:
        for index, sample in enumerate(samples):
            out[offset + index] += sample
    return out


def add_into(target: list[float], samples: Sequence[float], offset: int) -> None:
    """Add ``samples`` into ``target`` from ``offset`` (wrapping past the end, for loops)."""
    size = len(target)
    for index, sample in enumerate(samples):
        target[(offset + index) % size] += sample


def wav_bytes(samples: Sequence[float], bits: int = 16) -> bytes:
    """Encode mono samples (clipped to [-1, 1]) as a WAV file of 8 or 16 bits."""
    if bits not in (8, 16):
        raise ValueError("bits must be 8 or 16")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(bits // 8)
        writer.setframerate(SAMPLE_RATE)
        if bits == 16:
            data = bytearray()
            for sample in samples:
                value = round(max(-1.0, min(1.0, sample)) * 32767)
                data += value.to_bytes(2, "little", signed=True)
        else:
            data = bytearray(round((max(-1.0, min(1.0, s)) + 1.0) * 127.5) for s in samples)
        writer.writeframes(bytes(data))
    return buffer.getvalue()
