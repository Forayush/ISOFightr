"""Helpers for tests that look at a menu's own layer (decision D-072, M21)."""

from typing import Any

from isofightr.config import NATIVE_H, NATIVE_W

SOLID_ALPHA = 128
"""A pixel of the UI layer counts as covering the world from this alpha up."""
MAX_COVER = 0.35
"""The most of the screen a menu that shows the world may cover (decision D-072)."""


def ui_cover(window: Any, view: Any) -> float:
    """Return the share of the screen a menu's own layer covers: its UI sprites drawn alone
    on a clear buffer, and the pixels that came out solid counted."""
    window.switch_to()
    with window.pixel_buffer.drawing((0, 0, 0, 0)):
        view.ui.draw()
    data = bytes(window.pixel_buffer.framebuffer.read(components=4))
    solid = sum(1 for alpha in data[3::4] if alpha >= SOLID_ALPHA)
    return solid / (NATIVE_W * NATIVE_H)
