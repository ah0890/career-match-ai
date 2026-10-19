"""Design tokens: the single source of truth for colours, type, spacing and radii.

`.streamlit/config.toml` mirrors the core colour tokens (Streamlit reads its theme
from there); a unit test keeps the two in sync.
"""

from __future__ import annotations

COLORS: dict[str, str] = {
    "primary": "#13294B",
    "primary_hover": "#0B1C36",
    "accent": "#2563EB",
    "link": "#1D4ED8",
    "background": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_subtle": "#EDF1F7",
    "text_primary": "#0F172A",
    "text_secondary": "#4A5568",
    "border": "#E1E7EF",
    "success": "#04694F",
    "success_bg": "#E6F5EE",
    "warning": "#8A4B08",
    "warning_bg": "#FEF4E2",
    "danger": "#B42318",
    "danger_bg": "#FDECEB",
    # Dark navigation sidebar and dashboard hero.
    "sidebar": "#0C1A31",
    "sidebar_active": "#1B2D4F",
    "sidebar_text": "#D5DEEC",
    "sidebar_muted": "#8FA0BC",
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

RADII: dict[str, int] = {"sm": 6, "md": 10, "lg": 14, "xl": 18, "pill": 999}

SHADOWS: dict[str, str] = {
    "card": "0 1px 2px rgba(15, 23, 42, 0.04), 0 2px 8px rgba(15, 23, 42, 0.04)",
    "raised": "0 2px 4px rgba(15, 23, 42, 0.05), 0 12px 28px rgba(15, 23, 42, 0.08)",
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
