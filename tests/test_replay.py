"""Tests for replays: recording, the file format, and exact playback.

Plan notes "16 - Testing Debug and Tooling" (``--record``, ``--replay``) and "02 - Technical
Architecture" (determinism).
"""

import json
from pathlib import Path

import pytest

from helpers import random_inputs
from isofightr.__main__ import EXIT_DATA_ERROR, EXIT_REPLAY_MISMATCH, main
from isofightr.data.replay_io import load_replay, match_for, numbered, save_replay
from isofightr.sim.input_frame import Button, Dir8, InputFrame
from isofightr.sim.match import MatchRules
from isofightr.sim.replay import (
    REPLAY_VERSION,
    Recorder,
    Replay,
    ReplayError,
    decode_frame,
    encode_frame,
    from_data,
    play_back,
    to_data,
)

RULES = MatchRules(stocks=2, countdown_frames=20, teams=(0, 1, 0), friendly_fire=True)


def recorded(ticks: int = 1500, rules: MatchRules = RULES, players: int = 3) -> Replay:
    """Play a match on random input while recording it."""
    recorder = Recorder("sky_ruins", ("rook",) * players, seed=7, rules=rules)
    blank = Replay("sky_ruins", ("rook",) * players, 7, rules, (), "")
    match = match_for(blank)
    for frames in random_inputs(11, ticks, players):
        recorder.record(frames)
        match.tick(frames)
    return recorder.finish(match)


def test_frames_encode_compactly_and_round_trip() -> None:
    plain = InputFrame(move=Dir8.SE.world * 0.37, vertical=-1, held=Button.JUMP | Button.SHIELD)
    assert encode_frame(plain) == [plain.move.x, plain.move.y, -1, 24]
    assert decode_frame(json.loads(json.dumps(encode_frame(plain)))) == plain
    smash = InputFrame(cstick=Dir8.N.world)
    assert len(encode_frame(smash)) == 6
    assert decode_frame(json.loads(json.dumps(encode_frame(smash)))) == smash


@pytest.mark.parametrize("bad", [None, [1, 2, 3], [0, 0, 5, 0], ["a", 0, 0, 0], [9.0, 0, 0, 0]])
def test_bad_frames_are_rejected(bad: object) -> None:
    with pytest.raises(ReplayError):
        decode_frame(bad)


def test_a_recorded_match_plays_back_to_the_same_state() -> None:
    replay = recorded()
    assert replay.ticks == 1500 and len(replay.final_hash) == 32
    match = match_for(replay)
    assert play_back(match, replay)
    assert match.frame == 1500 and match.state_hash() == replay.final_hash


def test_a_replay_survives_the_file_format_exactly(tmp_path: Path) -> None:
    replay = recorded()
    path = tmp_path / "deep" / "match.json"
    save_replay(path, replay)
    assert b"\r" not in path.read_bytes()
    loaded = load_replay(path)
    assert loaded == replay
    assert play_back(match_for(loaded), loaded)


def test_identical_ticks_are_run_length_encoded() -> None:
    still = (InputFrame(), InputFrame())
    moving = (InputFrame(move=Dir8.E.world), InputFrame())
    replay = Replay(
        "training_grid", ("rook", "rook"), 1, MatchRules(), (still,) * 300 + (moving,) * 5, "x"
    )
    data = to_data(replay)
    assert [run[0] for run in data["inputs"]] == [300, 5]
    assert data["version"] == REPLAY_VERSION and data["ticks"] == 305
    assert data["rules"]["stocks"] == 3 and data["rules"]["teams"] is None
    assert from_data(json.loads(json.dumps(data))) == replay


def test_playback_notices_when_the_game_has_changed() -> None:
    replay = recorded(ticks=600)
    assert not play_back(match_for(Replay(**{**_fields(replay), "seed": 8})), replay)
    slower = MatchRules(stocks=2, countdown_frames=20, teams=(0, 1, 0), friendly_fire=False)
    assert not play_back(match_for(Replay(**{**_fields(replay), "rules": slower})), replay)


def _fields(replay: Replay) -> dict[str, object]:
    return {
        "stage": replay.stage,
        "characters": replay.characters,
        "seed": replay.seed,
        "rules": replay.rules,
        "inputs": replay.inputs,
        "final_hash": replay.final_hash,
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"version": 99}, "replay version 99 is not supported"),
        ({"ticks": 3}, "replay says 3 ticks but holds"),
        ({"rules": {"stock": 3}}, "malformed replay"),
        ({"inputs": [[1, [[0, 0, 0, 0]]]]}, "a tick has 1 frames, the match has 3 players"),
        ({"characters": None}, "malformed replay"),
    ],
)
def test_malformed_replays_are_rejected(change: dict[str, object], message: str) -> None:
    data = to_data(recorded(ticks=10))
    data.update(change)
    with pytest.raises(ReplayError, match=message):
        from_data(data)
    with pytest.raises(ReplayError, match="must be a JSON object"):
        from_data([])


def test_loading_reports_the_file(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="cannot read replay"):
        load_replay(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    with pytest.raises(ReplayError, match=r"broken\.json: not valid JSON"):
        load_replay(broken)


def test_session_recordings_are_numbered() -> None:
    path = Path("replays/night.json")
    assert numbered(path, 1) == path
    assert numbered(path, 2) == Path("replays/night-2.json")
    assert numbered(path, 10) == Path("replays/night-10.json")


# --- command line -------------------------------------------------------------------------


def test_headless_record_and_replay(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "run.json"
    assert main(["--headless", "--frames", "800", "--seed", "5", "--record", str(path)]) == 0
    first = capsys.readouterr().out
    assert path.is_file() and "recorded 800 ticks" in first
    assert main(["--headless", "--replay", str(path)]) == 0
    second = capsys.readouterr().out
    assert "replay matches" in second
    replay = load_replay(path)
    assert replay.final_hash in first and replay.final_hash in second

    data = json.loads(path.read_text(encoding="utf-8"))
    data["seed"] = 6
    path.write_text(json.dumps(data), encoding="utf-8")
    assert main(["--headless", "--replay", str(path)]) == EXIT_REPLAY_MISMATCH
    assert "does NOT match" in capsys.readouterr().out


def test_a_bad_replay_file_is_a_data_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--headless", "--replay", str(tmp_path / "none.json")]) == EXIT_DATA_ERROR
    assert "cannot read replay" in capsys.readouterr().err


def test_the_state_hash_does_not_care_whether_held_is_an_int_or_a_flag() -> None:
    """Found by replays: frames read back from a file hold plain ints, live ones hold flags."""
    blank = Replay("training_grid", ("rook", "rook"), 3, MatchRules(), (), "")
    live, loaded = match_for(blank), match_for(blank)
    live.tick([InputFrame(held=Button.ATTACK | Button.JUMP)] * 2)
    loaded.tick([InputFrame(held=9)] * 2)
    assert live.state_hash() == loaded.state_hash()
