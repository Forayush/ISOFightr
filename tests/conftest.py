"""Shared pytest fixtures."""

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from isofightr.app import GameWindow


@pytest.fixture(scope="session")
def window() -> Iterator["GameWindow"]:
    """One hidden game window shared by every ``gl`` test (they are opt-in: ``pytest -m gl``).

    Imported lazily so the default test run never creates an OpenGL context.
    """
    from isofightr.app import GameWindow

    game_window = GameWindow(visible=False)
    yield game_window
    game_window.close()
