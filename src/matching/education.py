"""Degree-level detection shared by job requirements and CV education.

Levels are ordered so a higher qualification satisfies a lower requirement. Only the
level is compared — a degree's subject is reported as evidence but never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class DegreeLevel(IntEnum):
    NONE = 0
    DIPLOMA = 1  # diploma, associate degree, HND
    BACHELOR = 2
    MASTER = 3
    DOCTORATE = 4


LEVEL_LABELS = {
    DegreeLevel.DIPLOMA: "diploma or associate degree", DegreeLevel.BACHELOR: "bachelor's degree",
    DegreeLevel.MASTER: "master's degree", DegreeLevel.DOCTORATE: "doctorate",
}

# Abbreviations are case-sensitive so "BA" and "MS" do not match ordinary words.
_PATTERNS: tuple[tuple[DegreeLevel, re.Pattern[str]], ...] = (
    (DegreeLevel.DOCTORATE, re.compile(r"(?i:\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b)|\bDPhil\b|\bEngD\b")),
    (DegreeLevel.MASTER, re.compile(
        r"(?i:\bmaster(?:'s|’s|s)(?=\W|$)|\bmaster\s+(?:of|degree)\b|\bpostgraduate\s+degree\b)"
        r"|\b(?:MSc|MBA|MEng|MPhil|MRes|M\.Sc|M\.S|M\.A)\b"
        # Bare "MS"/"MA" are common false positives ("MS Excel", "Boston, MA").
        r"|(?<!, )\b(?:MS|MA)\b(?!\s+(?:Excel|Office|Word|Teams|SQL|Project|Access|Dynamics|PowerPoint|Outlook|Visio|Azure))"
        r"(?=\s*(?:in|of|degree|\(|,|-|–|—|\s[A-Z]))")),
    (DegreeLevel.BACHELOR, re.compile(
        r"(?i:\bbachelor'?s?\b|\bundergraduate\s+degree\b|\bbaccalaureate\b|\buniversity\s+degree\b"
        r"|\bfour[- ]year\s+degree\b|\bcollege\s+degree\b)"
        r"|\b(?:BSc|BEng|BTech|BBA|BCom|BA|BS|B\.Sc|B\.S|B\.A|B\.E|B\.Tech|LLB)\b")),
    (DegreeLevel.DIPLOMA, re.compile(
        r"(?i:\bassociate'?s?\s+degree\b|\bdiploma\b|\bhnd\b|\bhnc\b|\bvocational\s+qualification\b)")),
)
# "degree" alone, excluding "360-degree feedback" and "a high degree of autonomy".
_GENERIC_DEGREE = re.compile(r"(?i)(?<![\d-])(?<!\d )\bdegree\b(?!\s+of\b)|\b(?:university|college)\s+graduate\b")


@dataclass(frozen=True)
class DegreeMention:
    level: DegreeLevel
    text: str  # the sentence or line it was found in


def highest_degree(text: str) -> DegreeMention | None:
    """The highest degree level mentioned, with the line that mentions it."""
    best: DegreeMention | None = None
    for line in text.split("\n"):
        for level, pattern in _PATTERNS:
            if pattern.search(line):
                if best is None or level > best.level:
                    best = DegreeMention(level, line.strip())
                break
    return best


def lowest_degree(text: str) -> DegreeMention | None:
    """The lowest specific level mentioned (job ads often say "bachelor's or master's").

    A bare "degree" with no level is read as a bachelor's degree, which is how employers
    normally use the word; the evidence line is kept so the user can check.
    """
    found: list[DegreeMention] = []
    for level, pattern in _PATTERNS:
        m = pattern.search(text)
        if m:
            found.append(DegreeMention(level, text.strip()))
    if found:
        return min(found, key=lambda d: d.level)
    if _GENERIC_DEGREE.search(text):
        return DegreeMention(DegreeLevel.BACHELOR, text.strip())
    return None
