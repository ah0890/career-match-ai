"""Small text helpers shared by the matching modules: sentence splitting and light stemming."""

from __future__ import annotations

import re

from src.cv.ats import _STOPWORDS

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z+#]*")  # hyphens split words: "root-cause" → "root", "cause"
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ers", "er", "ed", "es", "s")
# Irregular past tenses common in CVs, so "Led a team" matches "lead a team".
_IRREGULAR = {"led": "lead", "built": "build", "ran": "run", "wrote": "write", "drove": "drive", "grew": "grow",
              "oversaw": "oversee", "taught": "teach", "brought": "bring", "sold": "sell", "won": "win",
              "began": "begin", "made": "make", "took": "take", "chose": "choose", "spoke": "speak",
              "thought": "think", "bought": "buy", "kept": "keep", "met": "meet"}
# Generic job-ad words that say nothing about the work itself.
_GENERIC = frozenset("""
across along also ensure ensuring help helping other others part through various within while closely
daily regular regularly appropriate relevant related effective effectively high highly wide wider
""".split())


def stem(word: str) -> str:
    """Crude suffix stripping so 'managed', 'manages' and 'managing' compare equal."""
    w = _IRREGULAR.get(word.lower(), word.lower())
    if w.endswith(("ies", "ied")) and len(w) > 5:
        return w[:-3] + "y"  # "supplies"/"supplied" → "supply"
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            w = w[: -len(suffix)]
            break
    # Drop a final "e" so "manage" and "managed" (→ "manag") compare equal.
    return w[:-1] if w.endswith("e") and len(w) > 4 else w


def content_stems(text: str) -> list[str]:
    """Distinct stems of meaningful words (4+ letters, not stopwords), in order of appearance."""
    out: dict[str, None] = {}
    for word in _WORD_RE.findall(text):
        lw = _IRREGULAR.get(word.lower(), word.lower())
        if len(lw) < 4 or lw in _STOPWORDS or lw in _GENERIC:
            continue
        out.setdefault(stem(lw), None)
    return list(out)


def split_sentences(text: str) -> list[str]:
    """Split a job description into lines and sentences, keeping bullet items whole."""
    parts: list[str] = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-•*·▪◦").strip()
        if not line:
            continue
        parts.extend(s.strip() for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z])", line) if s.strip())
    return parts
