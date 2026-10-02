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
