"""Tests for where the game looks for its data (plan note 02; decision D-056)."""

import sys
from pathlib import Path

import pytest

from isofightr.data import paths


def test_assets_sit_at_the_repo_root_when_run_from_source() -> None:
    assert paths.ASSETS_DIR == paths.REPO_ROOT / "assets"
    assert (paths.ASSETS_DIR / "characters" / "rook" / "fighter.toml").is_file()
    assert (paths.REPO_ROOT / "src" / "isofightr").is_dir()


def test_the_packaged_game_looks_in_its_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths._root() == tmp_path
