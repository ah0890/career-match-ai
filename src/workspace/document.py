"""The structured, editable CV.

A CV is a contact block plus ordered sections; a section holds entries (a role, a degree, a
project) and each entry holds items (bullets, lines or single skills). Every piece of text
carries its *provenance*, so the app never confuses what the user stated with what it guessed:

* ``extracted``  — read from the uploaded document, not yet confirmed by the user
* ``verified``   — confirmed by the user
* ``edited``     — written or changed by the user
* ``suggested``  — wording from a recommendation the user accepted; facts unchanged
* ``unverified`` — supplied by a recommendation and still needing the user's confirmation
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field

Provenance = Literal["extracted", "verified", "edited", "suggested", "unverified"]
SectionKind = Literal["summary", "experience", "education", "skills", "certifications", "projects", "awards",
                      "languages", "publications", "volunteering", "memberships", "interests", "references",
                      "custom"]

ENTRY_KINDS = ("experience", "education", "projects", "volunteering")  # header line + bullets
INLINE_KINDS = ("skills", "languages", "interests")  # items rendered on one line
DEFAULT_TITLES = {
    "summary": "Professional Summary", "experience": "Experience", "education": "Education", "skills": "Skills",
    "certifications": "Certifications", "projects": "Projects", "awards": "Awards", "languages": "Languages",
    "publications": "Publications", "volunteering": "Volunteering", "memberships": "Memberships",
    "interests": "Interests", "references": "References", "custom": "Additional Information",
}


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class Item(BaseModel):
    id: str = Field(default_factory=new_id)
    text: str
    provenance: Provenance = "extracted"
    hidden: bool = False  # left out of this version's PDF (only ever by the user's choice)


class Entry(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = ""  # role, degree, project name
    organization: str = ""  # employer, institution
    location: str = ""
    dates: str = ""  # as written, e.g. "Jan 2019 – Present"
    items: list[Item] = Field(default_factory=list)
    provenance: Provenance = "extracted"
    hidden: bool = False

    @property
    def header(self) -> str:
        return " — ".join(p for p in (self.title, self.organization, self.location, self.dates) if p)


class Section(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: SectionKind
    title: str
    entries: list[Entry] = Field(default_factory=list)
    hidden: bool = False


class Contact(BaseModel):
    name: str = ""
    headline: str = ""  # professional title, e.g. "Quality Engineer"
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[str] = Field(default_factory=list)
    provenance: Provenance = "extracted"


class CVDocument(BaseModel):
    schema_version: int = 1
    contact: Contact = Field(default_factory=Contact)
    sections: list[Section] = Field(default_factory=list)

    # --- lookup --------------------------------------------------------------

    def section(self, kind: str) -> Section | None:
        return next((s for s in self.sections if s.kind == kind), None)

    def iter_items(self, include_hidden: bool = True) -> Iterator[tuple[Section, Entry, Item]]:
        for s in self.sections:
            if s.hidden and not include_hidden:
                continue
            for e in s.entries:
                if e.hidden and not include_hidden:
                    continue
                for i in e.items:
                    if include_hidden or not i.hidden:
                        yield s, e, i

    def find_item(self, item_id: str) -> tuple[Section, Entry, Item] | None:
        return next(((s, e, i) for s, e, i in self.iter_items() if i.id == item_id), None)

    def find_entry(self, entry_id: str) -> tuple[Section, Entry] | None:
        return next(((s, e) for s in self.sections for e in s.entries if e.id == entry_id), None)

    def find_section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    # --- editing ---------------------------------------------------------------

    def set_item_text(self, item_id: str, text: str, provenance: Provenance) -> None:
        found = self.find_item(item_id)
        if found is None:
            raise KeyError(item_id)
        found[2].text = " ".join(text.split())
        found[2].provenance = provenance

    def ensure_section(self, kind: SectionKind, position: int | None = None) -> Section:
        if (s := self.section(kind)) is not None:
            return s
        s = Section(kind=kind, title=DEFAULT_TITLES[kind])
        if position is None:
            self.sections.append(s)
        else:
            self.sections.insert(position, s)
        return s

    def move_section(self, section_id: str, offset: int) -> None:
        idx = next(i for i, s in enumerate(self.sections) if s.id == section_id)
        new = max(0, min(len(self.sections) - 1, idx + offset))
        self.sections.insert(new, self.sections.pop(idx))

    # --- text ------------------------------------------------------------------

    def to_text(self, include_hidden: bool = False) -> str:
        """Plain text in the layout the app's CV parser understands (used for matching and ATS checks)."""
        c = self.contact
        lines = [x for x in (c.name, c.headline) if x]
        contact = " | ".join(x for x in (c.email, c.phone, c.location, *c.links) if x)
        if contact:
            lines.append(contact)
        for s in self.sections:
            if s.hidden and not include_hidden:
                continue
            entries = [e for e in s.entries if include_hidden or not e.hidden]
            items_of = (lambda e: [i for i in e.items if include_hidden or not i.hidden])
            if not any(e.header or items_of(e) for e in entries):
                continue
            lines += ["", s.title.upper()]
            for e in entries:
                if s.kind in INLINE_KINDS:
                    lines.append(", ".join(i.text for i in items_of(e)))
                    continue
                if e.header:
                    lines.append(e.header)
                bullet = s.kind not in ("summary",)
                lines += [f"- {i.text}" if bullet else i.text for i in items_of(e)]
        return "\n".join(lines).strip() + "\n"

    def word_count(self) -> int:
        return len(self.to_text().split())
