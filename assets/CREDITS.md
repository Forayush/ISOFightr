# Asset credits

ISOFightr uses **original IP only**. Nothing here may come from Super Smash Bros., Super Smash
Flash 2 or Pokémon; those are style references, never sources.

Every third-party asset (sprite, tile, font, sound, music) must be listed below **before** it is
committed, with a license that allows redistribution in this project.

## Third-party assets

| Asset (path) | Author | Source | License |
|---|---|---|---|
| Resurrect 64 colour palette (`art_src/palettes/resurrect64.toml`; every sprite colour comes from it) | Kerrie Lake | https://lospec.com/palette-list/resurrect-64 | No formal licence on the page; the author answered "Absolutely!" when asked about use in a commercial game (comment on that page, checked 2026-10-03). A list of colours, not artwork. |

| Departure Mono (`assets/fonts/DepartureMono-Regular.otf`; body text) | Helena Zhang | https://departuremono.com, https://github.com/rektdeckard/departure-mono | SIL Open Font License 1.1 (`assets/fonts/DepartureMono-OFL.txt`, shipped with the font). Unmodified. |
| Jersey 10, Jersey 20, Jersey 25 (`assets/fonts/Jersey*-Regular.ttf`; headings and the damage number) | The Soft Type Project Authors (Sarah Cadigan-Fried) | https://github.com/scfried/soft-type-jersey, via https://github.com/google/fonts | SIL Open Font License 1.1 (`assets/fonts/Jersey-OFL.txt`, shipped with the fonts). Unmodified. |
| Tiny5 (`assets/fonts/Tiny5-Regular.ttf`; fine print) | The Tiny5 Project Authors (Stefan Schmidt) | https://github.com/Gissio/font_tiny5, via https://github.com/google/fonts | SIL Open Font License 1.1 (`assets/fonts/Tiny5-OFL.txt`, shipped with the font). Unmodified. |

The three font licences were read on 2026-10-06: each is the standard OFL 1.1 text with no
Reserved Font Name. The fonts are bundled unmodified, never sold on their own, and each ships
with its copyright notice and licence, which is what the OFL asks for.

## Original and generated assets

- Fighter sprites (`assets/characters/*/sprites/`) are rendered from original 3D models that
  Claude Code scripts in Blender (`art_src/`, `tools/blender/`) and packed by
  `tools/build_art.py` (decision D-044). Blender is only a tool; nothing of Blender is shipped.
- Sound effects and music (`assets/audio/`) are original: they are written as synthesizer
  recipes and note patterns (`art_src/audio/`) and rendered by the game's own chiptune synth
  (`isofightr.audio.synth`, `tools/build_audio.py`; decision D-055). Nothing is sampled or
  downloaded.
- UI art is original: icons are drawn as text recipes (`art_src/ui/icons.toml`), panels,
  buttons and the menu backdrop are drawn by code (`isofightr.ui.kit_art`,
  `isofightr.ui.backdrop`, `tools/build_ui_art.py`; decision D-061). The layout references
  for M13 were used for layout only; no art, colour scheme, icon, font or wording was copied.
- Placeholder art is generated procedurally in code (Pillow) and needs no credit. The M0 test
  pattern's label text uses Pillow's built-in bitmap font, drawn at runtime; no font file is
  shipped.
