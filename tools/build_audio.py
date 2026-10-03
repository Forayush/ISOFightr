"""Render the game's sound effects and music from their text recipes.

Usage::

    uv run python tools/build_audio.py            # rebuild whatever changed
    uv run python tools/build_audio.py --force    # rebuild everything

Reads ``art_src/audio/sfx.toml`` and ``art_src/audio/music/*.toml`` and writes
``assets/audio/sfx/<name>.wav`` (16-bit), ``assets/audio/music/<id>.wav`` (8-bit) and
``assets/audio/manifest.json`` (names, lengths and the hash of each source, which the tests
compare with the sources so stale audio is caught). Plan note "14 - Audio", decision D-055.
Commit the rendered files with the recipe change.
"""

import argparse
import json

from isofightr.audio.recipes import (
    SYNTH_VERSION,
    load_song,
    sfx_wavs,
    song_wav,
    source_hash,
)
from isofightr.audio.synth import SAMPLE_RATE
from isofightr.data.paths import AUDIO_DIR, AUDIO_MANIFEST, AUDIO_SRC, MUSIC_DIR, SFX_DIR

WAV_HEADER_BYTES = 44


def main() -> None:
    """Parse arguments and render."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild even what is up to date")
    args = parser.parse_args()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    SFX_DIR.mkdir(exist_ok=True)
    MUSIC_DIR.mkdir(exist_ok=True)
    old = json.loads(AUDIO_MANIFEST.read_text(encoding="utf-8")) if AUDIO_MANIFEST.exists() else {}
    manifest: dict[str, object] = {"sample_rate": SAMPLE_RATE, "synth_version": SYNTH_VERSION}

    sfx_source = AUDIO_SRC / "sfx.toml"
    sfx_hash = source_hash(sfx_source, SYNTH_VERSION)
    old_sfx = old.get("sfx", {})
    current = all((SFX_DIR / f"{name}.wav").exists() for name in old_sfx.get("sounds", {}))
    if args.force or old_sfx.get("source") != sfx_hash or not current or not old_sfx:
        sounds = {}
        for name, data in sorted(sfx_wavs(sfx_source).items()):
            (SFX_DIR / f"{name}.wav").write_bytes(data)
            sounds[name] = round((len(data) - WAV_HEADER_BYTES) / 2 / SAMPLE_RATE, 3)
        for stale in SFX_DIR.glob("*.wav"):
            if stale.stem not in sounds:
                stale.unlink()
        manifest["sfx"] = {"source": sfx_hash, "sounds": sounds}
        print(f"rendered {len(sounds)} sound effects")
    else:
        manifest["sfx"] = old_sfx
        print("sound effects are up to date")

    music: dict[str, object] = {}
    old_music = old.get("music", {})
    for path in sorted((AUDIO_SRC / "music").glob("*.toml")):
        song = load_song(path)
        digest = source_hash(path, SYNTH_VERSION)
        target = MUSIC_DIR / f"{song.id}.wav"
        entry = old_music.get(song.id, {})
        if args.force or entry.get("source") != digest or not target.exists():
            target.write_bytes(song_wav(song))
            print(f"rendered {song.id}: {song.title}, {song.seconds:.1f} s")
        music[song.id] = {
            "source": digest,
            "title": song.title,
            "seconds": round(song.seconds, 3),
        }
    for stale in MUSIC_DIR.glob("*.wav"):
        if stale.stem not in music:
            stale.unlink()
    manifest["music"] = music
    text = json.dumps(manifest, indent=2) + "\n"
    AUDIO_MANIFEST.write_text(text, encoding="utf-8", newline="\n")
    print(AUDIO_MANIFEST)


if __name__ == "__main__":
    main()
