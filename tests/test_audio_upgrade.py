"""The synth and recipe upgrade and the rules that keep songs apart (decision D-063, M14
group 2): the six instrument waves, echo, swing, meters, sections and levels, 16-bit music,
and the structural tests of every song (nobody here can hear them; the user judges the sound).
"""

import json
import math
import wave
from collections.abc import Sequence
from io import BytesIO
from itertools import combinations, pairwise
from pathlib import Path

import pytest

from isofightr.audio.recipes import (
    MASTER_HEADROOM,
    MUSIC_BITS,
    SCALES,
    SECTION_KINDS,
    Echo,
    RecipeError,
    Song,
    load_song,
    render_song,
    song_wav,
    timbre,
)
from isofightr.audio.synth import (
    CLASSIC_WAVES,
    INSTRUMENT_WAVES,
    SAMPLE_RATE,
    WAVES,
    Voice,
    note_hz,
    note_midi,
    render_voice,
)
from isofightr.data.paths import AUDIO_MANIFEST, AUDIO_SRC, MUSIC_DIR

SONGS = sorted((AUDIO_SRC / "music").glob("*.toml"))
LOADED = {path.stem: load_song(path) for path in SONGS}
LEGACY = {
    "final_plateau",
    "lily_pads",
    "menu",
    "training_grid",
    "victory",
}
"""Songs from before D-063, which state no key: each is replaced when its stage is rebuilt
(groups 3 and 5), and this set must shrink to the two that are not stage songs."""
NEW = {name: song for name, song in LOADED.items() if song.key}
MIN_TEMPO_GAP = 8.0
MIN_OWN_VOICES = 3
MIN_IN_SCALE = 0.85
LOOP_SECONDS = (40.0, 70.0)
SEAM_PERCENTILE = 0.999


def level(samples: Sequence[float], hz: float) -> float:
    """How much of a frequency a sound holds (the Goertzel algorithm)."""
    turn = 2.0 * math.pi * hz / SAMPLE_RATE
    coefficient = 2.0 * math.cos(turn)
    first = second = 0.0
    for sample in samples:
        first, second = sample + coefficient * first - second, first
    power = first * first + second * second - coefficient * first * second
    return math.sqrt(max(power, 0.0)) / len(samples)


def energy(samples: Sequence[float]) -> float:
    return sum(sample * sample for sample in samples)


def note(wave_name: str, **changes: object) -> list[float]:
    values: dict[str, object] = {"wave": wave_name, "freq": 440.0, "length": 1.0, "volume": 1.0}
    return render_voice(Voice(**{**values, **changes}))  # type: ignore[arg-type]


def write_song(tmp_path: Path, body: str, name: str = "tune") -> Path:
    path = tmp_path / f"{name}.toml"
    path.write_text(body, encoding="utf-8")
    return path


TUNE = """
id = "tune"
tempo = 120
steps_per_beat = 2
key = "C"
mode = "major"
meter = "3/4"
form = ["intro", "verse", "verse", "outro"]

[sections.intro]
play = ["line"]
level = 0.5
to = 1.0

[sections.verse]
play = ["line", "low-12*0.5", "tap"]

[sections.outro]
play = ["line"]
to = 0.25

[instruments.lead]
wave = "pluck"
send = 0.5

[instruments.drum]
wave = "drum"
freq = 200
length = 0.1

[patterns.line]
instrument = "lead"
steps = "C4 E4 G4 C5 - G4"

[patterns.low]
instrument = "lead"
steps = "C4 - - G3 - -"

[patterns.tap]
instrument = "drum"
steps = "x . . x . ."

[echo]
beats = 0.5
feedback = 0.4
mix = 0.5
"""


# --- the instrument waves ------------------------------------------------------------------


def test_the_new_waves_are_listed_and_the_old_ones_kept() -> None:
    assert (*CLASSIC_WAVES, *INSTRUMENT_WAVES) == WAVES
    assert INSTRUMENT_WAVES == ("pluck", "bell", "pad", "reed", "ping", "drum")
    assert note_midi("A4") == 69 and note_midi("C#5") == 73 and note_midi("Bb3") == 58
    assert note_hz("A4") == pytest.approx(440.0)


@pytest.mark.parametrize("wave_name", INSTRUMENT_WAVES)
def test_every_instrument_wave_stays_in_range_and_is_deterministic(wave_name: str) -> None:
    for freq in (82.4, 440.0, 1568.0):
        samples = note(wave_name, freq=freq, length=0.4)
        assert len(samples) == round(0.4 * SAMPLE_RATE)
        assert max(abs(sample) for sample in samples) <= 1.0, "no clipping at full volume"
        assert energy(samples) > 1.0, "it sounds"
        assert samples == note(wave_name, freq=freq, length=0.4)


@pytest.mark.parametrize("freq", [110.0, 440.0, 880.0, 1046.5, 1568.0])
def test_a_plucked_string_is_in_tune_at_every_pitch(freq: float) -> None:
    samples = note("pluck", freq=freq, length=0.5, damp=0.3)[2000:8000]
    cents = range(-40, 41, 4)
    best = max(cents, key=lambda c: level(samples, freq * 2.0 ** (c / 1200.0)))
    assert abs(best) <= 4, f"{best} cents off"


def test_a_plucked_string_rings_out_and_damping_shortens_it() -> None:
    bright, dull = note("pluck", damp=0.0), note("pluck", damp=1.0)
    for samples in (bright, dull):
        assert energy(samples[:4000]) > 4 * energy(samples[-8000:-4000]), "it dies away"
    assert energy(bright[-8000:]) > 2 * energy(dull[-8000:]), "a damped string is shorter"


def test_a_bell_is_bright_when_struck_and_pure_as_it_rings() -> None:
    bell = note("bell", mod_ratio=3.5, mod_index=4.0, length=1.5)
    early, late = bell[:6000], bell[-6000:]
    side = 440.0 * 2.5  # a sideband the modulator makes: nothing a plain sine has
    assert level(early, side) > 0.02 and level(early, side) > 5 * level(late, side)
    assert level(late, 440.0) > 10 * level(late, side), "it settles to its note"
    plain, sine = note("bell", mod_index=0.0), note("sine")
    assert plain[201:2000] == pytest.approx(sine[200:1999], abs=1e-9), "no strike: a sine"


def test_a_pad_is_several_saws_that_beat_against_each_other() -> None:
    wide, narrow = note("pad", detune=20.0), note("pad", detune=0.0)
    assert wide != narrow
    window = 2205
    loudness = [energy(wide[at : at + window]) for at in range(0, len(wide) - window, window)]
    assert max(loudness) > 1.5 * min(loudness), "the detuned saws drift in and out of phase"
    assert level(wide[:8820], 880.0) > 0.01, "it has a saw's harmonics"


def test_a_reed_is_mostly_odd_harmonics() -> None:
    reed = note("reed")[:8820]
    first, second, third = (level(reed, 440.0 * n) for n in (1, 2, 3))
    assert first > third > 2 * second
    # Harmonics above half the sample rate are left out, not folded back down.
    high = note("reed", freq=5000.0)[:8820]
    assert level(high, SAMPLE_RATE - 15000.0) < 0.01 < level(high, 5000.0)


def test_a_ping_has_partials_no_string_has_and_they_die_first() -> None:
    ping = note("ping", length=1.0)
    early, late = ping[:4410], ping[8820:13230]
    assert level(early, 440.0 * 2.76) > 0.03
    share_early = level(early, 440.0 * 2.76) / level(early, 440.0)
    share_late = level(late, 440.0 * 2.76) / level(late, 440.0)
    assert share_late < share_early / 2


def test_a_drum_is_a_thump_with_a_skin_of_noise() -> None:
    thump = note("drum", freq=200.0, noise=0.0, length=0.2)
    slap = note("drum", freq=200.0, noise=1.0, length=0.2)
    mixed = note("drum", freq=200.0, noise=0.3, length=0.2)
    assert level(thump, 200.0) > 20 * level(thump, 3100.0), "all thump"
    assert level(slap, 3100.0) > 3 * level(thump, 3100.0), "all skin"
    assert level(thump, 200.0) > level(mixed, 200.0) > level(slap, 200.0)
    falling = note("drum", freq=200.0, freq_end=100.0, noise=0.0, length=0.3)
    assert level(falling[-2000:], 105.0) > level(falling[-2000:], 200.0), "the pitch drops"


def test_the_classic_waves_take_the_new_fields_without_changing() -> None:
    plain = Voice(wave="square", freq=330.0, length=0.1)
    odd = Voice(wave="square", freq=330.0, length=0.1, detune=50.0, damp=0.9, noise=0.9)
    assert render_voice(plain) == render_voice(odd)


# --- songs: form, meter, swing, levels, echo -----------------------------------------------


def test_a_song_states_its_key_meter_and_form(tmp_path: Path) -> None:
    song = load_song(write_song(tmp_path, TUNE))
    assert (song.key, song.mode, song.meter) == ("C", "major", (3, 4))
    assert song.bar_steps == 6, "three quarter notes of two steps"
    assert [section.kind for section in song.sections] == ["intro", "verse", "verse", "outro"]
    assert all(song.section_steps(section) == 6 for section in song.sections)
    verse = song.sections[1]
    assert [(p.pattern, p.transpose, p.gain) for p in verse.plays] == [
        ("line", 0, 1.0),
        ("low", -12, 0.5),
        ("tap", 0, 1.0),
    ]
    assert (song.sections[0].level, song.sections[0].to) == (0.5, 1.0)
    assert (song.sections[3].level, song.sections[3].to) == (1.0, 0.25)
    assert song.sequence[1] == (("line", 0), ("low", -12), ("tap", 0))
    assert song.sends == {"lead": 0.5} and song.echo == Echo(0.5, 0.4, 0.5, 0.6)
    assert song.in_scale() == 1.0 and len(song.pitches()) == 5 * 4 + 2 * 2
    assert song.seconds == pytest.approx(24 * 0.25)
    assert set(SECTION_KINDS) >= {section.kind for section in song.sections}


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('mode = "major"', 'mode = "happy"', "mode must be one of"),
        ('key = "C"', "", "with a key"),
        ('meter = "3/4"', 'meter = "3/5"', "meter must look like"),
        ('form = ["intro", "verse", "verse", "outro"]', 'form = ["intro"]', "not in the form"),
        ('"verse", "outro"]', '"verse", "outro", "solo"]', "unknown section 'solo'"),
        ('play = ["line", "low-12*0.5", "tap"]', 'play = ["line", "bass"]', "unknown pattern"),
        ('play = ["line", "low-12*0.5", "tap"]', 'play = ["line!"]', "cannot read"),
        ("[sections.outro]", '[sections.outro]\nkind = "coda"', "kind must be one of"),
        ("[sections.outro]", "[sections.outro]\nfade = 1", "unknown key"),
        ("feedback = 0.4", "feedback = 0.95", "feedback must be under"),
        ("mix = 0.5", "mix = 0.5\nwet = 1", "unknown key"),
        ('meter = "3/4"', 'meter = "3/4"\nswing = 0.7', "swing must be"),
        ('meter = "3/4"', 'meter = "3/4"\nsequence = [["line"]]', "either sequence or form"),
        ('form = ["intro", "verse", "verse", "outro"]', "", "either sequence or form"),
    ],
)
def test_bad_songs_are_refused(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert TUNE.count(old) == 1
    with pytest.raises(RecipeError, match=message):
        load_song(write_song(tmp_path, TUNE.replace(old, new)))


def test_a_send_needs_an_echo(tmp_path: Path) -> None:
    body = TUNE[: TUNE.index("[echo]")]
    with pytest.raises(RecipeError, match="echo the song has not got"):
        load_song(write_song(tmp_path, body))


def test_meters_set_the_bar(tmp_path: Path) -> None:
    for meter, steps_per_beat, bar in (
        ("7/8", 2, 7),
        ("6/8", 2, 6),
        ("5/4", 4, 20),
        ("4/4", 4, 16),
    ):
        body = TUNE.replace('meter = "3/4"', f'meter = "{meter}"').replace(
            "steps_per_beat = 2", f"steps_per_beat = {steps_per_beat}"
        )
        assert load_song(write_song(tmp_path, body)).bar_steps == bar


def test_swing_delays_the_off_beats_and_keeps_the_bar(tmp_path: Path) -> None:
    straight = load_song(write_song(tmp_path, TUNE))
    swung = load_song(
        write_song(tmp_path, TUNE.replace('meter = "3/4"', 'meter = "3/4"\nswing = 0.3'))
    )
    step = straight.step_seconds
    assert [straight.step_time(n) for n in range(4)] == pytest.approx([0, step, 2 * step, 3 * step])
    times = [swung.step_time(n) for n in range(7)]
    assert times == sorted(times)
    assert times[0] == 0 and times[2] == pytest.approx(2 * step), "pairs stay where they were"
    assert times[1] == pytest.approx(1.3 * step) and times[3] == pytest.approx(3.3 * step)
    assert swung.step_time(swung.total_steps) == pytest.approx(straight.seconds)
    assert len(render_song(swung)) == len(render_song(straight)), "the loop is no longer"
    assert render_song(swung) != render_song(straight)


def test_a_sections_level_scales_what_plays_in_it(tmp_path: Path) -> None:
    verse_plays = 'play = ["line", "low-12*0.5", "tap"]'
    quiet = TUNE.replace(verse_plays, 'play = ["tap"]\nlevel = 0.25')
    intro_plays = '[sections.intro]\nplay = ["line"]'
    quiet = quiet.replace(intro_plays, '[sections.intro]\nplay = ["tap"]')
    body = quiet[: quiet.index("[echo]")].replace("send = 0.5\n", "")
    song = load_song(write_song(tmp_path, body))
    assert (song.sections[1].level, song.sections[1].to) == (0.25, 0.25)
    samples = render_song(song)
    section = len(samples) // 4
    intro, verse = samples[:section], samples[section : 2 * section]
    assert energy(verse) < energy(intro) / 2, "the verse is a quarter as loud"
    first_hit, second_hit = intro[: section // 2], intro[section // 2 :]
    assert energy(second_hit) == pytest.approx(energy(first_hit) * 1.5**2, rel=0.05), (
        "the intro builds: its second hit is at 0.75 of full, its first at 0.5"
    )


def test_the_echo_repeats_what_is_sent_and_wraps_round_the_loop(tmp_path: Path) -> None:
    body = TUNE.replace('form = ["intro", "verse", "verse", "outro"]', 'form = ["outro"]')
    body = body.replace('steps = "C4 E4 G4 C5 - G4"', 'steps = ". . . . . C5"')
    body = body[: body.index("[sections.intro]")] + body[body.index("[sections.outro]") :]
    body = body.replace("[sections.verse]", "[sections.unused]")
    wet = load_song(write_song(tmp_path, body, "tune"))
    dry_body = body[: body.index("[echo]")].replace("send = 0.5\n", "")
    dry = load_song(write_song(tmp_path, dry_body, "tune"))
    heard, plain = render_song(wet), render_song(dry)
    assert len(heard) == len(plain)
    first_half = len(plain) // 2
    assert energy(plain[:first_half]) < 0.2, "the note is at the end, and its tail is short"
    assert energy(heard[:first_half]) > 5 * energy(plain[:first_half]), (
        "the repeats of the last note come back in at the start of the loop"
    )


# --- every song in the game ----------------------------------------------------------------


def test_the_songs_from_before_the_upgrade_are_known() -> None:
    assert {name for name, song in LOADED.items() if not song.key} == LEGACY
    assert "sound_check" in NEW


@pytest.mark.parametrize("name", sorted(NEW))
def test_a_new_song_is_a_loop_of_whole_bars_in_its_scale(name: str) -> None:
    song = NEW[name]
    assert song.mode in SCALES
    for section in song.sections:
        assert song.section_steps(section) % song.bar_steps == 0, "sections are whole bars"
        for play in section.plays:
            length = song.patterns[play.pattern].length
            assert length % song.bar_steps == 0, f"{play.pattern} is not whole bars"
    assert LOOP_SECONDS[0] <= song.seconds <= LOOP_SECONDS[1]
    assert song.in_scale() >= MIN_IN_SCALE, f"{song.in_scale():.0%} of its notes are in {song.mode}"
    used = {song.patterns[play.pattern].instrument for s in song.sections for play in s.plays}
    assert used == set(song.instruments), "no instrument is defined and never played"
    assert len({section.kind for section in song.sections}) >= 2, "it has more than one part"


def test_no_two_new_songs_could_be_mistaken_for_each_other() -> None:
    for (first_name, first), (second_name, second) in combinations(sorted(NEW.items()), 2):
        pair = f"{first_name} and {second_name}"
        apart = abs(first.tempo - second.tempo) >= MIN_TEMPO_GAP or first.meter != second.meter
        assert apart, f"{pair}: same meter, tempos within {MIN_TEMPO_GAP} BPM"
        assert (first.key, first.mode) != (second.key, second.mode), f"{pair}: same key and mode"
    for name, song in NEW.items():
        others = set().union(*(other.timbres() for key, other in LOADED.items() if key != name))
        own = song.timbres() - others
        assert len(own) >= MIN_OWN_VOICES, f"{name} has only {len(own)} voices of its own"


def test_timbre_tells_instruments_apart_but_not_notes() -> None:
    string = Voice(wave="pluck", damp=0.3)
    assert timbre(string) == timbre(
        Voice(wave="pluck", damp=0.3, freq=99.0, volume=0.1, length=3.0)
    )
    assert timbre(string) != timbre(Voice(wave="pluck", damp=0.8))
    assert timbre(Voice(wave="pad", attack=0.3)) != timbre(Voice(wave="pad", attack=0.01))
    assert timbre(Voice(wave="square", duty=0.25)) != timbre(Voice(wave="square", duty=0.5))
    assert timbre(Voice(wave="bell", mod_ratio=2.0)) != timbre(Voice(wave="bell", mod_ratio=3.5))


def frames_of(path: Path) -> tuple[list[int], int, int, int]:
    with wave.open(str(path)) as reader:
        raw = reader.readframes(reader.getnframes())
        width, rate, channels = reader.getsampwidth(), reader.getframerate(), reader.getnchannels()
    values = [
        int.from_bytes(raw[index : index + 2], "little", signed=True)
        for index in range(0, len(raw), 2)
    ]
    return values, width, rate, channels


@pytest.mark.parametrize("name", sorted(LOADED))
def test_every_song_file_is_16_bit_unclipped_and_loops_without_a_click(name: str) -> None:
    values, width, rate, channels = frames_of(MUSIC_DIR / f"{name}.wav")
    assert (width * 8, rate, channels) == (MUSIC_BITS, SAMPLE_RATE, 1) and MUSIC_BITS == 16
    assert len(values) == pytest.approx(LOADED[name].seconds * SAMPLE_RATE, abs=2)
    peak = max(abs(value) for value in values)
    assert peak <= round(MASTER_HEADROOM * 32767) + 1, "no clipping"
    assert peak > 6000, "and not silent"
    if name == "victory":
        return  # played once, not looped
    steps = sorted(abs(b - a) for a, b in pairwise(values))
    usual = steps[int(len(steps) * SEAM_PERCENTILE)]
    seam = abs(values[0] - values[-1])
    assert seam <= max(usual, 1) * 1.5, f"the loop's seam jumps {seam}, the song's steps {usual}"


def test_the_manifest_tells_the_sound_test_about_every_song() -> None:
    manifest = json.loads(AUDIO_MANIFEST.read_text(encoding="utf-8"))
    for name, song in LOADED.items():
        entry = manifest["music"][name]
        assert entry["title"] == song.title and entry["tempo"] == song.tempo
        assert entry["key"] == song.key and entry["mode"] == song.mode
        assert entry["meter"] == f"{song.meter[0]}/{song.meter[1]}"


def test_rendering_a_new_song_reproduces_its_file() -> None:
    """Within one step per sample: float rounding may differ between machines."""
    song = NEW["sound_check"]
    data = song_wav(song)
    committed = (MUSIC_DIR / "sound_check.wav").read_bytes()
    assert len(data) == len(committed)
    with wave.open(BytesIO(data)) as a, wave.open(BytesIO(committed)) as b:
        new, old = a.readframes(a.getnframes()), b.readframes(b.getnframes())
    for index in range(0, len(old), 2 * 97):
        first = int.from_bytes(old[index : index + 2], "little", signed=True)
        second = int.from_bytes(new[index : index + 2], "little", signed=True)
        assert abs(first - second) <= 1
    assert isinstance(song, Song)
