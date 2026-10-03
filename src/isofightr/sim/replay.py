"""Replays: a match's seed, setup and every input frame, in a compact JSON-friendly form.

Plan note "16 - Testing Debug and Tooling" (``--record``, ``--replay``) and "02 - Technical
Architecture" (determinism: the same inputs and seed give the same state hash). A replay
stores what was *held* each tick for each player, run-length encoded, plus the state hash the
match ended on, so playing it back can be checked. Reading and writing files is in
:mod:`isofightr.data.replay_io`.
Pure sim code: never import ``arcade`` or ``pyglet``, read a clock, or use ``random``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Final

from isofightr.sim.input_frame import InputFrame
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.math3d import Vec2

REPLAY_VERSION: Final[int] = 1

type Tick = tuple[InputFrame, ...]
"""One tick's input: a frame per player, in player order."""


class ReplayError(ValueError):
    """A replay file is malformed or of an unknown version."""


@dataclass(frozen=True, slots=True)
class Replay:
    """Everything needed to play a match again exactly."""

    stage: str
    characters: tuple[str, ...]
    seed: int
    rules: MatchRules
    inputs: tuple[Tick, ...]
    final_hash: str
    """State hash after the last recorded tick."""

    @property
    def ticks(self) -> int:
        """Number of recorded ticks."""
        return len(self.inputs)


def _no_ticks() -> list[Tick]:
    return []


@dataclass(slots=True)
class Recorder:
    """Collects the input of a running match, tick by tick."""

    stage: str
    characters: tuple[str, ...]
    seed: int
    rules: MatchRules
    inputs: list[Tick] = field(default_factory=_no_ticks)
    final: Replay | None = None
    """The finished replay, once whoever runs the match has called :meth:`finish`."""

    def record(self, frames: Sequence[InputFrame]) -> None:
        """Note the frames that are about to be handed to ``Match.tick``."""
        self.inputs.append(tuple(frames))

    def finish(self, match: Match) -> Replay:
        """Return the replay of everything recorded so far, ending on ``match``'s state."""
        return Replay(
            stage=self.stage,
            characters=self.characters,
            seed=self.seed,
            rules=self.rules,
            inputs=tuple(self.inputs),
            final_hash=match.state_hash(),
        )


def encode_frame(frame: InputFrame) -> list[float | int]:
    """Return a frame as a short list: move x, move y, vertical, held, and the smash-stick
    direction when there is one."""
    encoded: list[float | int] = [frame.move.x, frame.move.y, frame.vertical, frame.held]
    if frame.cstick is not None:
        encoded += [frame.cstick.x, frame.cstick.y]
    return encoded


def decode_frame(encoded: object) -> InputFrame:
    """Rebuild a frame from :func:`encode_frame`'s list."""
    if not isinstance(encoded, list) or len(encoded) not in (4, 6):
        raise ReplayError(f"an input frame must be a list of 4 or 6 numbers, got {encoded!r}")
    try:
        cstick = Vec2(float(encoded[4]), float(encoded[5])) if len(encoded) == 6 else None
        return InputFrame(
            move=Vec2(float(encoded[0]), float(encoded[1])),
            vertical=int(encoded[2]),
            held=int(encoded[3]),
            cstick=cstick,
        )
    except (TypeError, ValueError) as error:
        raise ReplayError(f"bad input frame {encoded!r}: {error}") from error


def to_data(replay: Replay) -> dict[str, Any]:
    """Return a replay as plain JSON-serializable data. Identical consecutive ticks are
    stored once with a repeat count."""
    runs: list[list[Any]] = []
    previous: Tick | None = None
    for tick in replay.inputs:
        if tick == previous:
            runs[-1][0] += 1
        else:
            runs.append([1, [encode_frame(frame) for frame in tick]])
            previous = tick
    rules = asdict(replay.rules)
    if rules["teams"] is not None:
        rules["teams"] = list(rules["teams"])
    return {
        "version": REPLAY_VERSION,
        "stage": replay.stage,
        "characters": list(replay.characters),
        "seed": replay.seed,
        "rules": rules,
        "ticks": replay.ticks,
        "hash": replay.final_hash,
        "inputs": runs,
    }


def from_data(data: object) -> Replay:
    """Rebuild a replay from :func:`to_data`'s output, checking it as it goes."""
    if not isinstance(data, dict):
        raise ReplayError("a replay must be a JSON object")
    version = data.get("version")
    if version != REPLAY_VERSION:
        raise ReplayError(f"replay version {version!r} is not supported (need {REPLAY_VERSION})")
    try:
        characters = tuple(str(name) for name in data["characters"])
        rule_values = dict(data["rules"])
        # Replays from before the short-hop macro (D-053) were played without it.
        rule_values.setdefault("short_hop_macro", False)
        if rule_values.get("teams") is not None:
            rule_values["teams"] = tuple(rule_values["teams"])
        rules = MatchRules(**rule_values)
        inputs: list[Tick] = []
        for count, frames in data["inputs"]:
            tick = tuple(decode_frame(frame) for frame in frames)
            if len(tick) != len(characters):
                raise ReplayError(
                    f"a tick has {len(tick)} frames, the match has {len(characters)} players"
                )
            inputs.extend([tick] * int(count))
        replay = Replay(
            stage=str(data["stage"]),
            characters=characters,
            seed=int(data["seed"]),
            rules=rules,
            inputs=tuple(inputs),
            final_hash=str(data["hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ReplayError):
            raise
        raise ReplayError(f"malformed replay: {error!r}") from error
    if replay.ticks != data.get("ticks"):
        raise ReplayError(f"replay says {data.get('ticks')} ticks but holds {replay.ticks}")
    return replay


def play_back(match: Match, replay: Replay) -> bool:
    """Run every recorded tick on a freshly created match. Returns whether the match ends on
    the recorded state hash (it does not if the game's data or rules have changed since)."""
    for tick in replay.inputs:
        match.tick(tick)
    return match.state_hash() == replay.final_hash
