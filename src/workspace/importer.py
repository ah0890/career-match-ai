"""Turn an uploaded CV into a structured document, and read its visual style.

Everything imported is marked ``extracted``: the user confirms or corrects it before it is
treated as verified. Unknown headings become custom sections, so nothing in the original is lost.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass

from src.cv.parsing import DATE_RANGE_RE, EMAIL_RE, PHONE_RE, URL_RE, _guess_name, looks_like_heading, match_heading
from src.workspace.document import (
    DEFAULT_TITLES, ENTRY_KINDS, INLINE_KINDS, Contact, CVDocument, Entry, Item, Section,
)
from src.workspace.style import StyleProfile

_BULLET = re.compile(r"^\s*(?:[-•*▪●◦‣–]|\d{1,2}[.)])\s+")
_HEADER_SPLIT = re.compile(r"\s+[—–|]\s+|\s+-\s+|\s*\|\s*")
_YEAR_END = re.compile(r"(?:^|\s)((?:19|20)\d{2})\s*$")
_INLINE_SPLIT = re.compile(r"\s*[,;•·|]\s*")


def _split_blocks(text: str) -> tuple[list[str], list[tuple[str, str | None, list[str]]]]:
    """(preamble lines, [(heading, canonical key or None, body lines)])."""
    preamble: list[str] = []
    blocks: list[tuple[str, str | None, list[str]]] = []
    for line in text.split("\n"):
        key = match_heading(line)
        if key is not None or (looks_like_heading(line) and _preamble_done(preamble, blocks)):
            blocks.append((line.strip().rstrip(":"), key, []))
            continue
        (blocks[-1][2] if blocks else preamble).append(line)
    return preamble, blocks


def _preamble_done(preamble: list[str], blocks: list) -> bool:
    """An all-caps line in the first lines is usually the name, not a heading."""
    return bool(blocks) or len([p for p in preamble if p.strip()]) >= 2


def _contact(preamble: list[str], full_text: str) -> Contact:
    head = "\n".join(preamble) or "\n".join(full_text.split("\n")[:6])
    email = EMAIL_RE.search(head) or EMAIL_RE.search(full_text)
    phone = next((m.group(0).strip() for m in PHONE_RE.finditer(head) if len(re.sub(r"\D", "", m.group(0))) >= 8), "")
    links = list(dict.fromkeys(m.group(0).rstrip(".") for m in URL_RE.finditer(head)))
    lines = [l.strip() for l in preamble if l.strip()]
    name = _guess_name(lines) or ""
    headline = ""
    location = ""
    for line in lines:
        if line == name or line.upper() == name.upper():
            continue
        if EMAIL_RE.search(line) or PHONE_RE.search(line) or URL_RE.search(line):
            parts = [p.strip() for p in re.split(r"\s*[|•·]\s*", line)]
            leftovers = [p for p in parts if p and not (EMAIL_RE.search(p) or PHONE_RE.search(p) or URL_RE.search(p))]
            if leftovers and not location:
                location = leftovers[0][:120]
            continue
        if not headline and len(line.split()) <= 8:
            headline = line[:120]
    return Contact(name=name, headline=headline, email=email.group(0) if email else "", phone=phone,
                   location=location, links=links)


def _parse_header(line: str) -> Entry:
    raw = line.strip()
    dates = ""
    m = DATE_RANGE_RE.search(raw) or _YEAR_END.search(raw)
    if m:
        dates = m.group(0).strip()
        raw = (raw[:m.start()] + raw[m.end():]).strip(" ,—–-|()")
    parts = [p.strip(" ,") for p in _HEADER_SPLIT.split(raw) if p.strip(" ,")]
    if len(parts) == 1 and "," in parts[0] and " at " not in parts[0]:
        parts = [p.strip() for p in parts[0].split(",", 1)]
    if len(parts) == 1 and " at " in parts[0]:
        parts = [p.strip() for p in parts[0].split(" at ", 1)]
    title = parts[0] if parts else ""
    organization = parts[1] if len(parts) > 1 else ""
    location = ", ".join(parts[2:]) if len(parts) > 2 else ""
    return Entry(title=title, organization=organization, location=location, dates=dates)


def _is_header(line: str) -> bool:
    return bool(DATE_RANGE_RE.search(line) or _YEAR_END.search(line.strip())) and len(line.split()) <= 18


def _entries(kind: str, lines: list[str]) -> list[Entry]:
    body = [l.rstrip() for l in lines if l.strip()]
    if kind in INLINE_KINDS:
        items: list[Item] = []
        for line in body:
            text = _BULLET.sub("", line).strip()
            if ":" in text and len(text) > 40:  # "Tools: X, Y, Z" stays one labelled line
                items.append(Item(text=text))
            else:
                items += [Item(text=t) for t in _INLINE_SPLIT.split(text) if t]
        return [Entry(items=items)] if items else []
    if kind in ENTRY_KINDS:
        entries: list[Entry] = []
        for line in body:
            if _BULLET.match(line):
                if not entries:
                    entries.append(Entry())
                entries[-1].items.append(Item(text=_BULLET.sub("", line).strip()))
            elif _is_header(line) or not entries or (entries[-1].items and not line[0].islower()):
                entries.append(_parse_header(line))
            elif not entries[-1].items and not entries[-1].organization and len(line.split()) <= 8:
                entries[-1].organization = line.strip()  # header written over two lines
            else:
                entries[-1].items.append(Item(text=line.strip()))
        return entries
    # summary, certifications, awards, custom…: one entry of lines or bullets
    if kind == "summary":
        paragraph = " ".join(_BULLET.sub("", l).strip() for l in body)
        return [Entry(items=[Item(text=paragraph)])] if paragraph else []
    return [Entry(items=[Item(text=_BULLET.sub("", l).strip()) for l in body])] if body else []


def import_text(text: str) -> CVDocument:
    preamble, blocks = _split_blocks(text.replace("\r", ""))
    doc = CVDocument(contact=_contact(preamble, text))
    seen: dict[str, Section] = {}
    for heading, key, lines in blocks:
        kind = key if key in DEFAULT_TITLES else "custom"
        if key == "personal":  # contact details listed as a section
            continue
        entries = _entries(kind, lines)
        if kind != "custom" and kind in seen:  # the same section split across pages
            seen[kind].entries += entries
            continue
        title = heading.title() if heading.isupper() else heading
        section = Section(kind=kind, title=title or DEFAULT_TITLES[kind], entries=entries)
        doc.sections.append(section)
        seen[kind] = section
    if not doc.sections and text.strip():  # no headings at all: keep everything as one custom section
        doc.sections.append(Section(kind="custom", title="Imported text",
                                    entries=_entries("custom", text.split("\n")[len(preamble):])))
    return doc


# --- visual style -------------------------------------------------------------------------

@dataclass(frozen=True)
class _Span:
    size: float
    font: str
    color: int
    bold: bool
    x0: float


def style_from_pdf(data: bytes) -> StyleProfile:
    import pymupdf as fitz
    with fitz.open(stream=data, filetype="pdf") as pdf:
        page = pdf[0]
        width, height = page.rect.width, page.rect.height
        spans: list[_Span] = []
        lefts, tops = [], []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for s in line.get("spans", []):
                    if not s["text"].strip():
                        continue
                    spans.append(_Span(round(s["size"], 1), s["font"], s["color"], bool(s["flags"] & 16), s["bbox"][0]))
                    lefts.append(s["bbox"][0])
                    tops.append(s["bbox"][1])
    if not spans:
        return StyleProfile.default()
    weights = Counter()
    for s in spans:
        weights[s.size] += 1
    body = weights.most_common(1)[0][0]
    largest = max(s.size for s in spans)
    heading_sizes = [s.size for s in spans if s.bold and body < s.size < largest]
    colors = Counter(s.color for s in spans if s.color not in (0,) and (s.bold or s.size > body))
    font = Counter(s.font for s in spans if s.size == body).most_common(1)[0][0]
    xs = sorted({round(s.x0) for s in spans})
    columns = 2 if any(x > width * 0.45 for x in xs) and sum(1 for s in spans if s.x0 > width * 0.45) > len(spans) * 0.2 else 1
    return StyleProfile(
        page_width=round(width, 1), page_height=round(height, 1),
        # Right and bottom extents depend on how much text there is, so the margins are mirrored.
        margin_left=round(min(lefts), 1), margin_right=round(min(lefts), 1),
        margin_top=round(min(tops), 1), margin_bottom=round(min(tops), 1),
        font_family=StyleProfile.family_for(font), body_size=body,
        heading_size=max(heading_sizes) if heading_sizes else round(body + 1.5, 1),
        name_size=largest, accent_color=f"#{colors.most_common(1)[0][0]:06X}" if colors else "#1F2937",
        columns=columns, source="original",
    )


def style_from_docx(data: bytes) -> StyleProfile:
    from docx import Document
    doc = Document(io.BytesIO(data))
    section = doc.sections[0] if doc.sections else None
    sizes: Counter = Counter()
    fonts: Counter = Counter()
    for p in doc.paragraphs:
        for r in p.runs:
            if r.text.strip():
                if r.font.size:
                    sizes[r.font.size.pt] += len(r.text)
                fonts[r.font.name or (p.style.font.name if p.style is not None else None) or "Calibri"] += len(r.text)
    base = StyleProfile.default()
    if section is None:
        return base
    pt = lambda emu: round(emu / 12700, 1) if emu else None  # noqa: E731 (EMU → points)
    return StyleProfile(
        page_width=pt(section.page_width) or base.page_width, page_height=pt(section.page_height) or base.page_height,
        margin_left=pt(section.left_margin) or base.margin_left, margin_right=pt(section.right_margin) or base.margin_right,
        margin_top=pt(section.top_margin) or base.margin_top, margin_bottom=pt(section.bottom_margin) or base.margin_bottom,
        font_family=StyleProfile.family_for(fonts.most_common(1)[0][0] if fonts else "Calibri"),
        body_size=sizes.most_common(1)[0][0] if sizes else base.body_size,
        heading_size=base.heading_size, name_size=max(sizes) if sizes else base.name_size,
        accent_color=base.accent_color, columns=1, source="original",
    )
