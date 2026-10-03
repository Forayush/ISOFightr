"""Where data files live on disk.

Plan note "02 - Technical Architecture" (package layout): game data sits in ``assets/`` at the
repo root, next to ``src/``. Packaging (M11) will need to revisit this lookup.
"""

from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ASSETS_DIR: Final[Path] = REPO_ROOT / "assets"
STAGES_DIR: Final[Path] = ASSETS_DIR / "stages"
STAGE_FILE_NAME: Final[str] = "stage.toml"
CHARACTERS_DIR: Final[Path] = ASSETS_DIR / "characters"
CHARACTER_FILE_NAME: Final[str] = "fighter.toml"
MOVES_DIR_NAME: Final[str] = "moves"
AUDIO_DIR: Final[Path] = ASSETS_DIR / "audio"
SFX_DIR: Final[Path] = AUDIO_DIR / "sfx"
MUSIC_DIR: Final[Path] = AUDIO_DIR / "music"
AUDIO_MANIFEST: Final[Path] = AUDIO_DIR / "manifest.json"
AUDIO_SRC: Final[Path] = REPO_ROOT / "art_src" / "audio"
"""The sound and song recipes the audio in ``assets/audio`` is rendered from (not shipped)."""
