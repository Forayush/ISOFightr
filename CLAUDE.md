# CLAUDE.md: ISOFightr

ISOFightr is a local-multiplayer **isometric platform fighter** in **Python Arcade**. 2–4 fighters on floating pixel-art islands rack up **damage %** and try to launch each other past the **blast zones**. Combat follows **Super Smash Bros. (Ultimate) mechanics**: percent knockback, hitlag, hitstun, DI/SDI, shields, dodges, grabs and throws, ledges, specials. The art style is Super Smash Flash 2 animation energy combined with Pokémon Auto Chess isometric boards.

The full design and implementation plan lives in an **Obsidian vault** outside this repo, at `D:\dwthiw\isofighter\plan\`. It is never committed here (`plan/` is git-ignored).

## Start here
1. `D:\dwthiw\isofighter\plan\17 - Roadmap and Milestones.md`: what to build next (milestones M0–M11 with checkboxes).
2. Read the **specific plan note(s)** for the feature before writing code:

| Working on… | Read |
|---|---|
| Architecture, loop, package layout | `D:\dwthiw\isofighter\plan\02 - Technical Architecture.md` |
| Projection, depth sorting, camera, shadows | `D:\dwthiw\isofighter\plan\03 - Isometric World and Rendering.md` |
| Movement, jumps, gravity, stage collision, blast zones | `D:\dwthiw\isofighter\plan\04 - Movement and Physics.md` |
| Hitboxes, knockback, hitlag, DI, staling, projectiles | `D:\dwthiw\isofighter\plan\05 - Combat Core.md` |
| Shield, dodges, grabs and throws, ledges, teching | `D:\dwthiw\isofighter\plan\06 - Shield Dodge Grab and Ledge.md` |
| Fighter states, input buffer, move/character TOML | `D:\dwthiw\isofighter\plan\07 - Fighter State Machine and Move Data.md` |
| Controls, bindings, `InputFrame` | `D:\dwthiw\isofighter\plan\08 - Controls and Input.md` |
| Art specs / sprite pipeline | `D:\dwthiw\isofighter\plan\09 - Art Direction.md`, `D:\dwthiw\isofighter\plan\10 - Animation and Asset Pipeline.md` |
| Stages | `D:\dwthiw\isofighter\plan\11 - Stages.md` |
| Characters | `D:\dwthiw\isofighter\plan\12 - Roster.md` |
| Menus, HUD, modes, training mode | `D:\dwthiw\isofighter\plan\13 - Game Modes UI and Flow.md` |
| Audio / AI | `D:\dwthiw\isofighter\plan\14 - Audio.md`, `D:\dwthiw\isofighter\plan\15 - CPU AI.md` |
| Tests, debug keys, CLI flags, tools | `D:\dwthiw\isofighter\plan\16 - Testing Debug and Tooling.md` |
| Past decisions and open questions | `D:\dwthiw\isofighter\plan\19 - Decision Log.md` |

3. After finishing a task: tick its checkbox in the roadmap, set the plan note's frontmatter `status` to `implemented` where it applies, and update the note with real values if they changed. If behavior **diverges from the plan**, add an entry to `D:\dwthiw\isofighter\plan\19 - Decision Log.md`. Don't silently change the spec.

## Tech stack and commands
- Python **3.12**, **Arcade 3.x** (pinned), Pillow, uv, pytest, ruff, mypy
```bash
uv sync                                   # install deps
uv run python -m isofightr                # run the game (two Rooks on Sky Ruins)
uv run python -m isofightr --p1 rook --p2 rook --stage training_grid --seed 3
uv run python -m isofightr --headless --frames 10000   # headless sim run, prints the state hash
uv run pytest                             # fast tests (excludes @slow and @gl)
uv run pytest -m slow                     # soak tests
uv run pytest -m gl                       # render and device tests; need a real display, skipped in CI
uv run pytest --update-goldens            # re-record tests/goldens after an intended mechanic change
uv run ruff check . && uv run ruff format .
uv run mypy src/isofightr/sim
```
(As of M2 these flags exist: `--stage ID`, `--p1` to `--p4 ID`, `--seed N`, `--headless`, `--frames N`, `--test-pattern`, `--scale N`, `--fullscreen`, `--debug`. `--training`, `--cpu`, `--replay` and `--record` are still the target, not reality; each arrives with the milestone that builds what it controls.)

Controls as of M2 (`input/devices.py`): P1 keyboard `W/A/S/D` move, `Space` jump, `I` / `,` up and down modifiers, `Left Ctrl` walk; P2 arrows, `Num0` jump, `Num8` / `Num2` modifiers; a connected controller also drives its player. Debug keys: `F2` fighter info, `F3` stage overlay, `F8` restart, `C` camera clamp, `F11` fullscreen.

## Architecture rules (hard rules)
1. **`src/isofightr/sim/` must never import `arcade`, `pyglet`, or read clocks/`random`.** The sim is pure, deterministic Python driven only by `InputFrame`s. Use `match.rng` for randomness.
2. **Presentation never mutates sim state.** Rendering, audio and HUD read state and consume `match.events`.
3. **Fixed 60 Hz tick. All gameplay timing is in frames**, never seconds. Frames are **1-indexed**; frame ranges like `"14-16"` are **inclusive**.
4. **World space is 3D: `x`, `y` = ground plane, `z` = up. 1 unit = 1 tile edge.** Only `render/` converts to pixels:
   `sx = (x - y) * 16`, `sy = -(x + y) * 8 + z * 16` (Arcade is y-up). Depth key = `x + y` (bigger = closer = drawn later).
5. **All combat collision is 3D** (spheres and capsules in world space). Never use Arcade sprite collision for gameplay.
6. **Characters, moves and stages are data** (TOML in `assets/`), loaded into frozen dataclasses with strict validation (unknown keys = error). Python code only for special-move scripts in `sim/characters/<name>.py`.
7. Follow the **per-tick order of operations** in `D:\dwthiw\isofighter\plan\02 - Technical Architecture.md`. Hits are computed first, then applied simultaneously (trades).
8. Iterate fighters in **player index order**. Never iterate a `set` in the sim.
9. Tunable numbers go in data files, `sim/constants.py` (movement, physics, match flow), `sim/combat/constants.py` (combat) or `config.py` (presentation, devices, stage defaults). No inline magic numbers.

## Smash-mechanics essentials (full spec: `D:\dwthiw\isofighter\plan\05 - Combat Core.md` and `D:\dwthiw\isofighter\plan\06 - Shield Dodge Grab and Ledge.md`)
- Knockback: `KB = ((((p/10 + p*d/20) * 200/(w+100) * 1.4) + 18) * kbg/100 + bkb) * r`, where `p` is the target's % **after** the hit.
- Hitstun `= floor(KB * 0.4)`. Tumble at `KB ≥ 80`. Hitlag `= min(floor((d*0.65 + 6) * mult), 30)`.
- Launch direction = **yaw relative to attacker facing** + **elevation angle** (361 = Sakurai angle, negative = meteor).
- Controls: the stick moves on the ground plane, so **up/down moves use dedicated `up`/`down` modifier inputs**, and smash attacks use a `strong` input (decision D-008).
- Facing is 8-way (`Dir8`, named by **screen** compass). Stick input is screen-relative and converted to world: `wx = (u - v)/√2`, `wy = (-u - v)/√2`.

## Code style
- Type hints everywhere. `mypy` must pass on `sim/`. Prefer `@dataclass(slots=True)` (frozen for loaded data).
- Small modules, explicit names (`hitstun_frames`, not `hs`). Docstrings on public functions, including the plan note they implement.
- Format and lint with ruff (line length 100).
- No new dependencies without a Decision Log entry.

## Testing expectations
- Every gameplay change gets a **scenario test** (scripted `InputFrame`s against a `Match`, see `tests/helpers.py`: `make_match`, `hold`, `run`, `place`) plus unit tests for any formula.
- Golden state hashes in `tests/goldens/*.json` guard determinism and catch unintended mechanic changes. If a change intentionally alters them, re-record with `pytest --update-goldens` and say so in the commit message. Between them the goldens must visit every `StateId` (a test enforces it), so extend their input when you add states.
- Data validation tests load every TOML in `assets/`.
- Run `uv run pytest` and `uv run ruff check .` before committing.

## Arcade 3 gotchas
- Arcade 3's API differs significantly from 2.6, and most web examples are 2.6. **Check the pinned version's docs/source** (`uv run python -c "import arcade, inspect; ..."`) before using an API.
- Draw via `SpriteList` (batched). Avoid per-frame `arcade.draw_*` except in debug overlays. Create `arcade.Text` once and update it.
- Pixel art: render to the 640×360 offscreen buffer, nearest-neighbor filtering, integer upscale, round sprite positions to whole native pixels.
- DPI: importing `arcade` sets `pyglet.options.dpi_scaling = "stretch"`, which stretches the framebuffer by the OS display scale (2.5× on a 125% display) and ruins pixel art. `app.py` sets it to `"real"` before the window exists (decision D-017). Size things from `window.get_framebuffer_size()`, and always create the window through `GameWindow`.
- `View.on_draw` must call `self.clear()` first.

## Sim notes (as built in M2)
- State changes go through `change_state(match, fighter, state_id)` only. The tick a state is entered is its frame 1 (`enter` is that frame's logic); `step` runs from frame 2 on.
- States hold no data. Anything a state needs to remember is a field on `Fighter`, and must be added to `Match._canonical` so the state hash sees it.
- An `InputFrame` carries only what is held. Press edges, the 6-frame buffer and flicks come from the fighter's `InputBuffer` (decision D-024). Use `buffer.consume(Press.X)` so one press cannot trigger two things.
- Interrupt priority lives in `sim/states/interrupts.py` as ordered tuples. New actions slot into those tuples.

## Rendering notes (as built in M1 and M2)
- **World draw order comes from `render/depth.py`, never from a scalar sort key.** It is a topological sort over geometric constraints between sprites that overlap on screen (decision D-019). To add a new kind of world sprite, give it a `DynamicItem` (position, height, exact pixel rect) and let the sorter place it.
- The rect passed to the sorter must bound **every pixel the sprite draws**. A rect that is too small silently drops constraints.
- `uv run pytest -m gl` includes an occlusion sweep against a geometric oracle (`tests/test_world_render.py`). Run it after any change to sorting, tile art geometry or sprite anchoring.
- Modules without `arcade` imports (`render/iso.py`, `depth.py`, `camera.py`, `shadows.py`, `placeholder_art.py`, `pixel_scale.py`, `ui/pixel_font.py`, `input/keyboard.py`, `input/gamepad.py`, `headless.py`, `ai/random_inputs.py`) must stay that way: the CI test run has no display.
- A fighter the stage partly hides gets a faint "x-ray" copy drawn over the world (`OCCLUDED_FIGHTER_ALPHA`, decision D-025), because platforms and the island otherwise hide fighters completely in this projection.

## Assets and legal
- Sprites: 64×64 cells, feet pivot at (32, 8) from the bottom-left. Directions SE/NE are authored and SW/NW are mirrored. Exported from Aseprite to `assets/characters/<id>/sheet_<DIR>.png/.json`.
- Placeholder art is generated procedurally. Gameplay work must never block on art.
- **Original IP only.** Never add sprites, names, music or SFX from Smash, SSF2 or Pokémon. Log every third-party asset with its license in `assets/CREDITS.md`.

## Don'ts
- Don't add gameplay logic in `render/`, `scenes/` or `ai/`.
- Don't use `dt`-scaled movement in the sim.
- Don't edit files under `assets/**/sheet_*.png|json` by hand (they are generated).
- Don't change plan notes' meaning without a Decision Log entry. Fixing typos or filling in real values is fine.
- Don't rename notes in `D:\dwthiw\isofighter\plan\`. Obsidian `[[wikilinks]]` depend on the filenames.
