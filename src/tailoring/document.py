"""Plain-text CV operations used by tailoring: find, replace and restructure sections.

The CV text produced by extraction is the single source of truth. Every operation returns
new text and leaves everything outside the targeted section exactly as it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.cv.parsing import match_heading

_ITEM_SPLIT = re.compile(r"\s*[,;|•·]\s*")


@dataclass(frozen=True)
class SectionSpan:
    key: str
    heading_line: int  # index of the heading line
    start: int  # first body line
    end: int  # one past the last body line


def section_spans(text: str) -> list[SectionSpan]:
    lines = text.split("\n")
    heads = [(i, key) for i, line in enumerate(lines) if (key := match_heading(line)) is not None]
    spans = []
    for n, (i, key) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        spans.append(SectionSpan(key, i, i + 1, end))
    return spans


def find_section(text: str, key: str) -> SectionSpan | None:
    return next((s for s in section_spans(text) if s.key == key), None)


def section_body(text: str, key: str) -> str | None:
    span = find_section(text, key)
    if span is None:
        return None
    return "\n".join(text.split("\n")[span.start:span.end]).strip("\n")


def replace_section_body(text: str, key: str, body: str) -> str:
    """Replace a section's body, keeping its heading and one blank line before the next section."""
    span = find_section(text, key)
    if span is None:
        return text
    lines = text.split("\n")
    trailing_blank = span.end < len(lines) and span.end > span.start and lines[span.end - 1].strip() == ""
    new_body = body.strip("\n").split("\n") + ([""] if trailing_blank else [])
    return "\n".join(lines[:span.start] + new_body + lines[span.end:])


def insert_section_after_preamble(text: str, heading: str, body: str) -> str:
    """Add a new section before the first recognised section (e.g. a summary after the contact lines)."""
    spans = section_spans(text)
    lines = text.split("\n")
    at = spans[0].heading_line if spans else len(lines)
    block = [heading, *body.strip("\n").split("\n"), ""]
    return "\n".join(lines[:at] + block + lines[at:])


# --- Skills lists ---------------------------------------------------------

@dataclass(frozen=True)
class SkillList:
    items: tuple[str, ...]
    style: str  # "inline" (comma-separated lines) or "bullets"


def parse_skill_list(body: str) -> SkillList:
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if lines and all(ln.startswith(("- ", "• ")) for ln in lines):
        return SkillList(tuple(ln[2:].strip() for ln in lines), "bullets")
    items: list[str] = []
    for ln in lines:
        items.extend(i for i in _ITEM_SPLIT.split(ln.lstrip("-• ")) if i)
    return SkillList(tuple(dict.fromkeys(items)), "inline")


def render_skill_list(skills: SkillList) -> str:
    if skills.style == "bullets":
        return "\n".join(f"- {s}" for s in skills.items)
    return ", ".join(skills.items)


# --- Experience blocks ----------------------------------------------------

def split_roles(body: str) -> list[tuple[list[str], list[str]]]:
    """Group experience lines into (header lines, bullet lines) per role, in order."""
    roles: list[tuple[list[str], list[str]]] = []
    for line in body.split("\n"):
        is_bullet = line.startswith("- ")
        if not roles or (not is_bullet and roles[-1][1]):
            roles.append(([], []))
        (roles[-1][1] if is_bullet else roles[-1][0]).append(line)
    return roles


def join_roles(roles: list[tuple[list[str], list[str]]]) -> str:
    return "\n".join(line for header, bullets in roles for line in (*header, *bullets))
