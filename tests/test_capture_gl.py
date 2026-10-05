"""Smoke test for the offscreen capture tool (plan note 16, decision D-060)."""

from typing import Any

import pytest

pytestmark = pytest.mark.gl


def test_a_scripted_battle_is_captured_as_a_contact_sheet(window: Any) -> None:
    from isofightr.capture import KeyStep, capture, parse_script

    script = parse_script("K@2, K!3")
    assert [(step.tick, step.down) for step in script] == [(2, True), (3, False)]
    assert isinstance(script[0], KeyStep)
    with pytest.raises(ValueError, match="bad key step"):
        parse_script("NOPE@2")
    sheet = capture(
        window,
        ["rook", "rook"],
        "training_grid",
        script,
        ticks=[5, 25],
        positions=[(4.0, 6.0, 0.0), (8.0, 6.0, 0.0)],
        crop=(160, 60, 320, 200),
        scale=2,
    )
    assert sheet.size == (2 * 320 * 2, 200 * 2), "two frames side by side, at 2x"
    colours = sheet.getcolors(maxcolors=100000)
    assert colours is not None and len(colours) > 8, "something was drawn"
    first = sheet.crop((0, 0, 640, 400))
    second = sheet.crop((640, 0, 1280, 400))
    assert first.tobytes() != second.tobytes(), "the projectile moved between the two ticks"
