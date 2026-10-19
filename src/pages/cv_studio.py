"""CV Studio — upload, review, improve, tailor and export your CV. Every change is approved by you."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape

import streamlit as st
from sqlalchemy import select

from config.settings import get_settings
from src.cv.extraction import CVError, ExtractionResult
from src.cv.session import ActiveCV, process_upload, set_active_cv
from src.db.engine import session_scope
from src.db.models import CVFile, CVQuestion, CVRecommendation, CVSource, CVVersion
from src.jobs.models import JobPosting
from src.pages.find_jobs import OUTCOME_KEY
from src.services.matching import clear_matches
from src.tracker.repository import (
    ApplicationInput, TrackerError, add_manual, find_by_job, list_applications, save_job, set_status,
)
from src.ui.components import Feature, badge_html, feature_grid, key_value, notice, page_header, section_header
from src.ui.score_components import Bar, bars_html, chips_html, score_card_html
from src.ui.studio_view import (
    PROVENANCE_LABELS, before_after_html, changes_html, checks_html, rec_badges_html, workflow_html,
)
from src.workspace import ai, approval, exports, ocr
from src.workspace import repository as repo
from src.workspace.document import DEFAULT_TITLES, ENTRY_KINDS, INLINE_KINDS, CVDocument, Entry, Item
from src.workspace.importer import import_text
from src.workspace.render import preview_png, render_pdf, validate_pdf
from src.workspace.repository import WorkspaceError
from src.workspace.review import review
from src.workspace.style import PAGE_SIZES, TEMPLATE_LABELS, FormatSettings
from src.workspace.tailoring import job_posting, score, tailor

PREFILL_KEY = "cs_prefill_job"  # a JobPosting set by Job Matches ("Tailor CV")
_DOC = "cs_doc"
_NEXT_DOC = "cs_doc_next"
_FLASH = "cs_flash"
_EXPORT = "cs_export"
_PREVIEW = "cs_preview"
_PENDING = "cs_pending_upload"
_UPLOAD_GEN = "cs_upload_gen"
_AI_FEEDBACK = "cs_ai_feedback"
_PAGE_SIZE = 25

_FEATURES = [
    Feature("Your original stays untouched", "The CV you upload becomes your Original Master CV. It never changes; "
            "improvements go to a Revised Master CV and job-specific versions."),
    Feature("Review and scores", "Category scores out of 100 and concrete suggestions, each with the reason and the "
            "benefit. Scores are guidance, not a prediction of hiring success."),
    Feature("You approve every change", "Accept, edit or reject each suggestion. Nothing is invented: missing facts "
            "become questions for you."),
    Feature("PDF and Word", "Professional, ATS-friendly PDF and fully editable DOCX in several templates — checked "
            "after generation before you download."),
]


# --- small helpers -------------------------------------------------------------------------------

def _db() -> str:
    return get_settings().database_url


def _flash(message: str) -> None:
    st.session_state[_FLASH] = message


def _date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d %b %Y, %H:%M")


@dataclass(frozen=True)
class DocInfo:
    id: int
    role: str
    label: str
    name: str
    status: str
    target_title: str | None
    target_company: str | None
    job_description: str | None
    job_key: str | None
    parent_id: int | None
    parent_revision: int | None
    source_id: int | None
    created_at: datetime
    updated_at: datetime
    revisions: int

    @property
    def editable(self) -> bool:
        return self.role != "master"


def _info(s, d) -> DocInfo:
    return DocInfo(d.id, d.role, repo.label(d), d.name, d.status, d.target_title, d.target_company, d.job_description,
                   d.job_key, d.parent_id, d.parent_revision, d.source_id, d.created_at, d.updated_at,
                   len(d.revisions))


def _docs(include_archived: bool = False) -> list[DocInfo]:
    with session_scope(_db()) as s:
        return [_info(s, d) for d in repo.list_docs(s, include_archived)]


def _content(doc_id: int) -> CVDocument:
    with session_scope(_db()) as s:
        return repo.load(repo.get_doc(s, doc_id))


def _act(fn, success: str | None = None) -> bool:
    """Run a database action; show user-safe errors; flash and rerun on success."""
    try:
        with session_scope(_db()) as s:
            fn(s)
    except (WorkspaceError, TrackerError, CVError) as exc:
        st.error(str(exc), icon=":material/error:")
        return False
    if success:
        _flash(success)
    st.rerun()
    return True


def _select(doc_id: int) -> None:
    """Open another CV on the next run (the selector widget owns ``_DOC`` once drawn)."""
    st.session_state[_NEXT_DOC] = doc_id


# --- upload ------------------------------------------------------------------------------------

def _upload_panel(*, replacing: bool) -> None:
    settings = get_settings()
    gen = st.session_state.get(_UPLOAD_GEN, 0)
    uploaded = st.file_uploader(
        "Upload a new CV" if replacing else "Upload your CV", type=["pdf", "docx"], key=f"cs_upload_{gen}",
        help=f"PDF or DOCX, up to {settings.max_upload_mb:g} MB.", max_upload_size=max(1, math.ceil(settings.max_upload_mb)))
    keep = st.checkbox("Keep an encrypted copy of my original file on this computer", value=True, key=f"cs_keep_{gen}",
                       help="Lets you download the exact file you uploaded later. Without it, only the extracted "
                            "text is kept. The copy is encrypted with a key held in your operating system's "
                            "credential store.")
    if replacing:
        st.caption("Uploading a new CV makes it your Original Master CV. The previous one is archived, not deleted, "
                   "and CVs made from it keep working.")
    if uploaded is not None:
        st.session_state[_PENDING] = (uploaded.name, uploaded.getvalue(), keep)
    pending = st.session_state.get(_PENDING)
    if not pending:
        return
    name, data, keep = pending
    try:
        checked = process_upload(name, data, settings.max_upload_bytes)
    except CVError as exc:
        st.error(str(exc), icon=":material/error:")
        st.session_state.pop(_PENDING, None)
        return
    ocr_text = None
    if checked.extraction.needs_ocr:
        if not ocr.available():
            notice(ocr.OCR_HELP, tone="warning", title="This looks like a scanned document.")
            return
        notice("This looks like a scanned document, so its text has to be read with OCR (on this computer). "
               "OCR can misread characters — check the result carefully.", tone="warning")
        if not st.button("Read the text with OCR", icon=":material/document_scanner:", key="cs_ocr"):
            return
        with st.spinner("Reading the scanned pages…"):
            try:
                ocr_text = ocr.ocr_pdf(data)
            except ocr.OCRUnavailable as exc:
                st.error(str(exc), icon=":material/error:")
                return
    words = len((ocr_text or checked.extraction.text).split())
    with st.spinner("Reading and structuring your CV…"):
        try:
            with session_scope(_db()) as s:
                source = repo.import_source(s, name, data, max_bytes=settings.max_upload_bytes, ocr_text=ocr_text,
                                            keep_file=keep)
                master = repo.create_master(s, source)
                new_id = master.id
        except (CVError, WorkspaceError) as exc:
            st.error(str(exc), icon=":material/error:")
            return
    text = ocr_text or checked.extraction.text
    set_active_cv(st.session_state, ActiveCV(checked.filename, checked.size_bytes, checked.sha256,
                                             checked.uploaded_at, ExtractionResult(text, checked.extraction.kind,
                                                                                   checked.extraction.page_count)))
    clear_matches(st.session_state)
    st.session_state.pop(_PENDING, None)
    st.session_state[_UPLOAD_GEN] = gen + 1
    _select(new_id)
    quality = "" if words >= 150 else (" Only a little text could be read — check the structure on the Master CV tab "
                                       "and fix anything that is missing in the Revised Master CV.")
    _flash(f"Imported {checked.filename} as your Original Master CV.{quality}")
    st.rerun()


def _legacy_import() -> None:
    with session_scope(_db()) as s:
        legacy = [(v.id, v.name, v.text) for v in s.scalars(select(CVVersion).order_by(CVVersion.created_at.desc()))]
    if not legacy:
        return
    with st.expander("Use a CV you saved earlier", icon=":material/history:"):
        st.caption("Earlier versions of the app saved CV text only. Pick one to make it your Original Master CV.")
        choice = st.selectbox("Saved CV", [v[0] for v in legacy], key="cs_legacy",
                              format_func=lambda i: next(v[1] for v in legacy if v[0] == i))
        if st.button("Use this CV", key="cs_legacy_use"):
            text = next(v[2] for v in legacy if v[0] == choice)
            _act(lambda s: _select(repo.create_master(s, None, import_text(text)).id),
                 "Imported your saved CV as the Original Master CV.")


# --- previews ------------------------------------------------------------------------------------

def cv_html(content: CVDocument, *, show_provenance: bool = False) -> str:
    """A readable, escaped rendering of a structured CV for the page."""
    c = content.contact
    out = [f'<div class="cm-card cm-cv-preview"><h3>{escape(c.name or "Name not found")}</h3>']
    if c.headline:
        out.append(f"<p><strong>{escape(c.headline)}</strong></p>")
    contact = " · ".join(escape(x) for x in (c.email, c.phone, c.location, *c.links) if x)
    out.append(f'<p class="cm-muted">{contact or "No contact details found"}</p>')
    for s in content.sections:
        if s.hidden:
            continue
        out.append(f"<h4>{escape(s.title)}</h4>")
        for e in s.entries:
            if e.hidden:
                continue
            items = [i for i in e.items if not i.hidden]
            if s.kind in INLINE_KINDS:
                out.append(f"<p>{escape(', '.join(i.text for i in items))}</p>")
                continue
            if e.header:
                out.append(f"<p><strong>{escape(e.header)}</strong></p>")
            if items:
                lis = []
                for i in items:
                    tag = (f' <span class="cm-muted">({escape(PROVENANCE_LABELS[i.provenance])})</span>'
                           if show_provenance and i.provenance != "extracted" else "")
                    lis.append(f"<li>{escape(i.text)}{tag}</li>")
                out.append("<ul>" + "".join(lis) + "</ul>")
    out.append("</div>")
    return "".join(out)


# --- tabs ------------------------------------------------------------------------------------------

def _tab_master(master: DocInfo) -> None:
    with session_scope(_db()) as s:
        doc = repo.get_doc(s, master.id)
        source = s.get(CVSource, doc.source_id) if doc.source_id else None
        info = None
        if source is not None:
            info = (source.filename, source.kind, source.size_bytes, source.page_count, source.imported_at,
                    bool(source.blob), source.needs_ocr, source.id)
        content = repo.load(doc)
    st.html(f'<div class="cm-badge-row">{badge_html("Original Master CV", "info")}'
            f'{badge_html("Read-only — never changed", "neutral")}</div>')
    if info:
        filename, kind, size, pages, imported, has_file, needs_ocr, source_id = info
        rows = [("File", filename), ("Type", kind.upper()), ("Size", f"{size / 1024:.0f} KB"),
                ("Imported", _date(imported))]
        if pages:
            rows.append(("Pages", str(pages)))
        rows.append(("Original file", "Kept, encrypted" if has_file else "Not kept (text only)"))
        key_value(rows)
        if has_file:
            c1, c2, _ = st.columns([1, 1, 2])
            with session_scope(_db()) as s:
                data = repo.source_bytes(s.get(CVSource, source_id))
            c1.download_button("Download original", data, file_name=filename, icon=":material/download:",
                               key="cs_orig_dl", on_click="ignore", width="stretch")
            if c2.button("Delete stored original", icon=":material/delete:", key="cs_orig_del", width="stretch",
                         help="Removes the encrypted copy of the file. Your CVs and their text stay."):
                _act(lambda s: repo.delete_source_file(s, source_id), "The stored original file was deleted.")
    words = content.word_count()
    if words < 150:
        notice(f"Only about {words} words could be read from your file. Some content may be missing — compare it "
               "with your original and add anything missing in the Revised Master CV.", tone="warning",
               title="Check the extraction.")
    section_header("What was read from your CV", "Headings, roles, dates and bullets as the app understood them.")
    st.html(cv_html(content))
    c1, c2 = st.columns(2)
    if c1.button("Improve this CV", type="primary", icon=":material/auto_fix_high:", key="cs_start_revised",
                 width="stretch", help="Opens your Revised Master CV, where reviewed and approved changes go."):
        _act(lambda s: _select(repo.working_master(s).id))
    with c2.popover("Replace with a new upload", icon=":material/upload_file:", width="stretch"):
        _upload_panel(replacing=True)


def _scores(content: CVDocument, roles: list[str]) -> None:
    report = review(content, roles)
    a, b = st.columns([1, 2])
    a.html(score_card_html(report.score, report.band, "Overall CV score", report.note))
    bars = [Bar(c.label, c.score, 100, "; ".join(c.findings) or None) for c in report.categories if c.score is not None]
    b.html(bars_html(bars))
    skipped = [c.label for c in report.categories if c.score is None]
    if skipped:
        st.caption("Not assessed: " + ", ".join(skipped) + " — add your target roles to include it.")


def _tab_review(doc: DocInfo) -> None:
    settings = get_settings()
    content = _content(doc.id)
    default_roles = doc.target_title or content.contact.headline or ""
    roles_text = st.text_input("Target roles (comma-separated)", value=default_roles, key=f"cs_roles_{doc.id}",
                               max_chars=300, help="Used for the relevance score and advice.")
    roles = [r.strip() for r in roles_text.split(",") if r.strip()]
    _scores(content, roles)
    if not doc.editable:
        notice("Your Original Master CV never changes. Suggested changes are made to your Revised Master CV, which "
               "starts as an exact copy.", tone="info")
        if st.button("Review and improve as a Revised Master CV", type="primary", icon=":material/auto_fix_high:",
                     key="cs_review_start"):
            _act(lambda s: _select(repo.working_master(s).id))
        return
    c1, c2 = st.columns(2)
    if c1.button("Find suggested changes", type="primary", icon=":material/rule:", key=f"cs_run_{doc.id}",
                 width="stretch"):
        with st.spinner("Reviewing your CV…"):
            def run(s):
                d = repo.get_doc(s, doc.id)
                report = review(repo.load(d), roles)
                approval.store(s, d, report.suggestions)
                approval.store_questions(s, d, report.questions)
            _act(run, "Review finished — see Recommended changes and Missing information.")
    with c2:
        if ai.available(settings):
            with st.popover("Ask Claude for suggestions", icon=":material/psychology:", width="stretch"):
                st.caption(ai.DATA_NOTICE)
                consent = st.checkbox("Send my CV text (without contact details) to Anthropic for this review",
                                      key=f"cs_ai_ok_{doc.id}")
                if st.button("Get Claude's suggestions", disabled=not consent, key=f"cs_ai_run_{doc.id}",
                             type="primary"):
                    with st.spinner("Claude is reviewing your CV — this can take a minute…"):
                        try:
                            feedback, suggestions, cost = ai.review_with_claude(content, settings, target_roles=tuple(roles))
                        except ai.AIError as exc:
                            st.error(f"{exc} The built-in suggestions still work.", icon=":material/error:")
                        else:
                            st.session_state[_AI_FEEDBACK] = (doc.id, feedback, cost)
                            _act(lambda s: approval.store(s, repo.get_doc(s, doc.id), suggestions, source="claude"),
                                 f"Claude suggested {len(suggestions)} change(s) — review them under Recommended "
                                 "changes.")
        else:
            st.caption("To also get suggestions from Claude, add ANTHROPIC_API_KEY to your .env file and restart "
                       "the app. The built-in review works without it.")
    fb = st.session_state.get(_AI_FEEDBACK)
    if fb and fb[0] == doc.id:
        notice(fb[1], tone="info", title="Claude's overall feedback:")
        st.caption(fb[2])


def _rec_actions(doc: DocInfo, rec: CVRecommendation) -> None:
    key = f"cs_rec_{rec.id}"
    if rec.status != "pending":
        label = "Undo" if rec.status in ("accepted", "edited") else "Reconsider"
        if st.button(label, key=f"{key}_undo", icon=":material/undo:"):
            _act(lambda s: approval.decide(s, repo.get_doc(s, doc.id), rec.id, "undo"),
                 "Change undone." if label == "Undo" else "Moved back to pending.")
        return
    if rec.action == "advice":
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Noted", key=f"{key}_note", icon=":material/check:", width="stretch"):
            _act(lambda s: approval.decide(s, repo.get_doc(s, doc.id), rec.id, "accept"))
        if c2.button("Dismiss", key=f"{key}_rej", width="stretch"):
            _act(lambda s: approval.decide(s, repo.get_doc(s, doc.id), rec.id, "reject"))
        return
    confirmed = True
    if approval.needs_confirmation(rec):
        confirmed = st.checkbox(rec.verification or "I confirm this change is accurate", key=f"{key}_ok")
    c1, c2, c3, _ = st.columns([1, 1, 1, 2])
    if c1.button("Accept", key=f"{key}_acc", type="primary", icon=":material/check:", width="stretch",
                 disabled=not confirmed):
        _act(lambda s: approval.decide(s, repo.get_doc(s, doc.id), rec.id, "accept", confirmed=confirmed),
             "Change accepted.")
    if rec.action in ("replace", "add", "dates"):
        with c2.popover("Edit", icon=":material/edit:", width="stretch"):
            text = st.text_area("Your version", value=rec.proposed, key=f"{key}_text", height=120)
            if st.button("Use my version", key=f"{key}_edit", type="primary"):
                _act(lambda s: approval.decide(s, repo.get_doc(s, doc.id), rec.id, "edit", text=text),
                     "Your version was applied.")
    if c3.button("Reject", key=f"{key}_rej", icon=":material/close:", width="stretch"):
        _act(lambda s: approval.decide(s, repo.get_doc(s, doc.id), rec.id, "reject"), "Suggestion rejected.")


def _rec_list(doc: DocInfo, sources: tuple[str, ...] | None, key: str) -> None:
    with session_scope(_db()) as s:
        recs = [r for r in approval.recommendations(s, repo.get_doc(s, doc.id))
                if sources is None or r.source in sources]
    if not recs:
        st.caption("No suggestions yet." if sources != ("tailoring", "claude") else
                   "No job-specific suggestions yet.")
        return
    counts = {k: sum(r.status == k for r in recs) for k in ("pending", "accepted", "edited", "rejected", "kept")}
    st.html('<div class="cm-badge-row">' + "".join(
        badge_html(f"{n} {approval.STATUS_LABELS[k].lower()}", tone) for k, n, tone in (
            ("pending", counts["pending"], "info"), ("accepted", counts["accepted"], "success"),
            ("edited", counts["edited"], "success"), ("rejected", counts["rejected"], "neutral"),
            ("kept", counts["kept"], "neutral")) if n) + "</div>")
    view = st.segmented_control("Show", ["Pending", "Accepted", "Edited", "Rejected", "All"], default="Pending",
                                key=f"{key}_filter")
    wanted = {"Pending": ("pending",), "Accepted": ("accepted", "kept"), "Edited": ("edited",),
              "Rejected": ("rejected",)}.get(view or "All")
    shown = [r for r in recs if wanted is None or r.status in wanted]
    pending_changes = [r.id for r in recs if r.status == "pending" and r.action != "advice"]
    if doc.editable and pending_changes and view in ("Pending", "All", None):
        b1, b2, _ = st.columns([1.3, 1, 2])
        if b1.button(f"Accept all safe changes ({len(pending_changes)})", key=f"{key}_all", icon=":material/done_all:",
                     width="stretch", help="Changes that need you to confirm a fact are left for you to check."):
            def run(s):
                result = approval.accept_all(s, repo.get_doc(s, doc.id), pending_changes)
                _flash(f"Accepted {result.applied} change(s)."
                       + (f" {result.needs_confirmation} need your confirmation first." if result.needs_confirmation
                          else "") + (f" {result.stale} no longer applied." if result.stale else ""))
            _act(run)
        if b2.button("Reject all", key=f"{key}_none", width="stretch"):
            _act(lambda s: approval.reject_all(s, repo.get_doc(s, doc.id), pending_changes),
                 "All pending changes rejected.")
    limit = st.session_state.get(f"{key}_limit", _PAGE_SIZE)
    for rec in shown[:limit]:
        with st.container(border=True):
            st.html(rec_badges_html(status=rec.status, status_label=approval.STATUS_LABELS.get(rec.status, rec.status),
                                    priority=rec.priority, category=rec.category, source=rec.source))
            st.markdown(f"**{escape(rec.section_title)}**")
            if rec.action == "advice":
                st.write(rec.explanation)
                if rec.original:
                    st.caption("About: " + rec.original[:300])
            else:
                after = rec.final_text if rec.status == "edited" else rec.proposed
                labels = ("Current order", "Suggested order") if rec.action == "reorder" else ("Current", "Suggested")
                if rec.action == "remove":
                    labels = ("Current", "Leave out of this CV")
                st.html(before_after_html(rec.original, after or ("(left out — can be brought back)"
                                                                  if rec.action == "remove" else ""),
                                          before_label=labels[0], after_label=labels[1]))
                st.write(rec.explanation)
            st.caption(f"Why it helps: {rec.benefit}")
            if rec.warnings:
                notice(rec.warnings, tone="warning", title="Check before accepting:")
            if doc.editable:
                _rec_actions(doc, rec)
    if len(shown) > limit:
        if st.button(f"Show more ({len(shown) - limit} left)", key=f"{key}_more"):
            st.session_state[f"{key}_limit"] = limit + _PAGE_SIZE
            st.rerun()


def _tab_changes(doc: DocInfo) -> None:
    if not doc.editable:
        notice("Changes are never made to the Original Master CV. Open your Revised Master CV (Review tab) or a "
               "tailored CV to review suggested changes.", tone="info")
        return
    _rec_list(doc, None, f"cs_all_{doc.id}")


def _tab_questions(doc: DocInfo) -> None:
    if not doc.editable:
        notice("Questions are answered in your Revised Master CV or a tailored CV — the original never changes.",
               tone="info")
        return
    with session_scope(_db()) as s:
        qs = approval.questions(s, repo.get_doc(s, doc.id))
    open_qs = [q for q in qs if q.status == "open"]
    if not qs:
        st.caption("No questions yet. Run the review to find missing information.")
        return
    st.caption("Answer what applies to you. Anything you skip stays out of your CV — it is never filled in for you.")
    for q in open_qs:
        with st.container(border=True):
            st.html('<div class="cm-badge-row">' + badge_html("Essential" if q.essential else "Optional",
                                                              "warning" if q.essential else "neutral") + "</div>")
            st.markdown(f"**{escape(q.question)}**")
            if q.hint:
                st.caption(q.hint)
            multi = q.target.endswith(":add") or q.target.startswith(("item:", "section:"))
            widget = st.text_area if multi else st.text_input
            answer = widget("Your answer", key=f"cs_q_{q.id}", label_visibility="collapsed")
            also = False
            if doc.role == "version":
                also = st.checkbox("Also add this to my Revised Master CV", key=f"cs_q_master_{q.id}")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Save answer", key=f"cs_q_save_{q.id}", type="primary", width="stretch"):
                _act(lambda s: approval.answer(s, repo.get_doc(s, doc.id), q.id, answer, also_revised_master=also),
                     "Answer added to your CV.")
            if c2.button("Skip", key=f"cs_q_skip_{q.id}", width="stretch"):
                _act(lambda s: approval.skip(s, repo.get_doc(s, doc.id), q.id))
    done = [q for q in qs if q.status != "open"]
    if done:
        with st.expander(f"Answered or skipped ({len(done)})"):
            for q in done:
                st.markdown(f"**{escape(q.question)}** — {'skipped' if q.status == 'skipped' else 'answered'}")
                if q.answer:
                    st.caption(q.answer[:300])
                if q.status == "skipped" and st.button("Answer after all", key=f"cs_q_reopen_{q.id}"):
                    _act(lambda s, qid=q.id: approval.reopen(s, repo.get_doc(s, doc.id), qid))


def _save_section(doc_id: int, section_id: str, title: str, hidden: bool, entries: list[dict]) -> None:
    def run(s):
        d = repo.get_doc(s, doc_id)
        content = repo.load(d)
        section = content.find_section(section_id)
        if section is None:
            raise WorkspaceError("That section no longer exists.")
        section.title = " ".join(title.split())[:80] or section.title
        section.hidden = hidden
        for data in entries:
            found = content.find_entry(data["id"])
            if found is None:
                continue
            entry = found[1]
            for field in ("title", "organization", "location", "dates"):
                value = " ".join((data.get(field) or "").split())
                if value != getattr(entry, field):
                    setattr(entry, field, value)
                    entry.provenance = "edited"
            entry.hidden = not data["include"]
            lines = [" ".join(x.lstrip("-•* ").split()) for x in data["lines"].splitlines() if x.strip()]
            visible = [i for i in entry.items if not i.hidden]
            hidden_items = [i for i in entry.items if i.hidden]
            by_text: dict[str, list[Item]] = {}
            for i in visible:
                by_text.setdefault(i.text, []).append(i)
            new_items = []
            for n, line in enumerate(lines):
                if by_text.get(line):
                    new_items.append(by_text[line].pop(0))
                elif n < len(visible) and visible[n].text not in lines:
                    item = visible[n]
                    item.text, item.provenance = line, "edited"
                    new_items.append(item)
                else:
                    new_items.append(Item(text=line, provenance="edited"))
            entry.items = new_items + hidden_items
        repo.save(s, d, content, revision=("edit", f"Edited {section.title}"))
    _act(run, "Section saved.")


def _tab_edit(doc: DocInfo) -> None:
    if not doc.editable:
        notice("The Original Master CV is read-only. Edit your Revised Master CV or a tailored CV instead.", tone="info")
        if st.button("Open my Revised Master CV", key="cs_edit_open", icon=":material/edit:"):
            _act(lambda s: _select(repo.working_master(s).id))
        return
    content = _content(doc.id)
    st.caption("Edit freely — your changes are saved as a new revision, and you can restore any earlier one from "
               "Version history.")
    with st.expander("Contact details", icon=":material/badge:"):
        with st.form(f"cs_contact_{doc.id}", border=False):
            c = content.contact
            a, b = st.columns(2)
            name = a.text_input("Full name", c.name, max_chars=120)
            headline = b.text_input("Headline (professional title)", c.headline, max_chars=160)
            email = a.text_input("Email", c.email, max_chars=254)
            phone = b.text_input("Phone", c.phone, max_chars=60)
            location = a.text_input("Location", c.location, max_chars=120)
            links = b.text_area("Links (one per line)", "\n".join(c.links), height=80)
            if st.form_submit_button("Save contact details", type="primary"):
                def run(s):
                    d = repo.get_doc(s, doc.id)
                    new = repo.load(d)
                    new.contact = new.contact.model_copy(update={
                        "name": " ".join(name.split()), "headline": " ".join(headline.split()),
                        "email": email.strip(), "phone": " ".join(phone.split()), "location": " ".join(location.split()),
                        "links": [x.strip() for x in links.splitlines() if x.strip()][:6], "provenance": "edited"})
                    repo.save(s, d, new, revision=("edit", "Edited contact details"))
                _act(run, "Contact details saved.")
        if doc.role == "version" and st.button("Copy contact details from my master CV", key=f"cs_contact_copy_{doc.id}"):
            _act(lambda s: repo.update_contact_from_master(s, repo.get_doc(s, doc.id)), "Contact details updated.")
    for n, section in enumerate(content.sections):
        title = section.title + (" (hidden)" if section.hidden else "")
        with st.expander(title, icon=":material/segment:"):
            m1, m2, m3, m4 = st.columns(4)
            if m1.button("Move up", key=f"cs_up_{section.id}", disabled=n == 0, width="stretch"):
                _act(lambda s, sid=section.id: _move(s, doc.id, sid, -1))
            if m2.button("Move down", key=f"cs_down_{section.id}", disabled=n == len(content.sections) - 1,
                         width="stretch"):
                _act(lambda s, sid=section.id: _move(s, doc.id, sid, 1))
            if m3.button("Add entry", key=f"cs_addentry_{section.id}", width="stretch"):
                _act(lambda s, sid=section.id: _add_entry(s, doc.id, sid))
            if m4.button("Restore original", key=f"cs_restore_{section.id}", width="stretch",
                         help="Bring this section back to how it was when this CV was created."):
                _act(lambda s, sid=section.id: approval.restore_section(s, repo.get_doc(s, doc.id), sid),
                     "Section restored. Changes accepted in it are pending again.")
            with st.form(f"cs_sec_{section.id}", border=False):
                stitle = st.text_input("Section heading", section.title, max_chars=80)
                hide = st.checkbox("Leave this section out of this CV", section.hidden)
                entries = []
                for e in section.entries:
                    st.divider()
                    data = {"id": e.id}
                    if section.kind in ENTRY_KINDS or section.kind == "custom" or e.title:
                        a, b = st.columns(2)
                        data["title"] = a.text_input("Title", e.title, key=f"cs_et_{e.id}", max_chars=200)
                        data["organization"] = b.text_input("Organisation", e.organization, key=f"cs_eo_{e.id}",
                                                            max_chars=200)
                        data["location"] = a.text_input("Location", e.location, key=f"cs_el_{e.id}", max_chars=120)
                        data["dates"] = b.text_input("Dates", e.dates, key=f"cs_ed_{e.id}", max_chars=80)
                    label = "One item per line" if section.kind in INLINE_KINDS else "One line or bullet per line"
                    data["lines"] = st.text_area(label, "\n".join(i.text for i in e.items if not i.hidden),
                                                 key=f"cs_ei_{e.id}", height=max(90, 26 * len(e.items) + 40))
                    data["include"] = st.checkbox("Include this entry", not e.hidden, key=f"cs_einc_{e.id}")
                    entries.append(data)
                if st.form_submit_button("Save section", type="primary"):
                    _save_section(doc.id, section.id, stitle, hide, entries)
    with st.form(f"cs_newsec_{doc.id}", border=False):
        a, b = st.columns([2, 1])
        kinds = [k for k in DEFAULT_TITLES if content.section(k) is None or k == "custom"]
        kind = a.selectbox("Add a section", kinds, format_func=lambda k: DEFAULT_TITLES[k])
        if b.form_submit_button("Add section", width="stretch"):
            def run(s):
                d = repo.get_doc(s, doc.id)
                new = repo.load(d)
                section = new.ensure_section(kind) if kind != "custom" else None
                if section is None:
                    from src.workspace.document import Section
                    section = Section(kind="custom", title="Additional Information")
                    new.sections.append(section)
                section.entries.append(Entry(provenance="edited"))
                repo.save(s, d, new, revision=("edit", f"Added {section.title}"))
            _act(run, "Section added — open it below to fill it in.")


def _move(s, doc_id: int, section_id: str, offset: int) -> None:
    d = repo.get_doc(s, doc_id)
    content = repo.load(d)
    content.move_section(section_id, offset)
    repo.save(s, d, content, revision=("edit", "Changed section order"))


def _add_entry(s, doc_id: int, section_id: str) -> None:
    d = repo.get_doc(s, doc_id)
    content = repo.load(d)
    section = content.find_section(section_id)
    if section is not None:
        section.entries.append(Entry(provenance="edited", items=[Item(text="New line", provenance="edited")]))
        repo.save(s, d, content, revision=("edit", f"Added an entry to {section.title}"))


# --- job-specific -------------------------------------------------------------------------------

def _job_choices() -> tuple[list[JobPosting], list[tuple[int, str, str | None, str | None, str | None]]]:
    outcome = st.session_state.get(OUTCOME_KEY)
    search = list(outcome.unique_jobs) if outcome is not None else []
    with session_scope(_db()) as s:
        tracked = [(a.id, a.title, a.company, a.description, a.job_key) for a in list_applications(s)
                   if a.description]
    return search, tracked


def _create_tailored(job: JobPosting, *, name: str, track: bool, app_id: int | None) -> None:
    settings = get_settings()

    def run(s):
        base = repo.tailoring_base(s)
        if base is None:
            raise WorkspaceError("Upload your CV first.")
        version = repo.create_version(s, base, name=name, target_title=job.title, target_company=job.company,
                                      job_description=job.description, job_key=job.key)
        report = tailor(repo.load(version), job, settings.scoring_weights)
        approval.store(s, version, report.suggestions, source="tailoring")
        approval.store_questions(s, version, review(repo.load(version), [job.title]).questions)
        app = None
        if app_id is not None:
            from src.tracker.repository import get as get_app
            app = get_app(s, app_id)
        elif track:
            app = find_by_job(s, job.key) if job.provider_id != "manual" else None
            if app is None:
                if job.provider_id != "manual":
                    app, _ = save_job(s, None, job, "To Apply")
                else:
                    app = add_manual(s, ApplicationInput(job.title, job.company, status="To Apply"))
                    app.description = job.description
        if app is not None:
            repo.select_for_application(s, app, version)
        _select(version.id)
    _act(run, "Tailored CV created — review the job-specific suggestions below.")


def _new_tailored_form() -> None:
    search, tracked = _job_choices()
    prefill: JobPosting | None = st.session_state.pop(PREFILL_KEY, None)
    options = (["From my job search"] if search or prefill else []) + (["From my application tracker"] if tracked else []) \
        + ["Paste a job description"]
    if prefill is not None:
        st.session_state["cs_job_source"] = "From my job search"
        st.session_state["cs_job_pick"] = prefill.key
        if prefill.key not in {j.key for j in search}:
            search = [prefill, *search]
        st.session_state["cs_prefill_cache"] = prefill
    elif (cached := st.session_state.get("cs_prefill_cache")) is not None and cached.key not in {j.key for j in search}:
        search = [cached, *search]
    if st.session_state.get("cs_job_source") not in options:
        st.session_state["cs_job_source"] = options[0]
    source = st.radio("Job", options, key="cs_job_source", horizontal=True)
    job: JobPosting | None = None
    app_id = None
    if source == "From my job search":
        by_key = {j.key: j for j in search}
        if st.session_state.get("cs_job_pick") not in by_key:
            st.session_state["cs_job_pick"] = next(iter(by_key))
        pick = st.selectbox("Job from your search", list(by_key), key="cs_job_pick",
                            format_func=lambda k: f"{by_key[k].title} — {by_key[k].company or 'company not provided'}")
        job = by_key[pick]
    elif source == "From my application tracker":
        by_id = {t[0]: t for t in tracked}
        pick = st.selectbox("Application", list(by_id), key="cs_job_app",
                            format_func=lambda i: f"{by_id[i][1]} — {by_id[i][2] or 'company not provided'}")
        _, title, company, description, key = by_id[pick]
        job, app_id = job_posting(title, description or "", company, key=key), pick
    else:
        a, b = st.columns(2)
        title = a.text_input("Job title", key="cs_job_title", max_chars=300)
        company = b.text_input("Company (optional)", key="cs_job_company", max_chars=300)
        description = st.text_area("Job description", key="cs_job_text", height=200,
                                   placeholder="Paste the full job description here.")
        if title.strip() and len(description.split()) >= 30:
            job = job_posting(title, description, company or None)
        elif description.strip():
            st.caption("Add a job title and at least 30 words of the description.")
    if job is None:
        return
    with session_scope(_db()) as s:
        existing = next((d for d in repo.list_docs(s) if d.job_key and d.job_key == job.key), None)
        existing = (existing.id, repo.label(existing)) if existing else None
        base = repo.tailoring_base(s)
        base_label = repo.label(base) if base else ""
    if existing:
        notice(f"You already have a tailored CV for this job: {existing[1]}.", tone="info")
        if st.button("Open it", key="cs_job_open_existing"):
            _select(existing[0])
            st.rerun()
    name = st.text_input("Name of the tailored CV", value=repo.default_version_name(job.title, job.company)[:160],
                         key=f"cs_job_name_{hashlib.sha1(job.key.encode()).hexdigest()[:8]}", max_chars=160)
    track = app_id is None and st.checkbox("Add this job to my application tracker and link this CV to it", value=True,
                                           key="cs_job_track")
    st.caption(f"Starts from: {base_label}. Your master CVs are not changed.")
    if st.button("Create tailored CV", type="primary", icon=":material/auto_awesome:", key="cs_job_create"):
        with st.spinner("Comparing your CV with the job…"):
            _create_tailored(job, name=name, track=bool(track), app_id=app_id)


def _application_link(doc: DocInfo) -> None:
    with session_scope(_db()) as s:
        d = repo.get_doc(s, doc.id)
        linked = [(a.id, a.title, a.company, a.status, a.cv_revision_number) for a in repo.applications_using(s, d)]
        apps = [(a.id, a.title, a.company, a.status) for a in list_applications(s) if a.cv_doc_id != doc.id]
    section_header("Job application", "The exact CV revision you send is kept with the application.")
    for app_id, title, company, status, pinned in linked:
        with st.container(border=True):
            st.markdown(f"**{escape(title)}** — {escape(company or 'company not provided')} · {escape(status)}")
            if pinned:
                st.caption(f"Sent with revision {pinned} of this CV. Later edits do not change what was sent.")
            elif st.button("I submitted my application with this CV", key=f"cs_submit_{app_id}",
                           icon=":material/task_alt:", help="Marks it as submitted and keeps this exact revision."):
                _act(lambda s, aid=app_id: set_status(s, aid, "Application Submitted"),
                     "Marked as submitted. The CV revision you sent is saved with the application.")
    if apps:
        with st.expander("Link this CV to another application", icon=":material/link:"):
            by_id = {a[0]: a for a in apps}
            pick = st.selectbox("Application", list(by_id), key=f"cs_link_{doc.id}",
                                format_func=lambda i: f"{by_id[i][1]} — {by_id[i][2] or '—'} ({by_id[i][3]})")
            ok = st.checkbox("Yes, use this CV for that application", key=f"cs_link_ok_{doc.id}")
            if st.button("Link CV", disabled=not ok, key=f"cs_link_btn_{doc.id}"):
                def run(s):
                    from src.tracker.repository import get as get_app
                    repo.select_for_application(s, get_app(s, pick), repo.get_doc(s, doc.id))
                _act(run, "CV linked to the application.")


def _tab_job(doc: DocInfo) -> None:
    settings = get_settings()
    if doc.role == "version" and doc.job_description:
        job = job_posting(doc.target_title or "Target role", doc.job_description, doc.target_company, key=doc.job_key)
        with session_scope(_db()) as s:
            d = repo.get_doc(s, doc.id)
            content = repo.load(d)
            parent = s.get(type(d), doc.parent_id) if doc.parent_id else None
            before_content = (repo.load(repo.get_revision(s, parent, doc.parent_revision))
                              if parent is not None and doc.parent_revision else None)
        report = tailor(content, job, settings.scoring_weights)
        before = score(before_content, job, settings.scoring_weights).score if before_content else None
        a, b = st.columns([1, 2])
        a.html(score_card_html(report.result.score, f"{report.result.confidence} confidence", "Match with this job",
                               "How well this CV matches the job description — guidance, not a prediction."))
        with b:
            if before is not None:
                delta = report.result.score - before
                st.metric("Before tailoring", f"{before}", f"{delta:+d} now" if delta else "no change")
            st.markdown("**Strengths this job asks for**")
            st.html(chips_html(report.strengths[:12], "success", "None found"))
            st.markdown("**Genuine gaps — not added to your CV**")
            st.html(chips_html([g for g, _ in report.gaps][:12], "warning", "No gaps found"))
        st.caption(report.note)
        c1, c2 = st.columns(2)
        if c1.button("Refresh job-specific suggestions", icon=":material/refresh:", key=f"cs_tailor_{doc.id}",
                     width="stretch"):
            _act(lambda s: approval.store(s, repo.get_doc(s, doc.id), tailor(content, job, settings.scoring_weights)
                                          .suggestions, source="tailoring"), "Suggestions refreshed.")
        with c2:
            if ai.available(settings):
                with st.popover("Ask Claude to tailor it", icon=":material/psychology:", width="stretch"):
                    st.caption(ai.DATA_NOTICE + " The job description is sent too.")
                    consent = st.checkbox("Send my CV text (without contact details) and the job to Anthropic",
                                          key=f"cs_ai_job_ok_{doc.id}")
                    if st.button("Get Claude's suggestions", disabled=not consent, type="primary",
                                 key=f"cs_ai_job_{doc.id}"):
                        with st.spinner("Claude is tailoring your CV — this can take a minute…"):
                            try:
                                feedback, suggestions, cost = ai.tailor_with_claude(content, job.title, job.description,
                                                                              settings)
                            except ai.AIError as exc:
                                st.error(f"{exc} The built-in suggestions still work.", icon=":material/error:")
                            else:
                                st.session_state[_AI_FEEDBACK] = (doc.id, feedback, cost)
                                _act(lambda s: approval.store(s, repo.get_doc(s, doc.id), suggestions,
                                                              source="claude"),
                                     f"Claude suggested {len(suggestions)} change(s).")
        fb = st.session_state.get(_AI_FEEDBACK)
        if fb and fb[0] == doc.id:
            notice(fb[1], tone="info", title="Claude's feedback:")
            st.caption(fb[2])
        section_header("Job-specific suggestions")
        _rec_list(doc, ("tailoring", "claude"), f"cs_job_{doc.id}")
        _application_link(doc)
        st.divider()
        with st.expander("Tailor another CV for a different job", icon=":material/add:"):
            _new_tailored_form()
        return
    st.caption("A tailored CV is a separate copy made for one job. It starts from your approved Revised Master CV "
               "(or the original), and changing it never changes any other CV.")
    _new_tailored_form()
    if doc.role == "version":
        _application_link(doc)


def _tab_compare(doc: DocInfo, docs: list[DocInfo]) -> None:
    labels = {d.id: d.label for d in docs}
    with session_scope(_db()) as s:
        revs = {d.id: [(r.number, r.note, r.created_at) for r in repo.get_doc(s, d.id).revisions] for d in docs}
    a, b = st.columns(2)
    default_a = doc.parent_id if doc.parent_id in labels else doc.id
    left = a.selectbox("Compare", list(labels), index=list(labels).index(default_a), format_func=labels.get,
                       key=f"cs_cmp_a_{doc.id}")
    left_rev = a.selectbox("Revision", [r[0] for r in revs[left]][::-1], key=f"cs_cmp_ar_{doc.id}_{left}",
                           index=0 if left != doc.parent_id or not doc.parent_revision else
                           [r[0] for r in revs[left]][::-1].index(doc.parent_revision)
                           if doc.parent_revision in [r[0] for r in revs[left]] else 0,
                           format_func=lambda n: next(f"Revision {n} — {note}" for m, note, _ in revs[left] if m == n))
    right = b.selectbox("With", list(labels), index=list(labels).index(doc.id), format_func=labels.get,
                        key=f"cs_cmp_b_{doc.id}")
    right_rev = b.selectbox("Revision", [r[0] for r in revs[right]][::-1], key=f"cs_cmp_br_{doc.id}_{right}",
                            format_func=lambda n: next(f"Revision {n} — {note}" for m, note, _ in revs[right] if m == n))
    with session_scope(_db()) as s:
        ca = repo.load(repo.get_revision(s, repo.get_doc(s, left), left_rev))
        cb = repo.load(repo.get_revision(s, repo.get_doc(s, right), right_rev))
    changes = repo.compare(ca, cb)
    counts = {k: sum(c.kind == k for c in changes) for k in ("added", "removed", "changed")}
    st.html('<div class="cm-badge-row">' + badge_html(f"{counts['added']} added", "success")
            + badge_html(f"{counts['removed']} removed", "danger")
            + badge_html(f"{counts['changed']} changed", "warning") + "</div>")
    st.html(changes_html(changes))
    with st.expander("Side by side", icon=":material/view_column:"):
        x, y = st.columns(2)
        x.html(cv_html(ca))
        y.html(cv_html(cb))


def _format_form(doc: DocInfo) -> FormatSettings:
    with session_scope(_db()) as s:
        fmt = repo.load_format(repo.get_doc(s, doc.id))
    with st.expander("Template and layout", icon=":material/palette:"):
        with st.form(f"cs_fmt_{doc.id}", border=False):
            a, b, c = st.columns(3)
            template = a.selectbox("Template", list(TEMPLATE_LABELS), index=list(TEMPLATE_LABELS).index(fmt.template),
                                   format_func=TEMPLATE_LABELS.get)
            page = b.selectbox("Page size", list(PAGE_SIZES), index=list(PAGE_SIZES).index(fmt.page),
                               format_func=lambda p: {"a4": "A4", "letter": "US Letter"}[p])
            family = c.selectbox("Typeface", ["sans-serif", "serif"], index=["sans-serif", "serif"].index(fmt.font_family),
                                 format_func=lambda f: {"sans-serif": "Sans-serif (Helvetica/Calibri)",
                                                        "serif": "Serif (Times/Cambria)"}[f])
            body = a.slider("Text size (pt)", 9.0, 13.0, float(fmt.body_size), 0.5)
            margin = b.slider("Margins (pt)", 36, 90, int(fmt.margin), 2)
            accent = c.color_picker("Heading colour", fmt.accent_color)
            if st.form_submit_button("Save layout", disabled=not doc.editable):
                try:
                    new = fmt.model_copy(update={"template": template, "page": page, "font_family": family,
                                                 "body_size": body, "heading_size": max(fmt.heading_size, body + 1),
                                                 "margin": float(margin), "accent_color": accent.upper()})
                    FormatSettings.model_validate(new.model_dump())
                except ValueError:
                    st.error("Those settings are outside the readable range.", icon=":material/error:")
                else:
                    _act(lambda s: repo.save(s, repo.get_doc(s, doc.id), fmt=new,
                                             revision=("format", f"Layout: {TEMPLATE_LABELS[template]}")),
                         "Layout saved.")
            if not doc.editable:
                st.caption("The original's layout is fixed; change it in your Revised Master CV or a tailored CV.")
    return fmt


def _tab_export(doc: DocInfo) -> None:
    fmt = _format_form(doc)
    content = _content(doc.id)
    one_page = st.toggle("Fit onto one page (only if it stays readable)", key=f"cs_one_{doc.id}")
    digest = hashlib.sha256((content.model_dump_json() + fmt.model_dump_json() + str(one_page)).encode()).hexdigest()
    preview = st.session_state.get(_PREVIEW, {}).get(doc.id)
    if preview is None or preview[0] != digest:
        if st.button("Preview final CV", type="primary", icon=":material/preview:", key=f"cs_prev_{doc.id}"):
            with st.spinner("Generating the preview…"):
                try:
                    pdf = render_pdf(content, fmt, one_page=one_page)
                    validation = validate_pdf(pdf.data, content)
                    pngs = preview_png(pdf.data)
                except Exception:
                    st.error("The preview could not be generated. Try another template.", icon=":material/error:")
                    return
            st.session_state.setdefault(_PREVIEW, {})[doc.id] = (digest, pngs, validation.as_dict(), pdf.pages,
                                                                pdf.fits_one_page)
            st.rerun()
        return
    _, pngs, validation, pages, fits = preview
    st.caption(f"{pages} page(s)" + (" — could not fit onto one page without going below readable limits; consider "
                                      "leaving out older or less relevant lines (Edit tab)." if one_page and not fits
                                      else ""))
    cols = st.columns(min(2, len(pngs)))
    for n, png in enumerate(pngs):
        cols[n % len(cols)].image(png, caption=f"Page {n + 1}", width="stretch")
    st.html(checks_html(validation["checks"]))
    if doc.editable:
        with session_scope(_db()) as s:
            status = repo.get_doc(s, doc.id).status
        if status != "approved":
            if st.button("Approve this CV", icon=":material/verified:", key=f"cs_approve_{doc.id}",
                         help="Marks it as reviewed by you. Editing it later makes it a draft again."):
                _act(lambda s: repo.approve(s, repo.get_doc(s, doc.id)), "Approved.")
        else:
            st.html(badge_html("Approved by you", "success"))
    section_header("Download", "Each file is generated, opened again and checked before it is offered.")
    with session_scope(_db()) as s:
        linked = [(a.id, f"{a.title} — {a.company or '—'}") for a in repo.applications_using(s, repo.get_doc(s, doc.id))]
    app_id = None
    if linked:
        app_id = st.selectbox("Keep the file with application", [None, *[a[0] for a in linked]],
                              format_func=lambda i: "None" if i is None else dict(linked)[i], key=f"cs_exp_app_{doc.id}")
    c1, c2 = st.columns(2)
    for col, kind, label in ((c1, "pdf", "PDF"), (c2, "docx", "DOCX (Word)")):
        made = st.session_state.get(_EXPORT, {}).get((doc.id, kind))
        if made and made["digest"] == digest:
            if made["ok"]:
                col.download_button(f"Download {label}", made["data"], file_name=made["filename"],
                                    mime=exports.MIME[kind], type="primary", icon=":material/download:",
                                    key=f"cs_dl_{kind}_{doc.id}", on_click="ignore", width="stretch")
                col.caption(f"Generated and checked: {made['filename']}")
            else:
                col.error(made["error"], icon=":material/error:")
            continue
        if col.button(f"Create {label}", key=f"cs_make_{kind}_{doc.id}", icon=":material/description:",
                      width="stretch"):
            with st.spinner(f"Generating and checking the {label}…"):
                with session_scope(_db()) as s:
                    from src.tracker.repository import get as get_app
                    result = exports.generate(s, repo.get_doc(s, doc.id), kind, one_page=one_page,
                                              application=get_app(s, app_id) if app_id else None)
            st.session_state.setdefault(_EXPORT, {})[(doc.id, kind)] = {
                "digest": digest, "ok": result.ok, "data": result.data, "filename": result.filename,
                "error": result.error}
            st.rerun()


def _tab_history(doc: DocInfo, docs_all: list[DocInfo]) -> None:
    show_archived = st.toggle("Show archived CVs", key="cs_hist_arch")
    docs = docs_all if show_archived else [d for d in docs_all if d.status != "archived"]
    by_id = {d.id: d for d in docs_all}
    rows = []
    with session_scope(_db()) as s:
        used = {d.id: len(repo.applications_using(s, repo.get_doc(s, d.id))) for d in docs}
    for d in docs:
        base = (f"{by_id[d.parent_id].label} · rev {d.parent_revision}" if d.parent_id in by_id else "—")
        rows.append({"CV": d.label, "Id": d.id, "Status": d.status.title(), "Based on": base,
                     "Created": _date(d.created_at), "Updated": _date(d.updated_at), "Revisions": d.revisions,
                     "Applications": used.get(d.id, 0)})
    st.dataframe(rows, hide_index=True, width="stretch")
    section_header(f"{doc.label}", "Actions and history of the CV you are working on.")
    if doc.role != "master":
        a, b, c, d_ = st.columns(4)
        with a.popover("Rename", icon=":material/edit:", width="stretch"):
            new_name = st.text_input("Name", doc.name, key=f"cs_rename_{doc.id}", max_chars=160)
            if st.button("Save name", key=f"cs_rename_btn_{doc.id}"):
                _act(lambda s: repo.rename(s, repo.get_doc(s, doc.id), new_name), "Renamed.")
        if b.button("Duplicate", icon=":material/content_copy:", key=f"cs_dup_{doc.id}", width="stretch"):
            _act(lambda s: _select(repo.duplicate(s, repo.get_doc(s, doc.id)).id), "Copy created.")
        archived = doc.status == "archived"
        if c.button("Restore from archive" if archived else "Archive", icon=":material/archive:",
                    key=f"cs_arch_{doc.id}", width="stretch"):
            _act(lambda s: repo.set_archived(s, repo.get_doc(s, doc.id), not archived),
                 "Restored." if archived else "Archived.")
        with d_.popover("Delete", icon=":material/delete:", width="stretch"):
            st.caption("Deletes this CV, its history and its generated files. Your master CVs are not affected.")
            sure = st.checkbox("Yes, delete it permanently", key=f"cs_del_ok_{doc.id}")
            if st.button("Delete", disabled=not sure, key=f"cs_del_{doc.id}", type="primary"):
                def run(s):
                    repo.delete(s, repo.get_doc(s, doc.id))
                    st.session_state.pop(_NEXT_DOC, None)
                    st.session_state[_NEXT_DOC] = -1  # falls back to the Revised Master CV
                _act(run, "Deleted.")
    if st.button("Use this CV for job matching", icon=":material/fact_check:", key=f"cs_match_{doc.id}",
                 help="Job Matches and CV Analysis will use this CV's text in this session."):
        text = _content(doc.id).to_text()
        set_active_cv(st.session_state, ActiveCV(f"{doc.name}.txt", len(text.encode()),
                                                 hashlib.sha256(text.encode()).hexdigest(), datetime.now(timezone.utc),
                                                 ExtractionResult(text, "docx", None)))
        clear_matches(st.session_state)
        st.toast("Job matching now uses this CV.", icon=":material/check_circle:")
    with session_scope(_db()) as s:
        d = repo.get_doc(s, doc.id)
        revisions = [(r.number, r.kind, r.note, r.created_at) for r in reversed(d.revisions)]
        files = [(f.id, f.kind, f.filename, f.revision_number, f.created_at, f.page_count)
                 for f in exports.list_files(s, d)]
    st.markdown("**Revisions**")
    for number, kind, note, created in revisions[:30]:
        r1, r2, r3 = st.columns([4, 1.2, 1.2])
        r1.markdown(f"**Revision {number}** · {escape(note)}  \n<span class='cm-muted'>{_date(created)} · "
                    f"{escape(kind)}</span>", unsafe_allow_html=True)
        if doc.editable and number != revisions[0][0] and r2.button("Restore as new", key=f"cs_rest_{doc.id}_{number}",
                                                                    width="stretch"):
            _act(lambda s, n=number: repo.restore(s, repo.get_doc(s, doc.id), n),
                 f"Revision {number} restored as a new revision.")
        if r3.button("PDF", key=f"cs_rev_pdf_{doc.id}_{number}", icon=":material/picture_as_pdf:", width="stretch",
                     help="Generate a PDF of exactly this revision."):
            with session_scope(_db()) as s:
                result = exports.generate(s, repo.get_doc(s, doc.id), "pdf", revision=number)
            if result.ok:
                _flash(f"PDF of revision {number} generated — download it under Generated files.")
            else:
                st.error(result.error, icon=":material/error:")
                return
            st.rerun()
    if files:
        st.markdown("**Generated files**")
        for fid, kind, filename, rev, created, pages in files[:15]:
            f1, f2 = st.columns([4, 1.4])
            f1.markdown(f"{escape(filename)} · revision {rev} · {_date(created)}"
                        + (f" · {pages} page(s)" if pages else ""))
            with session_scope(_db()) as s:
                data = exports.file_bytes(s.get(CVFile, fid))
            f2.download_button("Download", data, file_name=filename, mime=exports.MIME[kind], key=f"cs_file_{fid}",
                               on_click="ignore", icon=":material/download:", width="stretch")


# --- page --------------------------------------------------------------------------------------------

def _progress(doc: DocInfo) -> tuple[dict[str, bool], str]:
    with session_scope(_db()) as s:
        recs = list(s.scalars(select(CVRecommendation).where(CVRecommendation.doc_id == doc.id)))
        qs = list(s.scalars(select(CVQuestion).where(CVQuestion.doc_id == doc.id)))
        files = list(s.scalars(select(CVFile).where(CVFile.doc_id == doc.id)))
    reviewed = bool(recs)
    approved = reviewed and not any(r.status == "pending" and r.action != "advice" for r in recs)
    answered = reviewed and not any(q.status == "open" and q.essential for q in qs)
    done = {"Upload": True, "Review": reviewed, "Approve changes": approved, "Missing information": answered,
            "Preview & download": bool(files)}
    current = next((name for name in ("Review", "Approve changes", "Missing information", "Preview & download")
                    if not done[name]), "Preview & download")
    return done, current


def render() -> None:
    page_header("CV Studio", "Review, improve and tailor your CV — then download a checked PDF or Word file. "
                "Every change is yours to approve.", eyebrow="Prepare")
    if flash := st.session_state.pop(_FLASH, None):
        st.toast(flash, icon=":material/check_circle:")
    docs_all = _docs(include_archived=True)
    current = [d for d in docs_all if d.status != "archived" or d.role != "master"]
    master = next((d for d in docs_all if d.role == "master" and d.status != "archived"), None)
    if master is None:
        with st.container(border=True):
            _upload_panel(replacing=False)
        _legacy_import()
        section_header("What CV Studio does")
        feature_grid(_FEATURES)
        return
    active = [d for d in current if d.status != "archived"]
    ids = [d.id for d in active]
    if (wanted := st.session_state.pop(_NEXT_DOC, None)) in {d.id for d in docs_all}:
        st.session_state[_DOC] = wanted
    if st.session_state.get(_DOC) not in {d.id for d in docs_all}:
        revised = next((d for d in active if d.role == "revised"), None)
        st.session_state[_DOC] = (revised or master).id
    selected_id = st.session_state[_DOC]
    if selected_id not in ids:
        ids = [*ids, selected_id]
    by_id = {d.id: d for d in docs_all}
    with st.container(border=True):
        st.selectbox("CV you are working on", ids, key=_DOC, format_func=lambda i: by_id[i].label)
    doc = by_id[st.session_state[_DOC]]
    done, now = _progress(doc) if doc.editable else ({"Upload": True}, "Review")
    st.html(workflow_html(done, now))
    tabs = st.tabs(["Master CV", "Review & scores", "Recommended changes", "Missing information", "Edit",
                    "Tailor for a job", "Compare", "Preview & download", "Version history"])
    with tabs[0]:
        _tab_master(master)
    with tabs[1]:
        _tab_review(doc)
    with tabs[2]:
        _tab_changes(doc)
    with tabs[3]:
        _tab_questions(doc)
    with tabs[4]:
        _tab_edit(doc)
    with tabs[5]:
        _tab_job(doc)
    with tabs[6]:
        _tab_compare(doc, [d for d in docs_all if d.status != "archived" or d.id == doc.id])
    with tabs[7]:
        _tab_export(doc)
    with tabs[8]:
        _tab_history(doc, docs_all)


__all__ = ["PREFILL_KEY", "cv_html", "render"]
