"""The battle HUD's layout, timings and remembered state (plan note 13, decision D-061 item 9,
M13 group 7). Pure: no window. The HUD on screen is driven in ``tests/test_battle_gl.py``
and ``tests/test_flow_gl.py``.
"""

import itertools

import pytest

from helpers import make_match
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.sim.events import HitEvent, KoEvent
from isofightr.sim.math3d import Vec3
from isofightr.sim.move_def import Effect
from isofightr.ui import hud_art, hud_layout, theme
from isofightr.ui.focus import Rect
from isofightr.ui.hud_layout import (
    CARD_HEIGHT,
    CLOCK,
    HUD_BAND,
    PLAY_AREA,
    TOP_BAND,
    bubble_layout,
    card_rects,
    feed_rect,
    leader,
    pause_row_parts,
    play_area_overlaps,
    popup_alpha,
    popup_color,
    popup_offset,
    popup_text,
    roll,
    shake_amplitude,
)
from isofightr.ui.hud_state import KO_BANNER_TICKS, SHATTER_TICKS, HudState
from isofightr.ui.menu import MenuItem

# --- layout -----------------------------------------------------------------------------------


@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_nothing_fixed_covers_the_play_area(players: int) -> None:
    cards = card_rects(players)
    assert play_area_overlaps([*cards, CLOCK, feed_rect()]) == []
    for card in cards:
        assert card.left >= 0 and card.right <= NATIVE_W and card.top <= HUD_BAND
    for first, second in itertools.combinations(cards, 2):
        assert not first.overlaps(second)
    assert CLOCK.bottom >= NATIVE_H - TOP_BAND and feed_rect().bottom >= NATIVE_H - TOP_BAND
    assert not CLOCK.overlaps(feed_rect())
    assert PLAY_AREA.bottom == HUD_BAND and PLAY_AREA.top == NATIVE_H - TOP_BAND


def test_cards_hold_their_parts() -> None:
    assert hud_layout.BUST.top <= CARD_HEIGHT
    five_stocks = hud_layout.STOCK_LEFT + 4 * hud_layout.CARD_STOCK_STEP + 12
    from isofightr.ui import font
    from isofightr.ui.font import TextSize

    widest = font.text_width("999%", TextSize.NUMERAL)
    assert five_stocks <= hud_layout.CARD_WIDTH - hud_layout.DAMAGE_RIGHT - widest + 4, (
        "five stocks and a three-digit percent fit side by side (at most touching)"
    )


def test_the_number_rolls_up_and_snaps_down() -> None:
    assert roll(0, 20) == 5 and roll(5, 20) == 9
    assert roll(19, 20) == 20 and roll(20, 20) == 20
    assert roll(80, 0) == 0, "a respawn drops at once"
    shown, steps = 0.0, 0
    while shown < 76.8:
        shown, steps = roll(shown, 76.8), steps + 1
    assert shown == 76.8 and steps <= 20


def test_high_percent_trembles_unless_shake_is_off() -> None:
    assert shake_amplitude(99) == 0 and shake_amplitude(100) == 1
    assert shake_amplitude(160) == 2 and shake_amplitude(400) == 2
    assert shake_amplitude(160, 0.5) == 1 and shake_amplitude(160, 0.0) == 0


def test_popups_rise_fade_and_take_the_hits_colour() -> None:
    assert popup_text(12.4) == "+12%" and popup_text(0.2) == "+1%"
    colours = [popup_color(damage) for damage in (2, 7, 13, 20)]
    assert len(set(colours)) == 4 and all(colour in theme_colours() for colour in colours)
    rises = [popup_offset(age) for age in range(hud_layout.POPUP_TICKS + 1)]
    assert rises == sorted(rises) and rises[-1] == hud_layout.POPUP_RISE
    assert popup_alpha(0) == 255 and popup_alpha(hud_layout.POPUP_TICKS) == 0


def theme_colours() -> set[tuple[int, int, int]]:
    return set(theme.PALETTE)


def test_the_clock_alarms_in_the_last_thirty_seconds() -> None:
    assert not hud_layout.clock_alarm(None) and not hud_layout.clock_alarm(31 * 60)
    assert hud_layout.clock_alarm(30 * 60) and hud_layout.clock_alarm(0)


def test_the_leader_is_alone_at_the_top() -> None:
    assert leader([0, 0, 0]) is None, "nobody has scored"
    assert leader([2, 1, 0]) == 0 and leader([-1, 0, -2]) == 1
    assert leader([2, 2, 0]) is None, "a shared lead wears no crown"
    assert leader([]) is None


def test_bubbles_sit_inside_the_play_area_and_point_out() -> None:
    assert bubble_layout(300, 200) is None
    x, y, direction = bubble_layout(-50, 200) or (0, 0, 0)
    assert PLAY_AREA.contains(x, y) and direction == 4, "left"
    _, _, up = bubble_layout(300, NATIVE_H + 30) or (0, 0, 0)
    assert up == 2
    _, _, corner = bubble_layout(NATIVE_W + 40, -40) or (0, 0, 0)
    assert corner == 7, "down and to the right"
    assert bubble_layout(300, 10) is not None, "behind the cards counts as out of view"


def test_pause_rows_split_into_name_and_value() -> None:
    assert pause_row_parts(MenuItem("resume", "Resume")) == ("Resume", "")
    assert pause_row_parts(MenuItem("help", "Controls help", ("Off", "On"), 1)) == (
        "Controls help",
        "On",
    )
    assert pause_row_parts(MenuItem("damage", "Dummy damage: < 40% >")) == ("Dummy damage", "40%")


# --- state ------------------------------------------------------------------------------------


def hit(target: int, damage: float) -> HitEvent:
    return HitEvent(0, target, "jab", damage, 30.0, Vec3(1, 2, 0), Effect.NORMAL, 5)


def test_a_hit_flashes_the_card_and_rises_as_a_popup() -> None:
    match = make_match(fighters=("rook", "rook"))
    state = HudState(names=["P1 ROOK", "P2 ROOK"])
    state.step(match.fighters, [hit(1, 7.0)], over=False)
    assert state.flash == {1: hud_layout.HIT_FLASH_TICKS}
    assert [(popup.damage, popup.age) for popup in state.popups] == [(7.0, 0)]
    for _ in range(hud_layout.POPUP_TICKS):
        state.step(match.fighters, [], over=False)
    assert state.popups == [] and state.flash == {}


def test_a_ko_writes_the_feed_and_shows_the_sash() -> None:
    match = make_match(fighters=("rook", "rook", "rook"))
    state = HudState(names=["P1 ROOK", "P2 ROOK", "P3 ROOK"])
    state.step(match.fighters, [KoEvent(1, Vec3(0, 0, -9), Vec3(0, 0, -1), 2, 0)], over=False)
    assert [line.text for line in state.feed] == ["P1 ROOK KO P2 ROOK"]
    assert state.ko_banner == (1, 0)
    state.step(match.fighters, [KoEvent(2, Vec3(0, 0, -9), Vec3(0, 0, -1), 2, None)], over=True)
    assert state.feed[-1].text == "P3 ROOK FELL"
    assert state.ko_banner == (1, 1), "no new sash when the match has just ended"
    for _ in range(KO_BANNER_TICKS):
        state.step(match.fighters, [], over=False)
    assert state.ko_banner is None
    for victim in range(4):
        state.step(match.fighters, [KoEvent(victim % 3, Vec3(0, 0, 0), Vec3(0, 0, 1), 1)], False)
    assert len(state.feed) == hud_layout.FEED_LINES
    for _ in range(hud_layout.FEED_TICKS):
        state.step(match.fighters, [], over=False)
    assert state.feed == []


def test_a_lost_stock_breaks_its_icon() -> None:
    match = make_match(fighters=("rook", "rook"))
    fighter = match.fighters[0]
    fighter.stocks = 3
    state = HudState()
    state.step(match.fighters, [], over=False)
    fighter.stocks = 2
    state.step(match.fighters, [], over=False)
    assert [(shatter.player, shatter.slot) for shatter in state.shatters] == [(0, 2)]
    for _ in range(SHATTER_TICKS):
        state.step(match.fighters, [], over=False)
    assert state.shatters == []


def test_the_numbers_roll_once_a_drawn_frame() -> None:
    match = make_match(fighters=("rook", "rook"))
    state = HudState()
    state.roll(match.fighters)
    assert state.shown_damage(1) == 0
    match.set_damage(1, 40.0)
    state.roll(match.fighters)
    assert 0 < state.shown_damage(1) < 40
    for _ in range(30):
        state.roll(match.fighters)
    assert state.shown_damage(1) == 40


def test_a_new_banner_starts_its_pop() -> None:
    state = HudState()
    state.show_banner("3")
    state.tick += 5
    assert state.banner_age() == 5
    state.show_banner("3")
    assert state.banner_age() == 5
    state.show_banner("2")
    assert state.banner_age() == 0


# --- art --------------------------------------------------------------------------------------

HUD_ART = {
    "card": lambda: hud_art.card(148, 40, theme.player_ramp(0)),
    "card_lit": lambda: hud_art.card(148, 40, theme.player_ramp(3), lit=True),
    "well": lambda: hud_art.bust_well(32, theme.player_ramp(1)),
    "badge": lambda: hud_art.badge(24, 9, theme.SKY),
    "clock": lambda: hud_art.clock_plate(76, 20),
    "clock_alarm": lambda: hud_art.clock_plate(76, 20, alarm=True, glow=True),
    "feed": lambda: hud_art.feed_row(160, 12, theme.GOLD),
    "sash": lambda: hud_art.sash(300, 26, theme.player_ramp(2)),
    "combo": lambda: hud_art.combo_plate(60, 18),
    "bubble": lambda: hud_art.bubble(26, theme.player_ramp(3)),
    "arrow": lambda: hud_art.bubble_arrow(3, theme.player_ramp(0)),
    "banner_gold": lambda: hud_art.banner("3"),
    "banner_red": lambda: hud_art.banner("SUDDEN DEATH", "red"),
    "banner_mint": lambda: hud_art.banner("GO!", "mint"),
}


@pytest.mark.parametrize("name", sorted(HUD_ART))
def test_hud_art_uses_only_palette_colours(name: str) -> None:
    from test_ui_kit import colours, resurrect64

    image = HUD_ART[name]()
    assert colours(image) and colours(image) <= resurrect64()


def test_banners_fit_the_screen_and_arrows_point_eight_ways() -> None:
    for text in ("3", "GO!", "GAME!", "SUDDEN DEATH", "REPLAY END"):
        assert hud_art.banner(text).width <= NATIVE_W - 40, text
    arrows = {
        hud_art.bubble_arrow(direction, theme.player_ramp(0)).tobytes() for direction in range(8)
    }
    assert len(arrows) == 8


def test_a_stock_icon_breaks_in_four() -> None:
    from PIL import Image

    icon = Image.new("RGBA", (12, 12), (255, 0, 0, 255))
    pieces = hud_art.shards(icon)
    assert [offset for _, offset in pieces] == [(0, 0), (6, 0), (0, 6), (6, 6)]
    assert all(piece.size == (6, 6) for piece, _ in pieces)


def test_rect_helper_used_by_the_layout_test() -> None:
    assert not Rect(0, 0, 10, 10).overlaps(Rect(0, 10, 10, 10)), "touching is not covering"
