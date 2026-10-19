"""Visual style: what the original CV looked like, and the reusable settings a PDF is rendered with.

Only standard PDF fonts are used (Helvetica, Times, Courier families), so text is always
selectable, searchable and complete without embedding font files. The original's typeface is
mapped to the closest of these.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FontFamily = Literal["sans-serif", "serif"]
Template = Literal["original", "classic", "modern"]

# Readability limits the one-page fitter never goes below.
MIN_BODY_SIZE = 9.0
MIN_MARGIN = 36.0  # 0.5 inch
PAGE_SIZES = {"a4": (595.0, 842.0), "letter": (612.0, 792.0)}


class StyleProfile(BaseModel):
    """Measurements taken from the uploaded document (first page)."""

    page_width: float
    page_height: float
    margin_left: float
    margin_right: float
    margin_top: float
    margin_bottom: float
    font_family: FontFamily
    body_size: float
    heading_size: float
    name_size: float
    accent_color: str
    columns: int = 1
    source: str = "default"

    @staticmethod
    def family_for(font_name: str) -> FontFamily:
        name = (font_name or "").lower()
        serif = ("times", "georgia", "garamond", "cambria", "serif", "book antiqua", "palatino", "minion")
        return "serif" if any(s in name for s in serif) and "sans" not in name else "sans-serif"

    @classmethod
    def default(cls) -> StyleProfile:
        w, h = PAGE_SIZES["a4"]
        return cls(page_width=w, page_height=h, margin_left=54, margin_right=54, margin_top=48, margin_bottom=48,
                   font_family="sans-serif", body_size=10.5, heading_size=11.5, name_size=20, accent_color="#1F2937")


class FormatSettings(BaseModel):
    """How a version is laid out. Saved with each version so regeneration is predictable."""

    template: Template = "classic"
    page: Literal["a4", "letter"] = "a4"
    font_family: FontFamily = "sans-serif"
    body_size: float = Field(10.5, ge=MIN_BODY_SIZE, le=13)
    heading_size: float = Field(11.5, ge=9, le=16)
    name_size: float = Field(20, ge=12, le=30)
    accent_color: str = Field("#1F2937", pattern=r"^#[0-9A-Fa-f]{6}$")
    margin: float = Field(54, ge=MIN_MARGIN, le=90)
    line_height: float = Field(1.3, ge=1.1, le=1.6)
    section_gap: float = Field(9, ge=3, le=18)

    @classmethod
    def from_profile(cls, profile: StyleProfile) -> FormatSettings:
        """Settings inspired by the original, clamped to readable, ATS-friendly limits."""
        page = min(PAGE_SIZES, key=lambda k: abs(PAGE_SIZES[k][0] - profile.page_width))
        margin = sum((profile.margin_left, profile.margin_right)) / 2
        accent = profile.accent_color if _readable(profile.accent_color) else "#1F2937"
        return cls(template="original", page=page, font_family=profile.font_family,
                   body_size=_clamp(profile.body_size, MIN_BODY_SIZE, 12),
                   heading_size=_clamp(profile.heading_size, 10, 15), name_size=_clamp(profile.name_size, 14, 26),
                   accent_color=accent, margin=_clamp(margin, MIN_MARGIN, 80))


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 1)


def _readable(hex_color: str) -> bool:
    """Dark enough on white for headings (WCAG AA for large text, 3:1)."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    luminance = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return 1.05 / (luminance + 0.05) >= 3.0
