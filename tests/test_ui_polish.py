"""The UI polish pass (decision D-070): the pure parts.

Buttons that overwrite things rest quietly, the menu backdrop's drifting tiles are painted in
the backdrop's own colours, and the rules screen gives stage hazards its own icon.
"""

from PIL import Image

from isofightr.scenes import rules_model
from isofightr.ui import backdrop, kit_art, theme
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


def test_drifting_tiles_wear_the_backdrops_island_colours() -> None:
    wanted = {theme.rgb(backdrop.DUSK.island_top), theme.DEEP_TEAL, theme.NIGHT}
    for half in backdrop.TILE_HALF_WIDTHS:
        assert _colours(backdrop.build_drift_tile(half)) == wanted
    assert backdrop.TILE_ALPHA >= 128, "solid enough not to turn grey over the plum sky"


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
