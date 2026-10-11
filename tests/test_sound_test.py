"""The sound test's lists and text (decision D-063, M14 group 2). Pure: no window. The screen
is driven in ``tests/test_sound_test_gl.py``."""

import json
from pathlib import Path

from isofightr.audio.cues import required_sounds
from isofightr.config import AUDIO_MENU_SONG
from isofightr.data.paths import MUSIC_DIR, SFX_DIR
from isofightr.data.stage_loader import list_stage_ids, load_stage
from isofightr.scenes import sound_test_model as model
from isofightr.ui import font

MANIFEST = model.load_manifest()
INFO_TEXT_WIDTH = 190
"""The room for a line of facts beside the level bars' panel edge."""


def test_every_song_and_sound_in_the_game_is_listed() -> None:
    songs = model.music_tracks(MANIFEST)
    assert {track.id for track in songs} == {path.stem for path in MUSIC_DIR.glob("*.wav")}
    assert [track.title.lower() for track in songs] == sorted(t.title.lower() for t in songs)
    sounds = model.sound_tracks(MANIFEST)
    assert {track.id for track in sounds} == {path.stem for path in SFX_DIR.glob("*.wav")}
    assert set(required_sounds()) <= {track.id for track in sounds}
    assert [track.id for track in sounds] == sorted(track.id for track in sounds)
    assert all(
        track.kind == model.MUSIC and track.loops for track in songs if track.id != "victory"
    )
    assert not next(track for track in songs if track.id == "victory").loops
    assert not any(track.loops for track in sounds)
    for stage_id in list_stage_ids():
        assert load_stage(stage_id).music in {track.id for track in songs}
    assert AUDIO_MENU_SONG in {track.id for track in songs}


def test_a_songs_facts_say_where_it_plays_and_what_it_is() -> None:
    songs = model.music_tracks(MANIFEST, {"sound_check": "The sound test", "menu": "The menus"})
    check = next(track for track in songs if track.id == "sound_check")
    assert check.title == "Sound Check"
    assert check.facts == ("THE SOUND TEST", "100 BPM", "G MAJOR", "4/4 TIME", "0:53")
    menu = next(track for track in songs if track.id == "menu")
    assert menu.facts[0] == "THE MENUS" and menu.facts[-1] == "0:36"
    assert "MAJOR" not in " ".join(menu.facts), "a song from before D-063 states no key"
    plain = next(track for track in model.music_tracks(MANIFEST) if track.id == "menu")
    assert plain.facts[0].endswith("BPM"), "nothing about where, if nobody says"
    for track in songs:
        assert 1 <= len(track.facts) <= model.FACT_LINES
        for line in (track.title.upper(), *track.facts):
            assert font.text_width(line) <= INFO_TEXT_WIDTH, line


def test_lengths_read_as_a_clock() -> None:
    assert (
        model.clock(52.8) == "0:53" and model.clock(60.0) == "1:00" and model.clock(125.4) == "2:05"
    )
    assert model.clock(0.213) == "0.21 s" and model.clock(1.0) == "0:01"
    sound = model.sound_tracks({"sfx": {"sounds": {"ui_move": 0.05}}})[0]
    assert (sound.id, sound.title, sound.facts) == ("ui_move", "ui move", ("0.05 s",))


def test_a_broken_manifest_lists_nothing(tmp_path: Path) -> None:
    assert model.load_manifest(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert model.load_manifest(bad) == {}
    bad.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert model.load_manifest(bad) == {}
    assert model.music_tracks({}) == [] and model.sound_tracks({}) == []
    assert model.music_tracks({"music": {"a": 3, "b": {"title": "B"}}})[0].facts == ("0.00 s",)
    assert model.sound_tracks({"sfx": 4}) == []


def test_the_list_scrolls_only_as_far_as_the_cursor_needs() -> None:
    count, visible = 68, model.VISIBLE_ROWS
    first = 0
    seen = []
    for cursor in range(count):
        first = model.first_shown(cursor, first, count)
        assert first <= cursor < first + visible
        seen.append(first)
    assert seen[:visible] == [0] * visible and seen[-1] == count - visible
    assert model.first_shown(3, first, count) == 3, "back up: the cursor's row leads"
    assert model.first_shown(0, 40, 5) == 0, "a short list never scrolls"
    assert model.first_shown(67, 0, count) == count - visible, "round the end in one go"
    assert model.moved(0, -1, count) == 67 and model.moved(67, 1, count) == 0
    assert model.moved(0, 1, 0) == 0
    assert model.position(2, 68) == "3 / 68" and model.position(0, 0) == "0 / 0"


def test_every_row_fits_its_strip() -> None:
    row_text_width = 292 - 2 * 8 - 12
    for track in (*model.music_tracks(MANIFEST), *model.sound_tracks(MANIFEST)):
        name, length = font.text_width(track.title.upper()), font.text_width(track.facts[-1])
        assert name + length <= row_text_width, track.title
