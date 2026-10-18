"""Small parsing helpers shared by adapters."""

from __future__ import annotations

from typing import Any

from src.jobs.models import EmploymentType
from src.jobs.normalization import clean_text, parse_employment_type


def str_list(value: Any, max_items: int = 30) -> list[str]:
    """Accept a list of strings (or a single string) and return cleaned strings."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:max_items]:
        if isinstance(item, dict):  # some APIs return {"name": ...} objects
            item = item.get("name") or item.get("label")
        text = clean_text(item, 80)
        if text:
            out.append(text)
    return out


def first_employment_type(values: list[str]) -> EmploymentType:
    for v in values:
        t = parse_employment_type(v.replace(" ", "_"))
        if t is EmploymentType.UNKNOWN:
            t = parse_employment_type(v)
        if t is not EmploymentType.UNKNOWN:
            return t
    return EmploymentType.UNKNOWN
