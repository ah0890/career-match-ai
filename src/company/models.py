"""Company research data. Every fact carries the source it came from."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    licence: str  # how the content may be reused, shown with the attribution


WIKIDATA_LICENCE = "CC0 1.0"
WIKIPEDIA_LICENCE = "CC BY-SA 4.0"


@dataclass(frozen=True)
class CompanyCandidate:
    """A possible match for a company name; the user confirms which one is meant."""

    entity_id: str  # Wikidata id, e.g. "Q95"
    label: str
    description: str | None
    url: str


@dataclass(frozen=True)
class Fact:
    label: str
    value: str
    source: Source
    as_of: str | None = None  # the date the source gives for this value, if any


@dataclass(frozen=True)
class Summary:
    text: str
    source: Source


@dataclass(frozen=True)
class CompanyProfile:
    entity_id: str
    name: str
    description: str | None
    summary: Summary | None
    facts: tuple[Fact, ...]
    leadership: tuple[Fact, ...]
    official_website: str | None
    not_available: tuple[str, ...]  # fact types the sources did not provide
    retrieved_at: datetime
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def sources(self) -> tuple[Source, ...]:
        seen: dict[str, Source] = {}
        for f in (*self.facts, *self.leadership):
            seen.setdefault(f.source.url, f.source)
        if self.summary:
            seen.setdefault(self.summary.source.url, self.summary.source)
        return tuple(seen.values())
