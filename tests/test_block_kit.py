"""The block kit (decision D-072, M21 group 1): surfaces, block painters, the sentence face,
prompts and the cloud wipe. All pure: no window. The drawing side is in ``test_ui_gl.py``.
"""

import tomllib

import pytest
from PIL import Image

from isofightr.config import NATIVE_H, NATIVE_W
from isofightr.data.paths import REPO_ROOT
from isofightr.settings import KEYBOARD_ARROWS, KEYBOARD_SOLO, Settings
from isofightr.ui import font, hints, kit_art, logo, theme, wipe
from isofightr.ui.font import PRINTABLE, TextSize
from isofightr.ui.kit_art import Look

PALETTE_FILE = REPO_ROOT / "art_src" / "palettes" / "resurrect64.toml"
MIN_CONTRAST = 4.5
"""What D-072 asks of every text role on its surface (the WCAG line for body text)."""


def resurrect64() -> set[tuple[int, int, int]]:
    with PALETTE_FILE.open("rb") as file:
        return {theme.rgb(value) for value in tomllib.load(file)["colors"]}


def colours(image: Image.Image) -> set[tuple[int, int, int]]:
    """Every colour of an image's visible pixels."""
    return {pixel[:3] for pixel in image.convert("RGBA").getdata() if pixel[3] > 0}


def luminance(colour: tuple[int, ...]) -> float:
    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.04045 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in colour[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: tuple[int, ...], second: tuple[int, ...]) -> float:
    """The WCAG contrast ratio of two colours."""
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# --- surfaces --------------------------------------------------------------------------------


@pytest.mark.parametrize("surface", theme.SURFACES, ids=lambda surface: surface.name)
def test_every_surface_colour_is_in_the_palette(surface: theme.Surface) -> None:
    palette = resurrect64()
    for name in surface.__slots__:
        value = getattr(surface, name)
        if isinstance(value, tuple):
            assert value[:3] in palette, name


@pytest.mark.parametrize("surface", theme.SURFACES, ids=lambda surface: surface.name)
def test_text_reads_on_its_surface(surface: theme.Surface) -> None:
    for role in ("text", "text_muted", "accent", "warning"):
        assert contrast(getattr(surface, role), surface.face) >= MIN_CONTRAST, role
    assert contrast(surface.text, surface.button) >= MIN_CONTRAST
    assert contrast(surface.text, surface.well) >= MIN_CONTRAST
    assert contrast(surface.text_muted, surface.well) >= MIN_CONTRAST
    # The one faint role: text that is switched off. It must still be the faintest.
    assert contrast(surface.text_dim, surface.face) < contrast(surface.text_muted, surface.face)


@pytest.mark.parametrize("surface", theme.SURFACES, ids=lambda surface: surface.name)
@pytest.mark.parametrize("look", [look for look in Look if look is not Look.DISABLED])
def test_a_caption_reads_on_its_block_in_every_look(surface: theme.Surface, look: Look) -> None:
    face = kit_art.look_colours(look, surface)[0]
    assert contrast(kit_art.look_text(look, surface), face) >= MIN_CONTRAST
    assert contrast(kit_art.toggle_text(True, surface), theme.MINT) >= MIN_CONTRAST


def test_the_stone_surface_is_light_and_the_ink_surface_dark() -> None:
    assert luminance(theme.STONE.face) > 0.5 > luminance(theme.INKED.face)
    assert not theme.STONE.shadow and theme.INKED.shadow, "only light text has the ink shadow"
    assert theme.STONE.face[3] == 255, "a menu slab is solid: the bright world must not show"


# --- painters --------------------------------------------------------------------------------

PAINTED = {
    "slab": lambda surface: kit_art.slab(120, 60, surface),
    "plate": lambda surface: kit_art.plate(120, 24, surface),
    "sign": lambda surface: kit_art.sign(160, 16, surface),
    "well": lambda surface: kit_art.well(80, 16, surface),
    "well_focus": lambda surface: kit_art.well(80, 16, surface, True),
    "toggle_on": lambda surface: kit_art.toggle_block(40, 17, True, False, surface),
    "toggle_off": lambda surface: kit_art.toggle_block(40, 17, False, True, surface),
    "pips": lambda surface: kit_art.pips(8, 5),
    "pad": lambda surface: kit_art.pad_button("A"),
}


@pytest.mark.parametrize("surface", theme.SURFACES, ids=lambda surface: surface.name)
@pytest.mark.parametrize("name", list(PAINTED))
def test_block_art_is_palette_only(surface: theme.Surface, name: str) -> None:
    image = PAINTED[name](surface)
    assert colours(image) <= resurrect64()
    assert {pixel[3] for pixel in image.getdata()} <= {0, 240, 255}, "no soft edges"


@pytest.mark.parametrize("surface", theme.SURFACES, ids=lambda surface: surface.name)
@pytest.mark.parametrize("look", list(Look))
def test_a_block_button_is_palette_only_at_rest_raised_and_pressed(
    surface: theme.Surface, look: Look
) -> None:
    for lift in (0, theme.RAISE, kit_art.lift_of(look, True)):
        assert colours(kit_art.block_button(80, 22, look, surface, lift)) <= resurrect64()


def test_a_block_has_a_face_a_lit_line_a_lip_and_an_outline() -> None:
    face, light, lip, outline = theme.GOLD, theme.PALE_GOLD, theme.AMBER, theme.INK
    image = kit_art.block(40, 20, (face, light, lip, outline), 3, 0)
    column = [image.getpixel((20, y))[:3] for y in range(20)]
    assert column[0] == outline and column[1] == light
    assert set(column[2:16]) == {face}
    assert column[16] == outline, "the face is closed along its bottom"
    assert column[17:19] == [lip, lip] and column[19] == outline
    assert image.getpixel((0, 10))[:3] == outline == image.getpixel((39, 10))[:3]


def test_the_cursors_block_stands_higher_and_a_pressed_one_sinks() -> None:
    rest = kit_art.block_button(80, 22, Look.NORMAL, theme.STONE)
    raised = kit_art.block_button(80, 22, Look.FOCUS, theme.STONE, theme.RAISE)
    assert rest.size == (80, 22) and raised.size == (80, 22 + theme.RAISE)
    assert kit_art.lift_of(Look.FOCUS) == theme.RAISE == kit_art.lift_of(Look.DANGER)
    assert kit_art.lift_of(Look.NORMAL) == 0 == kit_art.lift_of(Look.CAUTION)
    sunk = kit_art.lift_of(Look.FOCUS, pressed=True)
    assert sunk == -(theme.LIP - 1)
    pressed = kit_art.block_button(80, 22, Look.FOCUS, theme.STONE, sunk)
    assert pressed.size == rest.size, "a pressed block keeps its place"
    assert all(pressed.getpixel((40, y))[3] == 0 for y in range(-sunk)), "its top is empty"
    assert pressed.getpixel((40, -sunk))[3] == 255
    # The face is where the caption goes: it moves with the block.
    assert kit_art.face_span(22) == (theme.LIP, 22 - theme.LIP)
    assert kit_art.face_span(22, theme.RAISE) == (theme.LIP + theme.RAISE, 22 - theme.LIP)
    assert kit_art.face_span(22, sunk) == (1, 22 - theme.LIP)


def test_a_caution_button_rests_quiet_on_both_surfaces() -> None:
    """D-070 kept: a button that overwrites things is the loudest thing only under the
    cursor."""
    for surface in theme.SURFACES:
        resting = colours(kit_art.block_button(80, 22, Look.CAUTION, surface))
        assert theme.CRIMSON in resting, "its rim says what it is"
        assert kit_art.look_colours(Look.CAUTION, surface)[0][:3] != theme.CRIMSON
        assert kit_art.look_colours(Look.DANGER, surface)[0][:3] == theme.CRIMSON


def test_a_switch_shows_its_state_by_shape_as_well_as_colour() -> None:
    on = kit_art.toggle_block(40, 17, True, False, theme.STONE)
    off = kit_art.toggle_block(40, 17, False, False, theme.STONE)
    assert on.size == off.size
    assert on.getpixel((20, 0))[3] == 255 and off.getpixel((20, 0))[3] == 0, "off is sunk"
    assert theme.MINT in colours(on) and theme.MINT not in colours(off)
    focused = kit_art.toggle_block(40, 17, True, True, theme.STONE)
    assert theme.FOCUS in colours(focused) and theme.FOCUS not in colours(on)


def test_a_header_plate_has_turf_along_its_top() -> None:
    plate = kit_art.plate(120, 24, theme.STONE)
    slab = kit_art.slab(120, 24, theme.STONE)
    assert plate.size == slab.size
    grass = {theme.GRASS_LIGHT, theme.GRASS, theme.GRASS_DARK}
    assert grass <= colours(plate) and not grass & colours(slab)
    rows = [y for y in range(24) for x in range(120) if plate.getpixel((x, y))[:3] in grass]
    assert max(rows) <= kit_art.TURF_ROWS + max(kit_art.TURF_TUFTS) + theme.CORNER
    assert plate.getpixel((60, 0))[:3] == theme.INK, "the outline is kept"
    assert kit_art.plate(120, 24, theme.STONE).tobytes() == plate.tobytes(), "no randomness"


def test_pips_can_be_counted() -> None:
    row = kit_art.pips(8, 5)
    assert row.size == (kit_art.pips_width(8), kit_art.PIP_SIZE[1])
    lit = kit_art.pip(kit_art.GOLD_RAMP, True)
    unlit = kit_art.pip(kit_art.GOLD_RAMP, False)
    assert lit.tobytes() != unlit.tobytes() and len(colours(unlit)) == 1
    for index in range(8):
        cell = row.crop((index * kit_art.PIP_STEP, 0, index * kit_art.PIP_STEP + 8, 7))
        assert cell.tobytes() == (lit if index < 5 else unlit).tobytes()
    assert kit_art.pips(3, 9).tobytes() == kit_art.pips(3, 3).tobytes()


def test_gamepad_face_buttons_keep_their_usual_colours() -> None:
    assert theme.GREEN in colours(kit_art.pad_button("a"))
    assert theme.RED in colours(kit_art.pad_button("B"))
    assert colours(kit_art.pad_button("LB")) == {theme.SLATE, theme.INK}
    assert contrast(kit_art.pad_button_text("Y"), theme.GOLD) >= MIN_CONTRAST


# --- type ------------------------------------------------------------------------------------


def test_sentences_have_a_proportional_face() -> None:
    widths = {font.text_width(character, TextSize.TEXT) for character in PRINTABLE}
    assert len(widths) > 3, "letters are as wide as they need to be"
    sentence = "A young knight. Solid at everything, with big committed swings."
    assert font.text_width(sentence, TextSize.TEXT) < 0.75 * font.text_width(sentence)
    assert font.cap_height(TextSize.TEXT) >= 7


def test_a_letter_that_hooks_back_keeps_its_whole_shape() -> None:
    """Micro 5's "j" starts left of its own cell; a label draws one sprite a character."""
    alone = font.mask("j", TextSize.TEXT)
    assert alone.getbbox() is not None
    assert alone.getbbox()[0] == 0, "its hook starts at the cell's edge"
    word = font.mask("major", TextSize.TEXT)
    assert word.width == sum(font.text_width(each, TextSize.TEXT) for each in "major")
    pasted = Image.new("L", word.size, 0)
    x = 0
    for character in "major":
        pasted.paste(font.mask(character, TextSize.TEXT), (x, 0))
        x += font.text_width(character, TextSize.TEXT)
    assert pasted.tobytes() == word.tobytes(), "a line is its characters side by side"


def test_a_screen_title_is_the_logos_lettering_made_shallow() -> None:
    title = logo.build_title("RULES")
    deep = logo.build_logo("RULES", 1)
    assert title.height == deep.height - (logo.DEPTH - logo.TITLE_DEPTH)
    assert colours(title) <= resurrect64()
    assert (
        logo.build_logo("RULES").tobytes() == logo.build_logo("RULES", depth=logo.DEPTH).tobytes()
    )


# --- prompts ---------------------------------------------------------------------------------


def test_a_hint_line_splits_into_caps_and_words() -> None:
    line = "WASD: move   J: pick   K: back   mouse: click"
    assert hints.prompts(line) == [
        ("WASD", "move"),
        ("J", "pick"),
        ("K", "back"),
        ("mouse", "click"),
    ]
    assert hints.prompts("WASD KEYS   WASD: fighter   up: rules") == [
        ("", "WASD KEYS"),
        ("WASD", "fighter"),
        ("up", "rules"),
    ]
    assert hints.prompts("P2 JOINED ON PAD 1") == [("", "P2 JOINED ON PAD 1")]
    assert hints.prompts("") == []
    assert hints.prompts("J: on / off") == [("J", "on / off")]


@pytest.mark.parametrize(
    "device", [f"keyboard:{KEYBOARD_SOLO}", f"keyboard:{KEYBOARD_ARROWS}", "pad:0"]
)
def test_prompts_lose_nothing_of_the_hint(device: str) -> None:
    labels = hints.device_labels(Settings(), device)
    for template in (
        "{stick}: move   {attack}: pick   {special}: back   mouse: click",
        "{stick}: row and value   {attack}: on / off   {special}: back   mouse: click",
        "{stick}: fighter   {grab}: CPUs   up: rules   {special}: back",
        "{stick}: stage   {attack}: fight   {grab}: random pool   {special}: back",
    ):
        line = hints.hint_text(template, labels)
        rebuilt = hints.HINT_GAP.join(
            f"{control}{hints.HINT_SEPARATOR}{words}" if control else words
            for control, words in hints.prompts(line)
        )
        assert rebuilt == line
        assert all(control for control, _ in hints.prompts(line)), "every item has its cap"
    assert hints.is_pad("pad:0") and not hints.is_pad(f"keyboard:{KEYBOARD_SOLO}")


# --- the cloud wipe --------------------------------------------------------------------------


def test_the_cloud_rises_covers_and_clears() -> None:
    assert wipe.band_bottom(0) == -wipe.BAND_HEIGHT, "it starts just under the screen"
    assert wipe.band_bottom(-1) is None and wipe.band_bottom(wipe.WIPE_TICKS) is None
    bottoms = [wipe.band_bottom(tick) for tick in range(wipe.WIPE_TICKS)]
    assert all(bottom is not None for bottom in bottoms)
    assert bottoms == sorted(bottoms), "it only ever rises"
    assert wipe.covers(wipe.CLOSE_TICKS), "the screen is hidden when the scene changes"
    assert not wipe.covers(0) and not wipe.covers(wipe.WIPE_TICKS - 1)
    assert [wipe.shows_old(tick) for tick in (0, wipe.CLOSE_TICKS - 1, wipe.CLOSE_TICKS)] == [
        True,
        True,
        False,
    ]
    assert wipe.running(0) and wipe.running(wipe.WIPE_TICKS - 1)
    assert not wipe.running(wipe.WIPE_TICKS)
    last = bottoms[-1]
    assert last is not None and last + wipe.BAND_HEIGHT > NATIVE_H - 1, "still on screen"


def test_the_band_of_cloud_is_solid_in_the_middle_and_ragged_at_both_ends() -> None:
    band = wipe.build_band()
    assert band.size == (NATIVE_W, wipe.BAND_HEIGHT)
    assert colours(band) <= resurrect64()
    alpha = band.getchannel("A")
    assert set(alpha.getdata()) <= {0, 255}, "a pixel is cloud or it is not"
    middle = alpha.crop((0, wipe.EDGE, NATIVE_W, wipe.BAND_HEIGHT - wipe.EDGE))
    assert set(middle.getdata()) == {255}, "a screen's height of it hides everything"
    for rows in ((0, wipe.EDGE // 2), (wipe.BAND_HEIGHT - wipe.EDGE // 2, wipe.BAND_HEIGHT)):
        edge = alpha.crop((0, rows[0], NATIVE_W, rows[1]))
        assert set(edge.getdata()) == {0, 255}, "puffs, not a straight line"
    assert wipe.build_band().tobytes() == band.tobytes(), "the same cloud every time"
