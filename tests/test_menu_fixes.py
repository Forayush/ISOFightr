"""Menu fixes from the user's play (decision D-078): fixed next-tab buttons, character
select's hints for CPUs and back, and the rules chip's text. The pure parts."""

from isofightr.input.gamepad import PadState
from isofightr.scenes import controls_model, rules_model, select_text
from isofightr.scenes.options_view import TAB_STEPS
from isofightr.scenes.setup import MatchSetup
from isofightr.settings import RESERVED_KEYS, TAB_KEY, Settings
from isofightr.ui import font
from isofightr.ui.font import TextSize
from isofightr.ui.hints import TAB_LABELS, device_labels
from isofightr.ui.menu import MenuAction, pad_actions


def test_only_fixed_buttons_change_tab() -> None:
    """Strong and the modifiers are keys a player binds (and tests on the Controls page):
    with the user's arrows layout S was strong, so it changed tab on one page and swung a
    sword on the next."""
    assert set(TAB_STEPS) == {MenuAction.NEXT_TAB}
    assert pad_actions(PadState(select=True)) == {MenuAction.NEXT_TAB}
    assert MenuAction.NEXT_TAB not in pad_actions(PadState(left_shoulder=True, a=True))


def test_tab_is_a_fixed_key_like_enter_and_escape() -> None:
    assert TAB_KEY in RESERVED_KEYS
    assert not controls_model.can_bind("keyboard:solo", "TAB")
    assert Settings().with_key("solo", "attack", "TAB") == Settings()


def test_every_device_names_its_tab_button() -> None:
    settings = Settings()
    assert device_labels(settings, "keyboard:arrows")["tabs"] == TAB_LABELS["keyboard"]
    assert device_labels(settings, "pad:0")["tabs"] == TAB_LABELS["pad"]


def test_a_cpus_plate_says_how_to_change_it_in_its_owners_keys() -> None:
    line = select_text.panel_line(select_text.CPU_IDLE_LINE, Settings(), "keyboard:solo")
    assert line == "L: change it"


def test_a_device_that_is_not_in_is_not_offered_a_back_that_does_nothing() -> None:
    template, _ = select_text.FOOTERS["outside"]
    assert "{special}" not in template and "{attack}" in template
    message = select_text.outside_back(Settings(), [(0, "keyboard:arrows")])
    assert "P1" in message and "NUM_5" in message


def test_the_rules_chip_fits_in_mixed_case_whatever_the_rules() -> None:
    setup = MatchSetup(time_on=True, stock_on=True, stocks=99, minutes=99, start_damage=300)
    line = rules_model.chip_line(setup)
    assert line == line[0].upper() + line[1:] and "TEAMS" not in line
    assert "Teams off" in line and "Time 99:00" in line
    room = 356 - 2 * (8 + 12 + 4)
    assert font.text_width(line, TextSize.TEXT) <= room
