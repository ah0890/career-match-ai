"""Optional Claude review and tailoring (Anthropic API).

Used only when ``ANTHROPIC_API_KEY`` is set, AI is enabled in settings, and the user confirms
each time that their CV text may be sent. Before anything is sent, contact details (name,
email, phone, location, links) are removed. Claude only *proposes* changes: they go through the
same approval workflow as the built-in rules, and a proposal that introduces a figure, skill or
name the CV does not contain is flagged so the user must confirm it before it can be accepted.

Any failure (no key, network, rate limit, refusal) raises :class:`AIError`; callers then carry on
with the built-in rules.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from config.settings import Settings
from src.matching.skills import extract_skills
from src.workspace.document import CVDocument
from src.workspace.review import Suggestion

DATA_NOTICE = ("Your CV text (without your name, email, phone, location or links) is sent to Anthropic's API to "
               "generate suggestions. Anthropic does not use API data to train its models by default. Nothing is "
               "changed until you accept a suggestion.")
_MAX_CV_CHARS = 40_000
_MAX_JOB_CHARS = 20_000

_SYSTEM = """You are an expert CV editor. You suggest improvements to a candidate's CV, which you receive as JSON.

Absolute rules:
- Never invent or imply facts that the CV does not state: no new employers, titles, dates, qualifications, \
certifications, tools, skills, achievements, figures or percentages. Never upgrade the candidate's role \
(e.g. "helped with" must not become "led").
- A rewrite must keep the original meaning. Improve clarity, concision, grammar, active voice and impact only.
- If a line would be stronger with information you do not have (a figure, a scope, a result), give advice \
instead of a rewrite and say which information the candidate should add.
- Keep the CV's spelling variant (British or American English) and its tense conventions.
- Only reference item ids that appear in the CV JSON. Propose at most 25 changes, most valuable first.
- Explanations are addressed to the candidate in plain language, one or two sentences."""


class AIChange(BaseModel):
    item_id: str | None = Field(None, description="Id of the CV line to rewrite; null for general advice. "
                                                   "Use 'summary' to propose a new professional summary.")
    kind: Literal["rewrite", "advice"]
    category: Literal["language", "structure", "summary", "experience", "skills", "relevance", "tailoring"]
    priority: Literal["High", "Medium", "Low"]
    proposed: str = Field("", description="The full replacement text for a rewrite; empty for advice")
    explanation: str
    benefit: str


class AIReview(BaseModel):
    overall_feedback: str = Field(description="Two or three sentences on the CV's main strengths and weaknesses")
    changes: list[AIChange]


class AIError(Exception):
    """Claude could not be used; the message is safe to show."""


def available(settings: Settings) -> bool:
    return bool(settings.cv_ai_enabled and settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value())


def minimised(content: CVDocument) -> dict:
    """What is sent: the CV structure with ids, without contact details or hidden lines."""
    sections = []
    for s in content.sections:
        if s.hidden:
            continue
        entries = []
        for e in s.entries:
            if e.hidden:
                continue
            entries.append({"title": e.title, "organization": e.organization, "dates": e.dates,
                            "items": [{"id": i.id, "text": i.text} for i in e.items if not i.hidden]})
        sections.append({"kind": s.kind, "title": s.title, "entries": entries})
    return {"headline": content.contact.headline, "sections": sections}


def _client(settings: Settings):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise AIError("The Anthropic package is not installed. Run: pip install -r requirements.txt") from exc
    return anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value(), max_retries=2, timeout=180)


def _call(client, settings: Settings, prompt: str) -> AIReview:
    import anthropic
    try:
        response = client.beta.messages.parse(
            model=settings.cv_ai_model,
            max_tokens=12000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_format=AIReview,
            thinking={"type": "adaptive"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise AIError("Anthropic rejected the API key. Check ANTHROPIC_API_KEY in your .env file.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AIError("This API key is not allowed to use the configured model.") from exc
    except anthropic.RateLimitError as exc:
        raise AIError("Anthropic's rate limit was reached. Try again in a minute.") from exc
    except anthropic.APIConnectionError as exc:
        raise AIError("Could not reach Anthropic's API. Check your internet connection.") from exc
    except anthropic.APIStatusError as exc:
        raise AIError(f"Anthropic's API returned an error ({exc.status_code}). Try again later.") from exc
    except Exception as exc:
        raise AIError("Claude's response could not be read. The built-in suggestions are still available.") from exc
    if response.stop_reason == "refusal":
        raise AIError("Claude declined this request. The built-in suggestions are still available.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise AIError("Claude's response was incomplete. Try again, or use the built-in suggestions.")
    return response.parsed_output


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_CAPITALISED = re.compile(r"\b[A-Z][A-Za-z0-9+#.&-]{1,}\b")


def unsupported_claims(proposed: str, original: str, cv_text: str) -> list[str]:
    """Figures, skills or names in ``proposed`` that the CV does not contain."""
    issues = []
    known_numbers = set(_NUMBER.findall(original)) | set(_NUMBER.findall(cv_text))
    new_numbers = [n for n in _NUMBER.findall(proposed) if n not in known_numbers]
    if new_numbers:
        issues.append("adds figure(s) not in your CV: " + ", ".join(dict.fromkeys(new_numbers)))
    cv_skills = {m.name for m in extract_skills(cv_text)}
    new_skills = [m.name for m in extract_skills(proposed) if m.name not in cv_skills]
    if new_skills:
        issues.append("mentions skill(s) not in your CV: " + ", ".join(dict.fromkeys(new_skills)))
    lowered = cv_text.lower()
    first_word = proposed.split()[0] if proposed.split() else ""
    names = [w for w in _CAPITALISED.findall(proposed) if w.lower() not in lowered and w != first_word
             and w not in {"I", "A", "An", "The"}]
    if names:
        issues.append("uses name(s) or term(s) not in your CV: " + ", ".join(dict.fromkeys(names))[:200])
    return issues


def _to_suggestions(review: AIReview, content: CVDocument, *, category_default: str) -> list[Suggestion]:
    cv_text = content.to_text()
    out = []
    for n, change in enumerate(review.changes[:25]):
        proposed = " ".join(change.proposed.split())
        if change.kind == "rewrite" and change.item_id == "summary" and proposed:
            section = content.section("summary")
            current = next((i for e in (section.entries if section else []) for i in e.items if not i.hidden), None)
            issues = unsupported_claims(proposed, "", cv_text)
            out.append(Suggestion(
                f"ai:summary:{n}", change.category or category_default, change.priority,
                "replace" if current else "add", "Professional Summary", current.text if current else "", proposed,
                change.explanation, change.benefit, section_id=section.id if section else None,
                entry_id=section.entries[0].id if current else None, item_id=current.id if current else None,
                verification="Check this summary describes you accurately.",
                warnings=("Claude's text " + "; ".join(issues)) if issues else None, payload={"kind": "summary"},
                source="claude"))
            continue
        found = content.find_item(change.item_id) if change.item_id else None
        if change.kind == "rewrite" and found and proposed and proposed != found[2].text:
            s, e, i = found
            issues = unsupported_claims(proposed, i.text, cv_text)
            out.append(Suggestion(
                f"ai:{i.id}", change.category, change.priority, "replace",
                s.title + (f" · {e.title}" if e.title else ""), i.text, proposed, change.explanation, change.benefit,
                section_id=s.id, entry_id=e.id, item_id=i.id,
                warnings=("Claude's rewrite " + "; ".join(issues) + ". Accept only if it is true.") if issues else None,
                source="claude"))
        elif change.kind == "advice" or not found:
            where = (found[0].title if found else "Whole CV")
            out.append(Suggestion(
                f"ai:advice:{n}", change.category, change.priority, "advice", where,
                found[2].text if found else "", "", change.explanation, change.benefit,
                item_id=found[2].id if found else None, source="claude"))
    return out


def review_with_claude(content: CVDocument, settings: Settings, *, target_roles: tuple[str, ...] = (),
                       client=None) -> tuple[str, list[Suggestion]]:
    """Claude's suggestions for a general review. Raises AIError when Claude cannot be used."""
    if not available(settings):
        raise AIError("Claude is not set up. Add ANTHROPIC_API_KEY to your .env file and restart the app.")
    cv = json.dumps(minimised(content), ensure_ascii=False)[:_MAX_CV_CHARS]
    roles = ", ".join(target_roles) or "not stated"
    prompt = (f"Review this CV. The candidate's target roles: {roles}.\n"
              "Focus on grammar, clarity, achievement statements, structure and relevance to the target roles. "
              "Rewrite lines only where the improvement is clear.\n\n<cv>\n" + cv + "\n</cv>")
    review = _call(client or _client(settings), settings, prompt)
    return review.overall_feedback, _to_suggestions(review, content, category_default="language")


def tailor_with_claude(content: CVDocument, job_title: str, job_description: str, settings: Settings, *,
                       client=None) -> tuple[str, list[Suggestion]]:
    """Claude's job-specific suggestions. Raises AIError when Claude cannot be used."""
    if not available(settings):
        raise AIError("Claude is not set up. Add ANTHROPIC_API_KEY to your .env file and restart the app.")
    cv = json.dumps(minimised(content), ensure_ascii=False)[:_MAX_CV_CHARS]
    prompt = (f"Tailor this CV to the job below. Rewrite the most relevant experience lines so the job's priorities "
              "stand out, using the job's terminology only where the CV already shows that skill, and propose a "
              "tailored professional summary (item_id 'summary'). Do not claim any requirement the CV does not "
              "show; mention genuine gaps as advice.\n\n<job title>" + job_title[:300] + "</job title>\n<job>\n"
              + job_description[:_MAX_JOB_CHARS] + "\n</job>\n\n<cv>\n" + cv + "\n</cv>")
    review = _call(client or _client(settings), settings, prompt)
    suggestions = _to_suggestions(review, content, category_default="tailoring")
    for s in suggestions:
        s.category = "tailoring" if s.action != "advice" else s.category
    return review.overall_feedback, suggestions


__all__ = ["AIError", "DATA_NOTICE", "available", "minimised", "review_with_claude", "tailor_with_claude",
           "unsupported_claims"]
