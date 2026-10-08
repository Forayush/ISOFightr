"""What character select writes: prompts in each panel's own keys, a footer that fits, one-line
messages, and which keys two keyboard layouts share (decision D-062, M13 group 10).

Pure: no window. The screen is driven in ``tests/test_flow_gl.py``.
"""

from dataclasses import replace

import pytest

from isofightr.config import NATIVE_W
from isofightr.input.gamepad import PAD_LAYOUTS
from isofightr.scenes import select_text as text
from isofightr.scenes.setup import MatchSetup, can_start
from isofightr.settings import KEYBOARD_ACTIONS, Settings, shared_keys
from isofightr.ui import font
from isofightr.ui.hints import device_labels, fit_hint, hint_text

USER_ARROWS = {
    "move_up": "MOTION_UP",
    "move_down": "DOWN",
    "move_left": "LEFT",
    "move_right": "MOTION_RIGHT",
    "up": "Z",
    "down": "LCTRL",
    "attack": "X",
    "special": "C",
    "strong": "S",
    "grab": "V",
    "jump": "LSHIFT",
    "shield": "SPACE",
    "walk": "",
    "taunt": "NUM_9",
}
"""The arrows layout from the user's own settings file."""
LONG_KEYS = dict.fromkeys(KEYBOARD_ACTIONS, "NUM_PAGE_DOWN") | {
    "move_up": "BRACKETLEFT",
    "move_left": "NUM_PAGE_UP",
    "move_down": "SCROLLLOCK",
    "move_right": "NUM_MULTIPLY",
}
"""A layout with the longest key names there are: nothing may overflow even with it."""
ARROWS, SOLO, PAD0 = "keyboard:arrows", "keyboard:solo", "pad:0"


def user_settings() -> Settings:
    base = Settings()
    return replace(
        base, slot_devices=(ARROWS, "", "", ""), keys={**base.keys, "arrows": dict(USER_ARROWS)}
    )


def long_settings() -> Settings:
    base = Settings()
    return replace(base, keys={"solo": dict(LONG_KEYS), "arrows": dict(LONG_KEYS)})


def every_setup() -> list[tuple[str, Settings, str]]:
    cases = [
        ("defaults, WASD", Settings(), SOLO),
        ("defaults, arrows", Settings(), ARROWS),
        ("the user's arrows", user_settings(), ARROWS),
        ("longest key names", long_settings(), SOLO),
    ]
    for name, bindings in PAD_LAYOUTS.items():
        cases.append((f"pad {name}", Settings().with_pad(0, bindings), PAD0))
    return cases


def width(line: str) -> int:
    return font.text_width(line)


# --- names and prompts ---------------------------------------------------------------------


def test_device_names_are_short_and_say_which() -> None:
    assert text.device_name(SOLO) == "WASD KEYS" and text.device_name(ARROWS) == "ARROW KEYS"
    assert text.device_name("pad:0") == "PAD 1" and text.device_name("pad:3") == "PAD 4"
    assert text.device_name("") == "" and text.device_name("mystery") == "MYSTERY"


def test_a_panels_hint_uses_that_panels_own_keys() -> None:
    settings = user_settings()
    assert text.panel_line("{attack}: ready", settings, ARROWS) == "X: ready"
    assert text.panel_line("{attack}: ready", settings, SOLO) == "J: ready"
    assert text.panel_line("{attack}: ready", settings, PAD0) == "A: ready"
    assert text.panel_line(text.CPU_EDIT_LINE, settings, ARROWS) == "X: done  C: remove"


def test_the_join_list_names_every_free_device_and_its_own_join_key() -> None:
    settings = user_settings()
    lines = text.join_lines(settings, [SOLO, PAD0], cpu_device=ARROWS)
    assert lines == ["PRESS TO JOIN", "J  WASD KEYS", "A  PAD 1", "", "V: ADD A CPU"]
    assert text.join_lines(settings, [SOLO], cpu_device="") == ["PRESS TO JOIN", "J  WASD KEYS"]
    assert text.join_lines(settings, [], cpu_device=ARROWS) == ["V: ADD A CPU"]
    assert text.join_lines(settings, [], cpu_device="") == []
    assert len(text.join_lines(settings, [SOLO, "pad:0", "pad:1", "pad:2"], ARROWS)) <= (
        text.PROMPT_LINES
    )


@pytest.mark.parametrize("case", every_setup(), ids=lambda case: case[0])
def test_no_panel_line_is_wider_than_its_panel(case: tuple[str, Settings, str]) -> None:
    _, settings, device = case
    others = [each for each in (SOLO, ARROWS, PAD0, "pad:1") if each != device]
    lines = text.join_lines(settings, [device, *others], cpu_device=device)
    for template in text.PANEL_LINES:
        lines.append(text.panel_line(template, settings, device))
    for line in lines:
        assert width(line) <= text.PANEL_TEXT_WIDTH, line


# --- the footer -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", every_setup(), ids=lambda case: case[0])
@pytest.mark.parametrize("state", sorted(text.FOOTERS))
def test_the_footer_always_fits_the_screen(case: tuple[str, Settings, str], state: str) -> None:
    _, settings, device = case
    for training in (False, True):
        line = text.footer_line(state, settings, device, training)
        assert line and width(line) <= text.FOOTER_WIDTH <= NATIVE_W, line


def test_the_footer_shows_the_devices_own_keys_and_drops_the_least_important_first() -> None:
    settings = user_settings()
    line = text.footer_line("roster", settings, ARROWS)
    assert "X: ready" in line and "V: add CPU" in line and "arrows: pick" in line
    assert "J:" not in line and "MOTION" not in line
    assert "A: ready" in text.footer_line("roster", settings, PAD0)
    tight = text.footer_line("roster", long_settings(), SOLO)
    assert "costume" not in tight and "ready" in tight and "back" in tight
    assert "add CPU" not in text.footer_line("roster", settings, ARROWS, training=True)
    assert "done" in text.footer_line("cpu", settings, ARROWS)
    assert "controls" in text.footer_line("controls", settings, ARROWS)


def test_fit_hint_drops_named_items_in_order_then_shortens() -> None:
    labels = device_labels(Settings(), SOLO)
    template = "{attack}: go   {stick}: move   {strong}: costume   {special}: back"
    full = hint_text(template, labels)
    assert fit_hint(template, labels, 1000) == full
    assert fit_hint(template, labels, width(full) - 1, drop=("strong", "stick")) == (
        "J: go   WASD: move   K: back"
    )
    assert fit_hint(template, labels, 150, drop=("strong", "stick")) == "J: go   K: back"
    squeezed = fit_hint(template, labels, 60, drop=("strong", "stick"))
    assert width(squeezed) <= 60 and squeezed.startswith("J: go")


# --- messages -------------------------------------------------------------------------------


@pytest.mark.parametrize("case", every_setup(), ids=lambda case: case[0])
def test_every_message_is_one_line_in_the_players_own_keys(
    case: tuple[str, Settings, str],
) -> None:
    _, settings, device = case
    versus = MatchSetup()
    teams = MatchSetup(team_play=True, teams=(0, 0, 0, 0))
    training = MatchSetup(training=True)
    messages = [
        text.start_problem(can_start(versus, 1), settings, device),
        text.start_problem(can_start(teams, 3), settings, device),
        text.start_problem(can_start(training, 0), settings, device),
        text.join_first(settings, device),
        text.joined(3, device),
        text.switched(3, device),
        text.shared_message(long_settings(), SOLO, ARROWS),
        text.shared_message(user_settings(), SOLO, ARROWS),
    ]
    for message in messages:
        assert message and width(message) <= text.FOOTER_WIDTH, message
        assert "{" not in message and "GRAB" not in message and "ATTACK" not in message


def test_messages_say_what_happened() -> None:
    settings = user_settings()
    need = text.start_problem(can_start(MatchSetup(), 1), settings, ARROWS)
    assert "two players" in need.lower() and need.endswith("V")
    assert text.join_first(settings, SOLO) == "PRESS J TO JOIN FIRST"
    assert text.join_first(settings, PAD0) == "PRESS A TO JOIN FIRST"
    assert text.joined(1, SOLO) == "P2 JOINED ON WASD KEYS"
    assert text.switched(0, SOLO) == "P1 NOW USES WASD KEYS"
    assert text.start_problem("", settings, ARROWS) == ""


# --- shared keys ----------------------------------------------------------------------------


def test_the_users_layouts_share_four_keys() -> None:
    settings = user_settings()
    assert shared_keys(settings, "solo", "arrows") == ("S", "SPACE", "LSHIFT", "LCTRL")
    assert shared_keys(settings, "arrows", "solo") == ("LCTRL", "S", "LSHIFT", "SPACE")
    assert shared_keys(Settings(), "solo", "arrows") == ()
    assert shared_keys(settings, "solo", "nowhere") == ()
    second = settings.with_key("arrows", "taunt", "MOTION_UP", slot=1)
    solo_up = replace(second, keys={**second.keys, "solo": {**second.keys["solo"], "up": "UP"}})
    assert "UP" in shared_keys(solo_up, "solo", "arrows"), "aliases and second keys count"
    message = text.shared_message(settings, SOLO, ARROWS)
    assert message == "WASD KEYS AND ARROW KEYS SHARE S, SPACE, LSHIFT, LCTRL"
    assert text.shared_message(Settings(), SOLO, ARROWS) == ""
    assert text.shared_message(settings, SOLO, PAD0) == ""


@pytest.mark.parametrize("case", every_setup(), ids=lambda case: case[0])
def test_the_footer_names_the_device_when_several_people_are_in(
    case: tuple[str, Settings, str],
) -> None:
    _, settings, device = case
    for state in text.FOOTERS:
        line = text.footer_line(state, settings, device, named=True)
        assert line.startswith(text.device_name(device) + "   "), line
        assert width(line) <= text.FOOTER_WIDTH, line
    assert not text.footer_line("roster", settings, device).startswith(text.device_name(device))
