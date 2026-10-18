"""Design tokens: the single source of truth for colours, type, spacing and radii.

`.streamlit/config.toml` mirrors the core colour tokens (Streamlit reads its theme
from there); a unit test keeps the two in sync.
"""

from __future__ import annotations

COLORS: dict[str, str] = {
    "primary": "#243B64",
    "primary_hover": "#1B2F52",
    "accent": "#4F6BED",
    "link": "#3B55D9",
    "background": "#F6F8FC",
    "surface": "#FFFFFF",
    "surface_subtle": "#EEF2F8",
    "text_primary": "#172033",
    "text_secondary": "#5B6476",
    "border": "#E3E8F0",
    "success": "#0F7458",
    "success_bg": "#E8F6F0",
    "warning": "#8F5E12",
    "warning_bg": "#FFF5DF",
    "danger": "#B3323D",
    "danger_bg": "#FDECEE",
}

# System font stack — no externally hosted font is required. Inter / Manrope are
# used automatically when installed locally.
FONT_FAMILY = (
    '"Inter", "Manrope", "Segoe UI", system-ui, -apple-system, '
    '"Helvetica Neue", Arial, sans-serif'
)

# Type scale in pixels (desktop).
FONT_SIZES: dict[str, int] = {
    "page_title": 30,
    "section": 22,
    "card_title": 17,
    "body": 15,
    "label": 13,
    "caption": 13,
    "score": 38,
}

# 8px spacing rhythm (with a 4px half-step).
SPACING: dict[str, int] = {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32, "xxl": 48}

RADII: dict[str, int] = {"sm": 6, "md": 10, "lg": 14, "pill": 999}

SHADOWS: dict[str, str] = {
    "card": "0 1px 2px rgba(23, 32, 51, 0.04), 0 1px 3px rgba(23, 32, 51, 0.06)",
}


def css_variables() -> str:
    """Render the tokens as CSS custom properties on ``:root``."""
    lines = [f"  --cm-color-{k.replace('_', '-')}: {v};" for k, v in COLORS.items()]
    lines += [f"  --cm-font-{k.replace('_', '-')}: {v}px;" for k, v in FONT_SIZES.items()]
    lines += [f"  --cm-space-{k}: {v}px;" for k, v in SPACING.items()]
    lines += [f"  --cm-radius-{k}: {v}px;" for k, v in RADII.items()]
    lines += [f"  --cm-shadow-{k}: {v};" for k, v in SHADOWS.items()]
    lines.append(f"  --cm-font-family: {FONT_FAMILY};")
    return ":root {\n" + "\n".join(lines) + "\n}"
