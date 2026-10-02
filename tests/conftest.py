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


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--update-goldens``: re-record golden state hashes after an intended change."""
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="rewrite tests/goldens/*.json with the current state hashes",
    )


@pytest.fixture
def update_goldens(request: pytest.FixtureRequest) -> bool:
    """Whether this run should re-record golden hashes instead of checking them."""
    return bool(request.config.getoption("--update-goldens"))
