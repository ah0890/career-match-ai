"""The approval workflow: suggested changes and missing-information questions.

Only an accepted (or user-edited) recommendation ever changes a CV, and every change is
recorded as a revision. Recommendations that need a fact confirmed (``verification``) or that
carry a ``warning`` are never applied by "Accept all" — the user confirms each one.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cv.parsing import EMAIL_RE
from src.db.models import CVDoc, CVQuestion, CVRecommendation
from src.workspace import repository as repo
from src.workspace.document import CVDocument, Entry, Item
from src.workspace.importer import _parse_header
from src.workspace.repository import WorkspaceError
from src.workspace.review import QuestionSpec, Suggestion

PENDING, ACCEPTED, REJECTED, EDITED = "pending", "accepted", "rejected", "edited"
APPLIED_STATES = (ACCEPTED, EDITED)
STATUS_LABELS = {PENDING: "Pending", ACCEPTED: "Accepted", REJECTED: "Rejected", EDITED: "Edited by you",
                 "kept": "Noted"}


class StaleRecommendation(WorkspaceError):
    """The CV changed since the suggestion was made, so it no longer applies."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def payload(rec: CVRecommendation) -> dict:
    return json.loads(rec.payload_json) if rec.payload_json else {}


# --- storing ----------------------------------------------------------------------------------

def store(session: Session, doc: CVDoc, suggestions: list[Suggestion], *, source: str = "rules") -> str:
    """Save a run's suggestions. Pending suggestions of the same source from earlier runs are replaced;
    decided ones stay as history."""
    for old in session.scalars(select(CVRecommendation).where(
            CVRecommendation.doc_id == doc.id, CVRecommendation.source == source,
            CVRecommendation.status == PENDING)):
        session.delete(old)
    run_id = secrets.token_hex(6)
    decided = {(payload(r).get("key"), r.original) for r in recommendations(session, doc)
               if r.source == source and r.status != PENDING}
    for s in suggestions:
        if (s.key, s.original) in decided:  # already accepted or rejected — don't ask again
            continue
        data = dict(s.payload or {}, key=s.key)
        session.add(CVRecommendation(
            doc_id=doc.id, run_id=run_id, source=s.source or source, category=s.category, priority=s.priority,
            action=s.action, section_title=s.section_title[:160], section_id=s.section_id, entry_id=s.entry_id,
            item_id=s.item_id, original=s.original, proposed=s.proposed, explanation=s.explanation,
            benefit=s.benefit[:300], verification=(s.verification or None) and s.verification[:500],
            warnings=(s.warnings or None) and s.warnings[:500], payload_json=json.dumps(data, ensure_ascii=False),
            status=PENDING))
    session.flush()
    return run_id


def recommendations(session: Session, doc: CVDoc, *, status: str | None = None,
                    source: str | None = None) -> list[CVRecommendation]:
    query = select(CVRecommendation).where(CVRecommendation.doc_id == doc.id)
    if status:
        query = query.where(CVRecommendation.status == status)
    if source:
        query = query.where(CVRecommendation.source == source)
    order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(session.scalars(query), key=lambda r: (r.status != PENDING, order.get(r.priority, 3),
                                                         r.action == "advice", r.id))


def store_questions(session: Session, doc: CVDoc, questions: list[QuestionSpec]) -> None:
    """Add new questions; open questions that no longer apply are removed, answered ones are kept."""
    existing = {q.key: q for q in session.scalars(select(CVQuestion).where(CVQuestion.doc_id == doc.id))}
    keys = {q.key for q in questions}
    for key, q in existing.items():
        if q.status == "open" and key not in keys:
            session.delete(q)
    for q in questions:
        if q.key not in existing:
            session.add(CVQuestion(doc_id=doc.id, key=q.key[:120], question=q.question[:400], hint=q.hint[:300],
                                   essential=q.essential, target=q.target[:60], status="open"))
    session.flush()


def questions(session: Session, doc: CVDoc, *, status: str | None = None) -> list[CVQuestion]:
    query = select(CVQuestion).where(CVQuestion.doc_id == doc.id)
    if status:
        query = query.where(CVQuestion.status == status)
    return sorted(session.scalars(query), key=lambda q: (q.status != "open", not q.essential, q.id))


# --- applying one change ----------------------------------------------------------------------

def _apply(content: CVDocument, rec: CVRecommendation, text: str, provenance: str) -> None:
    data = payload(rec)
    if rec.action == "replace":
        found = content.find_item(rec.item_id or "")
        if found is None or found[2].text != rec.original:
            raise StaleRecommendation("This line changed after the suggestion was made, so it was not applied. "
                                      "Run the review again for fresh suggestions.")
        content.set_item_text(found[2].id, text, provenance)
    elif rec.action == "remove":
        found = content.find_item(rec.item_id or "")
        if found is None:
            raise StaleRecommendation("That line no longer exists.")
        found[2].hidden = True
    elif rec.action == "dates":
        found = content.find_entry(rec.entry_id or "")
        if found is None or found[1].dates != rec.original:
            raise StaleRecommendation("These dates changed after the suggestion was made.")
        found[1].dates = " ".join(text.split())
    elif rec.action == "add":
        kind = data.get("kind", "summary")
        section = content.ensure_section(kind, position=0 if kind == "summary" else None)
        if kind == "summary" and section.entries and any(i.text for e in section.entries for i in e.items):
            entry = section.entries[0]
            for item in entry.items:
                item.hidden = True  # the earlier summary stays restorable
            entry.items.append(Item(text=" ".join(text.split()), provenance=provenance))
        else:
            if not section.entries:
                section.entries.append(Entry(provenance=provenance))
            entry = section.entries[0]
            entry.items.append(Item(text=" ".join(text.split()), provenance=provenance))
        data["added_item"] = entry.items[-1].id
        rec.payload_json = json.dumps(data, ensure_ascii=False)
    elif rec.action == "reorder":
        _reorder(content, data)
    elif rec.action != "advice":
        raise WorkspaceError(f"Unknown change type: {rec.action}")


def _reorder(content: CVDocument, data: dict) -> None:
    order = data.get("order") or []
    if data.get("scope") == "sections":
        current = [s.id for s in content.sections]
        if sorted(current) != sorted(order):
            raise StaleRecommendation("The sections changed after the suggestion was made.")
        by_id = {s.id: s for s in content.sections}
        content.sections = [by_id[i] for i in order]
        return
    found = content.find_entry(data.get("entry_id", ""))
    if found is None:
        raise StaleRecommendation("That part of the CV no longer exists.")
    entry = found[1]
    if sorted(i.id for i in entry.items) != sorted(order):
        raise StaleRecommendation("These lines changed after the suggestion was made.")
    by_id = {i.id: i for i in entry.items}
    entry.items = [by_id[i] for i in order]


def _undo(content: CVDocument, rec: CVRecommendation) -> None:
    data = payload(rec)
    if rec.action == "replace":
        found = content.find_item(rec.item_id or "")
        if found is None or found[2].text != (rec.final_text or rec.proposed):
            raise StaleRecommendation("This line was edited since, so the change cannot be undone automatically.")
        content.set_item_text(found[2].id, rec.original, "extracted")
    elif rec.action == "remove":
        if (found := content.find_item(rec.item_id or "")) is not None:
            found[2].hidden = False
    elif rec.action == "dates":
        if (found := content.find_entry(rec.entry_id or "")) is not None:
            found[1].dates = rec.original
    elif rec.action == "add":
        added = data.get("added_item")
        for s in content.sections:
            for e in s.entries:
                before = len(e.items)
                e.items = [i for i in e.items if i.id != added]
                if len(e.items) != before and s.kind == "summary":
                    for i in e.items:
                        i.hidden = False
    elif rec.action == "reorder":
        undo = dict(data, order=data.get("previous_order") or [])
        if undo["order"]:
            _reorder(content, undo)


# --- decisions -------------------------------------------------------------------------------

def _get(session: Session, doc: CVDoc, rec_id: int) -> CVRecommendation:
    rec = session.get(CVRecommendation, rec_id)
    if rec is None or rec.doc_id != doc.id:
        raise WorkspaceError("That suggestion no longer exists.")
    return rec


def needs_confirmation(rec: CVRecommendation) -> bool:
    return bool(rec.verification or rec.warnings)


def _previous_order(content: CVDocument, rec: CVRecommendation) -> None:
    data = payload(rec)
    if rec.action != "reorder":
        return
    if data.get("scope") == "sections":
        data["previous_order"] = [s.id for s in content.sections]
    elif (found := content.find_entry(data.get("entry_id", ""))) is not None:
        data["previous_order"] = [i.id for i in found[1].items]
    rec.payload_json = json.dumps(data, ensure_ascii=False)


def decide(session: Session, doc: CVDoc, rec_id: int, decision: str, *, text: str | None = None,
           confirmed: bool = False) -> CVRecommendation:
    """Accept, edit, reject or undo one recommendation. Accepting/editing changes the CV (a new revision)."""
    if doc.role == "master":
        raise WorkspaceError("The original master CV is never changed — work on the Revised Master CV instead.")
    rec = _get(session, doc, rec_id)
    content = repo.load(doc)
    if decision == "reject":
        if rec.status in APPLIED_STATES:
            raise WorkspaceError("Undo this change first.")
        rec.status, rec.decided_at = REJECTED, _now()
        return rec
    if decision == "undo":
        if rec.status in APPLIED_STATES:
            _undo(content, rec)
            repo.save(session, doc, content, revision=("review", f"Undid: {rec.category} change"[:300]))
        rec.status, rec.final_text, rec.decided_at = PENDING, None, None
        return rec
    if decision not in ("accept", "edit"):
        raise WorkspaceError(f"Unknown decision: {decision}")
    if rec.status != PENDING:
        raise WorkspaceError("This suggestion was already decided. Undo it first to change your decision.")
    if rec.action == "advice":
        rec.status, rec.decided_at = "kept", _now()
        return rec
    final = rec.proposed
    if decision == "edit":
        final = " ".join((text or "").split())
        if not final and rec.action not in ("remove", "reorder"):
            raise WorkspaceError("Write the text you want to use, or reject the suggestion.")
    if needs_confirmation(rec) and not confirmed and decision == "accept":
        raise WorkspaceError("Confirm that this change is accurate before accepting it.")
    _previous_order(content, rec)
    _apply(content, rec, final, "edited" if decision == "edit" else "suggested")
    rec.status = EDITED if decision == "edit" else ACCEPTED
    rec.final_text = final if decision == "edit" else None
    rec.decided_at = _now()
    repo.save(session, doc, content, revision=("review", f"{'Edited' if decision == 'edit' else 'Accepted'}: "
                                                         f"{rec.section_title}"[:300]))
    return rec


@dataclass(frozen=True)
class BulkResult:
    applied: int
    needs_confirmation: int  # left pending: they need the user to confirm a fact
    stale: int


def accept_all(session: Session, doc: CVDoc, rec_ids: list[int] | None = None) -> BulkResult:
    """Accept every pending change that needs no confirmation, as one revision."""
    if doc.role == "master":
        raise WorkspaceError("The original master CV is never changed — work on the Revised Master CV instead.")
    content = repo.load(doc)
    applied = confirm = stale = 0
    for rec in recommendations(session, doc, status=PENDING):
        if rec_ids is not None and rec.id not in rec_ids:
            continue
        if rec.action == "advice":
            continue
        if needs_confirmation(rec):
            confirm += 1
            continue
        try:
            _previous_order(content, rec)
            _apply(content, rec, rec.proposed, "suggested")
        except StaleRecommendation:
            stale += 1
            continue
        rec.status, rec.decided_at = ACCEPTED, _now()
        applied += 1
    if applied:
        repo.save(session, doc, content, revision=("review", f"Accepted {applied} suggested change(s)"))
    return BulkResult(applied, confirm, stale)


def reject_all(session: Session, doc: CVDoc, rec_ids: list[int] | None = None) -> int:
    """Reject every pending change (advice stays visible until noted one by one)."""
    n = 0
    for rec in recommendations(session, doc, status=PENDING):
        if rec.action != "advice" and (rec_ids is None or rec.id in rec_ids):
            rec.status, rec.decided_at = REJECTED, _now()
            n += 1
    return n


def restore_section(session: Session, doc: CVDoc, section_id: str) -> None:
    """Bring a section back to how it was when this CV was created (its first revision)."""
    first = next(iter(doc.revisions), None)
    if first is None:
        raise WorkspaceError("This CV has no history yet.")
    original = repo.load(first).find_section(section_id)
    content = repo.load(doc)
    current = content.find_section(section_id)
    if original is None or current is None:
        raise WorkspaceError("This section did not exist when the CV was created, so there is nothing to restore.")
    content.sections[content.sections.index(current)] = original
    ids = {i.id for e in original.entries for i in e.items} | {e.id for e in original.entries} | {section_id}
    for rec in recommendations(session, doc):
        if rec.status in APPLIED_STATES and ({rec.item_id, rec.entry_id, rec.section_id} & ids):
            rec.status, rec.final_text, rec.decided_at = PENDING, None, None
    repo.save(session, doc, content, revision=("restore", f"Restored the original {original.title} section"))


def counts(session: Session, doc: CVDoc) -> dict[str, int]:
    out = {PENDING: 0, ACCEPTED: 0, REJECTED: 0, EDITED: 0, "kept": 0}
    for rec in recommendations(session, doc):
        out[rec.status] = out.get(rec.status, 0) + 1
    return out


# --- questions -------------------------------------------------------------------------------

def _answer_into(content: CVDocument, target: str, answer: str) -> None:
    answer = answer.strip()
    lines = [" ".join(line.lstrip("-•* ").split()) for line in answer.splitlines() if line.strip()]
    single = " ".join(answer.split())
    if target.startswith("contact."):
        field = target.split(".", 1)[1]
        if field == "email" and not EMAIL_RE.fullmatch(single):
            raise WorkspaceError("That does not look like an email address.")
        if field == "links":
            content.contact.links = [*content.contact.links, single][:6]
        elif field in ("name", "email", "phone", "location", "headline"):
            setattr(content.contact, field, single[:200])
        content.contact.provenance = "edited"
        return
    kind, _, rest = target.partition(":")
    if kind == "entry":
        entry_id, _, what = rest.partition(":")
        found = content.find_entry(entry_id)
        if found is None:
            raise WorkspaceError("That part of the CV no longer exists.")
        if what == "dates":
            found[1].dates = single[:80]
        else:
            found[1].items += [Item(text=t, provenance="edited") for t in lines]
        return
    if kind == "item":
        found = content.find_item(rest)
        if found is None:
            raise WorkspaceError("That line no longer exists.")
        content.set_item_text(rest, single, "edited")
        return
    if kind == "section":
        section = content.ensure_section(rest, position=0 if rest == "summary" else None)
        if rest == "skills":
            items = [Item(text=t.strip(), provenance="edited") for t in single.replace(";", ",").split(",") if t.strip()]
            if not section.entries:
                section.entries.append(Entry(provenance="edited"))
            section.entries[0].items += items
        elif rest == "education":
            for line in lines:
                entry = _parse_header(line)
                entry.provenance = "edited"
                section.entries.append(entry)
        else:
            if not section.entries:
                section.entries.append(Entry(provenance="edited"))
            for item in section.entries[0].items:
                item.hidden = True
            section.entries[0].items.append(Item(text=single, provenance="edited"))
        return
    raise WorkspaceError("This question cannot be answered here.")


def answer(session: Session, doc: CVDoc, question_id: int, text: str, *, also_revised_master: bool = False) -> None:
    """Use the user's answer in this CV (and optionally in the Revised Master CV too)."""
    q = session.get(CVQuestion, question_id)
    if q is None or q.doc_id != doc.id:
        raise WorkspaceError("That question no longer exists.")
    if not text.strip():
        raise WorkspaceError("Write an answer, or skip the question.")
    content = repo.load(doc)
    _answer_into(content, q.target, text)
    repo.save(session, doc, content, revision=("answers", f"Answered: {q.question}"[:300]))
    q.answer, q.status, q.answered_at = text.strip()[:5000], "answered", _now()
    if also_revised_master and doc.role == "version":
        master = repo.working_master(session)
        content = repo.load(master)
        try:
            _answer_into(content, q.target, text)
        except WorkspaceError:
            return  # the line exists only in this version
        repo.save(session, master, content, revision=("answers", f"From {doc.name}: {q.question}"[:300]))
        q.added_to_master = True


def skip(session: Session, doc: CVDoc, question_id: int) -> None:
    q = session.get(CVQuestion, question_id)
    if q is not None and q.doc_id == doc.id:
        q.status = "skipped"


def reopen(session: Session, doc: CVDoc, question_id: int) -> None:
    q = session.get(CVQuestion, question_id)
    if q is not None and q.doc_id == doc.id and q.status == "skipped":
        q.status = "open"
