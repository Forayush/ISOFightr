"""The victory screen's model: standings, rows, awards and the animation timeline (plan note
13, decision D-061 item 10, M13 group 8). Pure: no window. The screen itself is driven in
``tests/test_flow_gl.py``.
"""

import itertools

import pytest

from helpers import make_match
from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.scenes import results_model as model
from isofightr.scenes.setup import result_awards
from isofightr.sim.match import Match, MatchRules
from isofightr.sim.rules import MatchResult
from isofightr.ui import results_art, theme


def finished(
    placements: tuple[tuple[int, ...], ...], teams: tuple[int, ...] | None = None
) -> Match:
    """A match with a result written straight in (the model only reads it)."""
    count = sum(len(group) for group in placements)
    match = make_match(fighters=("rook",) * count)
    if teams is not None:
        match.rules = MatchRules(stocks=3, teams=teams)
        for fighter, team in zip(match.fighters, teams, strict=True):
            fighter.team = team
    match.result = MatchResult(placements[0][0], placements, placements[0])
    return match


# --- who stands where ---------------------------------------------------------------------


def test_the_banner_names_the_winner_or_the_team() -> None:
    assert model.banner_text(make_match()) == "NO CONTEST"
    assert model.banner_text(finished(((1,), (0,)))) == "PLAYER 2 WINS!"
    team = finished(((0, 2), (1,)), teams=(1, 0, 1))
    assert model.banner_text(team) == "BLUE TEAM WINS!"


def test_the_line_under_the_banner_says_how_it_was_decided() -> None:
    match = finished(((0,), (1,)))
    assert model.sub_text(match) == ""
    match.sudden_death = True
    assert model.sub_text(match) == "DECIDED IN SUDDEN DEATH"
    assert model.sub_text(make_match()) == ""


def test_the_podium_is_second_first_third_fourth_and_centred() -> None:
    standings = model.standings(finished(((2,), (0,), (3,), (1,))))
    assert [standing.player for standing in standings] == [0, 2, 3, 1], "2nd, 1st, 3rd, 4th"
    assert [standing.place for standing in standings] == [1, 0, 2, 3]
    xs = [standing.x for standing in standings]
    assert xs == sorted(xs) and xs[1] - xs[0] == model.STEP_WIDTH
    assert (xs[0] + xs[-1]) // 2 == model.PODIUM_CENTRE
    heights = {standing.place: standing.height for standing in standings}
    assert heights[0] > heights[1] > heights[2] > heights[3] > 0
    assert [standing.winner for standing in standings] == [False, True, False, False]


def test_players_level_with_each_other_share_a_step_height_and_a_place() -> None:
    tied = model.standings(finished(((0,), (1, 2), (3,))))
    seconds = [standing for standing in tied if standing.place == 1]
    assert len(seconds) == 2 and len({standing.height for standing in seconds}) == 1
    assert [row.place for row in model.stat_rows(finished(((0,), (1, 2), (3,))))] == [
        "1ST",
        "2ND",
        "2ND",
        "3RD",
    ]


def test_a_winning_team_shares_the_top_step_with_room_for_each() -> None:
    standings = model.standings(finished(((0, 2), (1, 3)), teams=(0, 1, 0, 1)))
    winners = [standing for standing in standings if standing.winner]
    assert sorted(standing.player for standing in winners) == [0, 2]
    assert abs(winners[0].x - winners[1].x) == model.TEAM_STEP_WIDTH
    assert all(0 < standing.x < NATIVE_W for standing in standings)


def test_without_a_result_nobody_is_the_winner() -> None:
    standings = model.standings(make_match())
    assert not any(standing.winner for standing in standings)
    assert {standing.place for standing in standings} == {0}


# --- rows and awards ----------------------------------------------------------------------


def test_stat_rows_scale_their_bars_to_the_best() -> None:
    match = finished(((1,), (0,)))
    match.stats[0].damage_given, match.stats[0].damage_taken = 40.0, 120.0
    match.stats[1].damage_given, match.stats[1].damage_taken = 120.0, 40.0
    match.stats[1].kos, match.stats[0].falls, match.stats[1].longest_combo = 3, 3, 4
    first, second = model.stat_rows(match)
    assert (first.player, first.place, first.name) == (1, "1ST", "P2 ROOK")
    assert first.dealt_share == 1.0 and second.dealt_share == pytest.approx(1 / 3)
    assert second.taken_share == 1.0 and (first.kos, second.falls, first.combo) == (3, 3, 4)
    assert all(row.dealt_share == 0.0 for row in model.stat_rows(finished(((0,), (1,)))))


def test_awards_are_the_same_as_the_text_lines() -> None:
    match = finished(((0,), (1,)))
    assert model.awards(match) == []
    match.stats[0].damage_given, match.stats[0].longest_combo = 88.0, 3
    match.stats[1].peak_damage = 140.0
    awards = model.awards(match)
    assert [award.icon for award in awards] == ["burst", "swords", "shield"]
    assert [award.player for award in awards] == [0, 0, 1]
    assert [award.line for award in awards] == result_awards(match)
    assert awards[0].value == "88%" and awards[1].value == "3 hits"


def test_match_length_leaves_out_the_countdown() -> None:
    match = make_match()
    match.frame = 60 * 95
    assert model.match_length(match) == "1:35"


# --- the timeline -------------------------------------------------------------------------


def test_what_is_visible_at_each_tick() -> None:
    assert model.visible(0, 4, 3) == {"banner", "buttons", "confetti"}
    assert "step0" in model.visible(model.WINNER_START, 4, 3)
    assert "step1" not in model.visible(model.WINNER_START, 4, 3)
    mid = model.visible(model.ROWS_START + model.ROW_GAP, 4, 3)
    assert {"step0", "step1", "step2", "step3", "row0", "row1"} <= mid and "row2" not in mid
    assert "award0" not in mid
    late = model.visible(model.AWARDS_START + 2 * model.AWARD_GAP, 4, 3)
    assert {"row3", "award0", "award1", "award2"} <= late
    assert not model.settled(model.AWARDS_START, 4, 3)
    assert model.settled(400, 4, 3)


def test_the_banner_drops_bounces_and_then_waves() -> None:
    assert model.banner_offset(0) == model.BANNER_DROP
    assert model.banner_offset(model.BANNER_TICKS) == 0 == model.banner_offset(999)
    drops = [model.banner_offset(tick) for tick in range(model.BANNER_TICKS)]
    assert any(later > earlier for earlier, later in itertools.pairwise(drops)), (
        "it bounces back up before it settles"
    )
    assert all(model.letter_offset(10, index) == 0 for index in range(12)), "not while dropping"
    waves = {model.letter_offset(model.BANNER_TICKS + 30, index) for index in range(14)}
    assert len(waves) > 1 and max(abs(wave) for wave in waves) <= model.WAVE_AMPLITUDE


def test_steps_rows_and_awards_arrive_in_turn() -> None:
    assert model.step_offset(model.step_start(0), 0) == -model.RISE_PIXELS
    assert model.step_offset(model.step_start(0) + model.RISE_TICKS, 0) == 0
    assert model.step_start(2) > model.step_start(1) > model.step_start(0)
    assert model.row_offset(model.row_start(1), 1) == model.ROW_SLIDE
    assert model.row_offset(model.row_start(1) + model.ROW_SLIDE_TICKS, 1) == 0
    assert model.row_fill(model.row_start(0) + model.ROW_SLIDE_TICKS, 0) == 0.0
    done = model.row_start(0) + model.ROW_SLIDE_TICKS + model.BAR_TICKS
    assert model.row_fill(done, 0) == 1.0
    counts = [model.counted(tick, 0, 87.6) for tick in range(model.row_start(0), done + 1)]
    assert counts[0] == 0 and counts[-1] == 87 and counts == sorted(counts)
    assert model.award_pop(model.award_start(2) + model.AWARD_TICKS, 2) == 0


def test_confetti_is_the_same_every_time_and_keeps_falling() -> None:
    first = model.confetti(100)
    assert first == model.confetti(100) and len(first) == model.CONFETTI_PIECES
    assert all(0 <= x < NATIVE_W and -10 <= y <= NATIVE_H + 10 for x, y, _, _ in first)
    assert {colour for _, _, colour, _ in first} == set(range(model.CONFETTI_COLOURS))
    later = model.confetti(130)
    assert first != later
    lower = sum(1 for (_, y0, _, _), (_, y1, _, _) in zip(first, later, strict=True) if y1 < y0)
    assert lower > model.CONFETTI_PIECES * 0.8, "nearly all of it has fallen (some wrapped)"


# --- art ----------------------------------------------------------------------------------

RESULTS_ART = {
    "step": lambda: results_art.podium_step(64, 52, theme.player_ramp(0)),
    "step_low": lambda: results_art.podium_step(64, 10, theme.player_ramp(3)),
    "spotlight": lambda: results_art.spotlight(150, 236),
    "confetti": lambda: results_art.confetti_piece(theme.GOLD, True),
    "place": lambda: results_art.place_plate(24, 11, theme.player_ramp(1)),
    "letter": lambda: results_art.banner_letters("W", theme.player_ramp(2))[0][0],
}


@pytest.mark.parametrize("name", sorted(RESULTS_ART))
def test_results_art_uses_only_palette_colours(name: str) -> None:
    from test_ui_kit import colours, resurrect64

    image = RESULTS_ART[name]()
    assert colours(image) and colours(image) <= resurrect64()


def test_the_banner_fits_the_screen_in_letters() -> None:
    for text in ("PLAYER 4 WINS!", "YELLOW TEAM WINS!", "NO CONTEST"):
        letters = results_art.banner_letters(text, theme.player_ramp(0))
        assert len(letters) == len(text)
        assert results_art.banner_width(letters) <= NATIVE_W - 16, text
        assert [picture is None for picture, _ in letters] == [char == " " for char in text]


def test_a_podium_step_has_a_diamond_top_over_its_sides() -> None:
    image = results_art.podium_step(64, 20, theme.player_ramp(0))
    assert image.size == (64, 52)
    alpha = image.getchannel("A")
    assert alpha.getpixel((32, 16)) == 255 and alpha.getpixel((0, 0)) == 0
    assert alpha.getpixel((31, 50)) == 255, "the front corner reaches the foot"
    assert alpha.getpixel((0, 51)) == 0
