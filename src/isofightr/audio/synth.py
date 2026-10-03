"""A tiny chiptune synthesizer: the source of every sound and song in the game.

Plan note "14 - Audio" and decision D-055: sounds are not recorded or downloaded but written
as text recipes (``art_src/audio/``) and rendered here, the way the art is rendered from text
by Blender. One :class:`Voice` is an oscillator (square with a duty cycle, triangle, saw,
sine, or an LFSR noise channel like an old console's) shaped by an attack-decay-sustain-
release envelope, with an optional pitch slide, vibrato, arpeggio, low-pass filter and
bit crush. Sounds layer voices; songs sequence notes on instruments.

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
WAVES: Final[tuple[str, ...]] = ("square", "triangle", "saw", "sine", "noise")
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


def note_hz(name: str) -> float:
    """The frequency of a note name such as ``A4``, ``C#5`` or ``Bb3``."""
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
    midi = (int(rest) + 1) * 12 + NOTE_NAMES[letter] + shift
    return A4_HZ * SEMITONE ** (midi - A4_MIDI)


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


def render_voice(voice: Voice) -> list[float]:
    """Render one voice (one repeat) to samples in [-1, 1]."""
    if voice.wave not in WAVES:
        raise ValueError(f"unknown wave {voice.wave!r}; expected one of {', '.join(WAVES)}")
    total = max(1, round(voice.length * SAMPLE_RATE))
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
