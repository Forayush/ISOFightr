"""Tests for audio: the synthesizer, the recipes, the cue mapping and the sound director.

Plan note "14 - Audio", decision D-055. Everything here is pure: playback goes through a
:class:`NullBackend`, so nothing makes a sound.
"""

import json
import wave
from io import BytesIO
from pathlib import Path

import pytest

from helpers import hold, make_match, neutral, place, run
from isofightr import config
from isofightr.audio.cues import Cue, MatchSounds, event_cues, hit_sound, required_sounds
from isofightr.audio.recipes import (
    SYNTH_VERSION,
    RecipeError,
    load_sfx,
    load_song,
    render_sfx,
    render_song,
    sfx_wavs,
    source_hash,
)
from isofightr.audio.sound_director import NullBackend, SoundDirector
from isofightr.audio.synth import SAMPLE_RATE, Voice, mix, note_hz, render_voice, wav_bytes
from isofightr.data.character_loader import load_character
from isofightr.data.paths import AUDIO_MANIFEST, AUDIO_SRC, MUSIC_DIR, SFX_DIR
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.settings import Settings
from isofightr.sim import events as ev
from isofightr.sim.input_frame import Button, Dir8
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect

SFX_SOURCE = AUDIO_SRC / "sfx.toml"
SONGS = sorted((AUDIO_SRC / "music").glob("*.toml"))
ORIGIN = Vec3(0.0, 0.0, 0.0)


# --- synthesizer -----------------------------------------------------------------------------


def test_note_names() -> None:
    assert note_hz("A4") == pytest.approx(440.0)
    assert note_hz("C4") == pytest.approx(261.626, abs=0.01)
    assert note_hz("C#5") == pytest.approx(note_hz("Db5"))
    assert note_hz("A5") == pytest.approx(880.0)
    for bad in ("H4", "A", "4A"):
        with pytest.raises(ValueError, match="not a note"):
            note_hz(bad)


@pytest.mark.parametrize("wave_name", ["square", "triangle", "saw", "sine", "noise"])
def test_every_wave_renders_within_range_and_is_deterministic(wave_name: str) -> None:
    voice = Voice(wave=wave_name, freq=440.0, length=0.05, volume=0.8)
    samples = render_voice(voice)
    assert len(samples) == round(0.05 * SAMPLE_RATE)
    assert max(abs(sample) for sample in samples) <= 0.8 + 1e-9
    assert any(sample != 0.0 for sample in samples)
    assert render_voice(voice) == samples
    with pytest.raises(ValueError, match="unknown wave"):
        render_voice(Voice(wave="organ"))


def test_the_envelope_fades_in_and_out() -> None:
    voice = Voice(wave="square", freq=100.0, length=0.2, attack=0.05, release=0.05, volume=1.0)
    samples = render_voice(voice)
    assert abs(samples[0]) < 0.01 and abs(samples[-1]) < 0.01
    middle = samples[len(samples) // 2]
    assert abs(middle) == pytest.approx(1.0)


def test_layers_are_delayed_and_repeated() -> None:
    click = Voice(wave="square", freq=1000.0, length=0.01, volume=0.5)
    late = Voice(
        wave="square", freq=1000.0, length=0.01, volume=0.5, delay=0.1, repeat=2, repeat_gap=0.05
    )
    samples = mix([click, late])
    assert len(samples) == round(0.15 * SAMPLE_RATE) + round(0.01 * SAMPLE_RATE)
    gap = samples[round(0.03 * SAMPLE_RATE) : round(0.09 * SAMPLE_RATE)]
    assert all(sample == 0.0 for sample in gap)


@pytest.mark.parametrize("bits", [8, 16])
def test_wav_files_are_mono_at_the_synth_rate(bits: int) -> None:
    data = wav_bytes([0.0, 1.0, -1.0, 2.0], bits)
    with wave.open(BytesIO(data)) as reader:
        assert (reader.getnchannels(), reader.getframerate()) == (1, SAMPLE_RATE)
        assert reader.getsampwidth() == bits // 8 and reader.getnframes() == 4


# --- recipes ---------------------------------------------------------------------------------


def test_every_sound_the_game_asks_for_has_a_recipe_and_a_file() -> None:
    recipes = load_sfx(SFX_SOURCE)
    needed = required_sounds() | {"ui_move", "ui_select", "ui_back", "ui_pick"}
    assert needed <= set(recipes)
    files = {path.stem for path in SFX_DIR.glob("*.wav")}
    assert files == set(recipes), "run tools/build_audio.py"


def test_included_sounds_are_layered() -> None:
    recipes = load_sfx(SFX_SOURCE)
    combined = recipes["hit_heavy_fire"]
    assert len(combined) == len(recipes["hit_heavy"]) + len(recipes["fire"])
    assert len(render_sfx(combined)) >= len(render_sfx(recipes["hit_heavy"]))


def test_bad_recipes_are_rejected(tmp_path: Path) -> None:
    def sfx(text: str) -> Path:
        path = tmp_path / "sfx.toml"
        path.write_text(text, encoding="utf-8")
        return path

    with pytest.raises(RecipeError, match="unknown key"):
        load_sfx(sfx('[[a.layers]]\nwave = "square"\nwobble = 3\n'))
    with pytest.raises(RecipeError, match="unknown sound"):
        load_sfx(sfx('[a]\ninclude = ["b"]\n'))
    with pytest.raises(RecipeError, match="includes itself"):
        load_sfx(sfx('[a]\ninclude = ["a"]\n'))
    with pytest.raises(RecipeError, match="no layers"):
        load_sfx(sfx("[a]\n"))


@pytest.mark.parametrize("path", SONGS, ids=lambda path: path.stem)
def test_songs_load_and_fill_whole_bars(path: Path) -> None:
    song = load_song(path)
    steps_per_bar = song.steps_per_beat * 4
    for section in song.sequence:
        assert song.section_steps(section) % steps_per_bar == 0, "sections are whole bars"
    assert 5.0 < song.seconds < 90.0
    assert (MUSIC_DIR / f"{song.id}.wav").exists(), "run tools/build_audio.py"


def test_the_committed_audio_matches_its_sources() -> None:
    """The manifest stores a hash of each recipe; a changed recipe needs a rebuild."""
    manifest = json.loads(AUDIO_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["synth_version"] == SYNTH_VERSION
    assert manifest["sfx"]["source"] == source_hash(SFX_SOURCE, SYNTH_VERSION), (
        "sfx.toml changed: run tools/build_audio.py"
    )
    assert set(manifest["music"]) == {path.stem for path in SONGS}
    for path in SONGS:
        assert manifest["music"][path.stem]["source"] == source_hash(path, SYNTH_VERSION), (
            f"{path.name} changed: run tools/build_audio.py"
        )


def test_rendering_reproduces_the_committed_files() -> None:
    """Within one step per sample: float rounding may differ between machines."""
    for name, data in list(sfx_wavs(SFX_SOURCE).items())[:12]:
        committed = (SFX_DIR / f"{name}.wav").read_bytes()
        assert len(committed) == len(data), name
        with wave.open(BytesIO(committed)) as a, wave.open(BytesIO(data)) as b:
            old, new = a.readframes(a.getnframes()), b.readframes(b.getnframes())
        for index in range(0, len(old), 2):
            first = int.from_bytes(old[index : index + 2], "little", signed=True)
            second = int.from_bytes(new[index : index + 2], "little", signed=True)
            assert abs(first - second) <= 1, name
    victory = load_song(AUDIO_SRC / "music" / "victory.toml")
    assert len(render_song(victory)) == round(victory.seconds * SAMPLE_RATE)


def test_every_stage_names_a_song_that_exists() -> None:
    for stage_id in list_stage_ids():
        music = load_stage(stage_id).music
        assert music and (MUSIC_DIR / f"{music}.wav").exists(), stage_id
    for song in (config.AUDIO_MENU_SONG, config.AUDIO_VICTORY_SONG):
        assert (MUSIC_DIR / f"{song}.wav").exists()


# --- cues ------------------------------------------------------------------------------------


def test_hit_sounds_follow_knockback_tiers_and_the_element() -> None:
    assert hit_sound(10.0, Effect.NORMAL) == "hit_light"
    assert hit_sound(40.0, Effect.NORMAL) == "hit_medium"
    assert hit_sound(119.0, Effect.SLASH) == "hit_heavy_slash"
    assert hit_sound(200.0, Effect.ELECTRIC) == "hit_ko_electric"


def test_events_become_cues() -> None:
    events = [
        ev.JumpEvent(0, ev.JumpKind.AIR, ORIGIN),
        ev.LandEvent(0, ORIGIN, 0.26),
        ev.LandEvent(0, ORIGIN, 0.05),
        ev.KoEvent(1, ORIGIN, Vec3(1.0, 0.0, 0.0), 2),
        ev.ShieldHitEvent(0, 1, 5.0, ORIGIN, 4, True),
        ev.ProjectileEvent(0, ORIGIN, False),
        ev.MatchEndEvent(0),
    ]
    cues = event_cues(events)
    assert [cue.name for cue in cues] == [
        "double_jump",
        "land_heavy",
        "land_light",
        "ko_blast",
        "parry",
        "game",
    ]
    assert cues[3].duck and cues[5].duck and not cues[0].duck


def test_state_changes_make_swings_dashes_and_shields() -> None:
    match = make_match()
    place(match, match.fighters[0], 6.0, 6.0)
    sounds = MatchSounds()
    sounds.observe(match)

    def names(frames: list) -> list[str]:
        heard = []
        for frame in frames:
            run(match, [frame])
            heard += [cue.name for cue in sounds.observe(match) if cue.position is not None]
        return heard

    assert names(hold(buttons=Button.ATTACK, frames=1) + neutral(3)) == ["swing_light"]
    run(match, neutral(40))
    sounds.observe(match)
    assert names(hold(buttons=Button.STRONG, frames=1) + neutral(2)) == ["swing_heavy"]
    run(match, neutral(60))
    sounds.observe(match)
    assert "dash" in names(hold(Dir8.SE, frames=3))
    run(match, neutral(40))
    sounds.observe(match)
    assert names(hold(buttons=Button.SHIELD, frames=2)) == ["shield_up"]


def test_the_countdown_beeps_three_times_then_go() -> None:
    match = Match.create(
        load_stage("training_grid"),
        [load_character("rook")] * 2,
        rules=MatchRules(stocks=3, countdown_frames=180),
    )
    sounds = MatchSounds()
    heard = []
    for tick in range(200):
        heard += [(tick, cue.name) for cue in sounds.observe(match)]
        run(match, neutral(1))
    assert [name for _, name in heard] == ["countdown", "countdown", "countdown", "go"]
    assert [tick for tick, _ in heard] == [0, 60, 120, 180]


# --- sound director --------------------------------------------------------------------------


def director(**settings: int) -> tuple[SoundDirector, NullBackend]:
    backend = NullBackend()
    return SoundDirector(backend, Settings(**settings)), backend


def test_volumes_come_from_the_settings() -> None:
    sound, backend = director(master_volume=5, sfx_volume=10, music_volume=8)
    assert sound.sfx_volume == pytest.approx(0.5) and sound.music_volume == pytest.approx(0.4)
    assert sound.play("jump")
    sound.play_music("menu")
    assert [played.volume for played in backend.played] == pytest.approx([0.5, 0.4])
    sound.apply_settings(Settings(master_volume=10, music_volume=10))
    assert backend.volumes["menu"] == pytest.approx(1.0), "the music follows at once"
    muted, silent = director(sfx_volume=0)
    assert not muted.play("jump") and silent.played == []


def test_pan_is_clamped_and_pitch_varies_a_little() -> None:
    sound, backend = director()
    sound.play("jump", pan=2.0)
    sound.play("jump", pan=-0.2)
    assert [played.pan for played in backend.played] == [config.AUDIO_MAX_PAN, -0.2]
    assert all(played.speed == 1.0 for played in backend.played)
    speeds = []
    for _ in range(20):
        sound.tick()
        sound.tick()
        sound.tick()
        sound.play("hit_light", vary=True)
        speeds.append(backend.played[-1].speed)
    assert len(set(speeds)) > 5
    assert all(abs(speed - 1.0) <= config.AUDIO_PITCH_VARIATION for speed in speeds)


def test_at_most_three_copies_of_a_sound_start_together() -> None:
    sound, backend = director()
    started = [sound.play("hit_light") for _ in range(5)]
    assert started == [True, True, True, False, False]
    for _ in range(config.AUDIO_INSTANCE_TICKS):
        sound.tick()
    assert sound.play("hit_light")
    assert sound.play("hit_heavy"), "other sounds are not affected"
    assert len(backend.played) == 5


def test_music_switches_ducks_and_recovers() -> None:
    sound, backend = director(music_volume=10)
    sound.play_music("menu")
    sound.play_music("menu")
    assert backend.names() == ["menu"], "the same looping song carries on"
    sound.play_music("sky_ruins")
    assert backend.stopped == ["menu"] and sound.song == "sky_ruins"
    sound.play_cues([Cue("ko_blast", duck=True)])
    assert backend.volumes["sky_ruins"] == pytest.approx(config.AUDIO_DUCK_VOLUME)
    for _ in range(config.AUDIO_DUCK_TICKS):
        sound.tick()
    assert backend.volumes["sky_ruins"] == pytest.approx(1.0)
    sound.play_music("")
    assert sound.song == "" and backend.stopped[-1] == "sky_ruins"


def test_an_unknown_sound_is_skipped_quietly() -> None:
    sound, backend = director()
    assert not sound.play("kazoo")
    sound.play_music("kazoo")
    assert backend.played == [] and sound.song == ""


def test_cues_are_panned_by_where_they_happened() -> None:
    sound, backend = director()
    sound.play_cues(
        [Cue("jump", Vec3(1.0, 0.0, 0.0)), Cue("go")], lambda position: position.x * 0.3
    )
    assert [played.pan for played in backend.played] == [pytest.approx(0.3), 0.0]
