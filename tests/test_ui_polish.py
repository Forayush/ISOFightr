"""The UI polish pass (decision D-070): the pure parts.

Buttons that overwrite things rest quietly and the rules screen gives stage hazards its own
icon. (The dusk backdrop and its drifting tiles went with decision D-072: the menus are
drawn on the Isle, whose tests are ``test_menu_world*.py``.)
"""

from PIL import Image

from isofightr.scenes import rules_model
from isofightr.ui import kit_art, theme
from isofightr.ui.kit_art import Look


def _colours(image: Image.Image) -> set[tuple[int, int, int]]:
    return {pixel[:3] for pixel in image.convert("RGBA").getdata() if pixel[3]}


def test_a_button_that_overwrites_rests_dark_with_a_red_rim() -> None:
    resting = kit_art.button(80, 22, Look.CAUTION)
    assert _colours(resting) == {theme.INK, theme.CRIMSON}
    assert resting.getpixel((40, 11))[:3] == theme.INK, "the body is dark, not red"
    assert kit_art.text_color(Look.CAUTION) == theme.SALMON
    lit = kit_art.button(80, 22, Look.DANGER)
    assert lit.getpixel((40, 11))[:3] == theme.CRIMSON, "red only under the cursor"


def test_the_caution_colours_are_theme_palette_entries() -> None:
    for colour in (theme.CAUTION_FILL[:3], theme.CAUTION_BORDER[:3], theme.CAUTION_TEXT):
        assert colour in theme.PALETTE


def test_stage_hazards_has_its_own_icon_on_the_rules_screen() -> None:
    icons = {row.key: row.icon for row in rules_model.RULE_ROWS}
    assert icons["stage_hazards"] == "bolt"
    assert icons["stage_hazards"] != icons["launch_rate"]


def test_a_fighters_panel_keeps_its_last_line_off_the_panels_edge() -> None:
    import ast
    from pathlib import Path

    # select_view imports arcade, so read its layout constants from the source.
    source = Path(__file__).parent.parent / "src" / "isofightr" / "scenes" / "select_view.py"
    values = {
        node.targets[0].id: node.value.value
        for node in ast.parse(source.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert values["LINE2_BOTTOM"] >= 3, "the last line does not sit on the panel's edge"
    assert values["LINE1_BOTTOM"] - values["LINE2_BOTTOM"] >= 11, "two lines do not touch"
    assert values["SWATCH_BOTTOM"] + values["SWATCH"] < values["PLATE_BOTTOM"]


# --- group 2: the proposals (rules groups, footer, HUD cards) ----------------------------


def test_every_rule_is_in_one_titled_group_in_order() -> None:
    keys = [key for _, group in rules_model.RULE_GROUPS for key in group]
    assert tuple(keys) == rules_model.ROW_KEYS
    assert [title for title, _ in rules_model.RULE_GROUPS] == ["MATCH", "MECHANICS", "DISPLAY"]


def test_the_roster_footer_leaves_ready_and_costume_to_the_panels() -> None:
    from isofightr.scenes import select_text

    template, _ = select_text.FOOTERS["roster"]
    assert "ready" not in template and "costume" not in template
    assert "{stick}" in template and "{grab}" in template and "{special}" in template


def test_a_stock_pip_is_a_small_tile_in_the_players_ramp() -> None:
    from isofightr.ui import hud_art

    for index in range(4):
        ramp = theme.player_ramp(index)
        pip, socket = hud_art.stock_pip(ramp), hud_art.stock_pip(ramp, lost=True)
        assert pip.size == socket.size == hud_art.STOCK_PIP
        assert _colours(pip) == {ramp[0], ramp[1], ramp[2]}, "lit top, two sides"
        assert _colours(socket) == {ramp[3]}, "a lost stock is the deepest shade only"
        assert pip.getchannel("A").tobytes() == socket.getchannel("A").tobytes(), "same shape"


def test_a_bust_is_cut_to_its_wells_angled_corners() -> None:
    from isofightr.ui import hud_art

    bust = Image.new("RGBA", (32, 32), (*theme.GREEN, 255))
    cut = hud_art.clip_bust(bust, 32)
    assert cut.size == (32, 32)
    assert cut.getpixel((1, 1))[3] == 0 and cut.getpixel((30, 30))[3] == 0, "angled corners"
    assert cut.getpixel((30, 1))[3] == 255 and cut.getpixel((1, 30))[3] == 255, "square ones"
    assert cut.getpixel((0, 16))[3] == 0, "inside the well's ring"
    small = hud_art.clip_bust(Image.new("RGBA", (12, 12), (*theme.GREEN, 255)), 32)
    assert small.getpixel((16, 16))[3] == 255 and small.getpixel((5, 16))[3] == 0, "centred"
    well = hud_art.bust_well(32, theme.player_ramp(0))
    assert well.getpixel((0, 0))[3] == 0 and well.getpixel((0, 16))[:3] == theme.player_ramp(0)[0]


def test_the_damage_number_and_its_sign_are_split() -> None:
    from isofightr.ui import hud_layout

    assert hud_layout.damage_parts("37%") == ("37", "%")
    assert hud_layout.damage_parts("142%") == ("142", "%")
    assert hud_layout.damage_parts(hud_layout.KO_TEXT) == (hud_layout.KO_TEXT, "")
