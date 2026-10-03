# ISOFightr

A local-multiplayer isometric platform fighter for 2 to 4 players, written in Python with
[Arcade](https://api.arcade.academy/). Fighters on floating pixel-art islands rack up damage
and launch each other past the blast zones. Four characters, five stages, CPU opponents
(levels 1 to 9), stock and time matches, training mode and replays.

Everything in the game is original: the sprites are rendered from scripted Blender models,
and the sound effects and music come from the game's own chiptune synthesizer. See
`assets/CREDITS.md`.

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m isofightr              # title screen and menus
uv run python -m isofightr --cpu 2:5    # straight into a match against a level 5 CPU
uv run python -m isofightr --training   # training mode
```

Useful flags: `--stage ID`, `--p1` to `--p4 ID` (`rook`, `bramble`, `zephyr`, `mote`),
`--cpu P:L`, `--record FILE` and `--replay FILE`, `--mute`, `--scale N`, `--fullscreen`.
`--help` lists them all.

## Controls

| | Player 1 (keyboard) | Player 2 (keyboard) | Gamepad |
|---|---|---|---|
| Move | `W` `A` `S` `D` | arrow keys | left stick |
| Jump | `Space` | `Num0` | X / Y |
| Attack | `J` | `Num4` | A |
| Special | `K` | `Num5` | B |
| Smash | `U` | `Num7` | LB, or flick the right stick sideways |
| Grab | `L` | `Num6` | RB |
| Shield | `Left Shift` | `Num1` | triggers |
| Up / down moves | `I` / `,` | `Num8` / `Num2` | right stick up / down |

Hold up or down with attack or special for up and down moves. Jump and attack together give
a short-hop aerial. Shield plus a direction dodges. Keys can be rebound in Settings, and the
pause menu (`Escape`) has a move list for your character with your own keys.

On character select, attack joins and readies, and grab adds a CPU.

## Develop

```bash
uv run pytest                 # fast tests
uv run pytest -m gl           # tests that open a window
uv run pytest -m slow         # soak tests
uv run ruff check . && uv run ruff format .
uv run mypy src/isofightr/sim src/isofightr/ai
uv run python tools/benchmark.py
```

Generated assets are committed; rebuild them after changing their sources in `art_src/`:

```bash
uv run python tools/build_audio.py        # sound effects and music
uv run python tools/build_art.py rook     # a character's sprites (needs Blender 4.5 LTS)
```

## Package for Windows

```bash
uv run python tools/package.py
```

builds `dist/ISOFightr/ISOFightr.exe` with PyInstaller (the whole `dist/ISOFightr` folder is
the game) and smoke tests it.
