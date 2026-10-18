"""Country choices for job searches (ISO 3166-1 alpha-2, lowercase)."""

from __future__ import annotations

COUNTRIES: dict[str, str] = {
    "ae": "United Arab Emirates", "at": "Austria", "au": "Australia", "bd": "Bangladesh", "be": "Belgium",
    "bh": "Bahrain", "br": "Brazil", "ca": "Canada", "ch": "Switzerland", "cn": "China", "de": "Germany",
    "dk": "Denmark", "eg": "Egypt", "es": "Spain", "fi": "Finland", "fr": "France", "gb": "United Kingdom",
    "ie": "Ireland", "in": "India", "it": "Italy", "jo": "Jordan", "jp": "Japan", "ke": "Kenya", "kw": "Kuwait",
    "lk": "Sri Lanka", "my": "Malaysia", "mx": "Mexico", "ng": "Nigeria", "nl": "Netherlands", "no": "Norway",
    "nz": "New Zealand", "om": "Oman", "ph": "Philippines", "pk": "Pakistan", "pl": "Poland", "pt": "Portugal",
    "qa": "Qatar", "sa": "Saudi Arabia", "se": "Sweden", "sg": "Singapore", "tr": "Turkey", "us": "United States",
    "za": "South Africa",
}

# Common alternative names used in job location fields.
ALIASES: dict[str, tuple[str, ...]] = {
    "us": ("usa", "united states", "u.s.", "america"), "gb": ("uk", "united kingdom", "england", "britain"),
    "ae": ("uae", "united arab emirates", "dubai", "abu dhabi"), "sa": ("saudi", "ksa", "saudi arabia"),
}


def country_terms(code: str | None) -> list[str]:
    """Names that may identify the country in a free-text location (lowercase)."""
    if not code or code not in COUNTRIES:
        return []
    return [COUNTRIES[code].lower(), *ALIASES.get(code, ())]
