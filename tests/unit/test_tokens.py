import tomllib
from pathlib import Path

import pytest

from src.ui.tokens import COLORS, css_variables

CONFIG = Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize(
    "fg,bg",
    [
        ("text_primary", "background"),
        ("text_primary", "surface"),
        ("text_secondary", "background"),
        ("text_secondary", "surface"),
        ("text_secondary", "surface_subtle"),
        ("success", "success_bg"),
        ("warning", "warning_bg"),
        ("danger", "danger_bg"),
        ("primary", "surface"),
        ("accent", "surface"),
    ],
)
def test_text_pairs_meet_wcag_aa(fg, bg):
    # WCAG 2.2 AA for normal-size text requires 4.5:1.
    assert contrast(COLORS[fg], COLORS[bg]) >= 4.5, (fg, bg)


def test_streamlit_theme_mirrors_tokens():
    theme = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]
    assert theme["primaryColor"].upper() == COLORS["primary"].upper()
    assert theme["backgroundColor"].upper() == COLORS["background"].upper()
    assert theme["secondaryBackgroundColor"].upper() == COLORS["surface_subtle"].upper()
    assert theme["textColor"].upper() == COLORS["text_primary"].upper()


def test_css_variables_include_every_colour():
    css = css_variables()
    for name, value in COLORS.items():
        assert f"--cm-color-{name.replace('_', '-')}: {value};" in css


def test_stylesheet_has_no_angle_brackets_inside_the_style_block():
    # Streamlit's HTML sanitiser drops a whole <style> block that contains anything tag-like.
    from src.ui.theme import build_stylesheet
    body = build_stylesheet().removeprefix("<style>").removesuffix("</style>")
    assert "<" not in body


def test_sidebar_colours_meet_wcag_aa():
    assert contrast(COLORS["sidebar_text"], COLORS["sidebar"]) >= 4.5
    assert contrast(COLORS["sidebar_muted"], COLORS["sidebar"]) >= 4.5
    assert contrast(COLORS["sidebar_text"], COLORS["sidebar_active"]) >= 4.5
    sidebar = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]["sidebar"]
    assert sidebar["backgroundColor"].upper() == COLORS["sidebar"].upper()
    assert sidebar["textColor"].upper() == COLORS["sidebar_text"].upper()
