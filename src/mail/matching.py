"""Which application an email belongs to — with a confidence score, never a guess.

Strongest evidence first:
1. the same conversation (thread id) or a direct reply (In-Reply-To / References) to an email
   already linked to an application — near certain;
2. the address the application was sent to;
3. the sender's domain matching the company, or the company named in the sender, subject or text
   (including emails from applicant-tracking systems such as Greenhouse or Workday);
4. the job title or the original subject line.
Signals combine as independent evidence. An email is linked automatically only when one
application is clearly ahead; close calls and weak evidence go to the review queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.jobs.normalization import normalize_company, normalize_title
from src.mail.types import MailItem, domain_of

AUTO_LINK = 0.75
SUGGEST = 0.40
MARGIN = 0.15
THREAD = 0.97

FREEMAIL = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com", "icloud.com",
    "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "zoho.com", "mail.com", "yandex.com",
})
ATS_DOMAINS = frozenset({
    "greenhouse.io", "greenhouse-mail.io", "lever.co", "hire.lever.co", "myworkday.com", "myworkdayjobs.com",
    "workday.com", "smartrecruiters.com", "ashbyhq.com", "workablemail.com", "workable.com", "icims.com",
    "taleo.net", "successfactors.com", "successfactors.eu", "bamboohr.com", "recruitee.com", "teamtailor.com",
    "jobvite.com", "breezy.hr", "personio.de", "personio.com", "jazzhr.com", "applytojob.com", "rippling.com",
    "pinpointhq.com", "eightfold.ai", "oraclecloud.com",
})
_GENERIC_WORDS = frozenset({"and", "of", "for", "solutions", "services", "systems", "technologies", "technology",
                            "global", "international", "consulting", "digital", "uk", "us", "labs", "software"})


@dataclass(frozen=True)
class Candidate:
    """What the matcher needs to know about one application."""
    id: int
    title: str
    company: str | None
    contact_email: str | None
    application_subject: str | None
    applied_at: datetime | None


@dataclass(frozen=True)
class Match:
    application_id: int | None
    confidence: float
    reason: str
    alternatives: tuple[tuple[int, float], ...] = ()

    @property
    def automatic(self) -> bool:
        return self.application_id is not None and self.confidence >= AUTO_LINK


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", (text or "").lower()).split())


def _company_tokens(company: str | None) -> list[str]:
    return [t for t in normalize_company(company).split() if t not in _GENERIC_WORDS and len(t) > 1]


def _base_domain(domain: str) -> str:
    """'mail.careers.example-devices.co.uk' → 'example-devices' (good enough for comparing names)."""
    parts = [p for p in domain.split(".") if p]
    while len(parts) > 1 and (len(parts[-1]) <= 3 or parts[-1] in {"com", "net", "org", "co", "io", "jobs"}):
        parts.pop()
    return parts[-1] if parts else ""


def _is_ats(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in ATS_DOMAINS)


def _combine(signals: list[tuple[float, str]]) -> tuple[float, str]:
    """Independent evidence: 1 - Π(1 - p). Capped below thread certainty."""
    remaining = 1.0
    for p, _ in signals:
        remaining *= 1 - p
    reasons = [r for _, r in sorted(signals, key=lambda s: -s[0])]
    return min(round(1 - remaining, 2), 0.95), "; ".join(reasons[:3])


def score(item: MailItem, cand: Candidate) -> tuple[float, str]:
    signals: list[tuple[float, str]] = []
    counterpart = [item.from_address or ""] if item.direction == "in" else list(item.to_addresses)
    counterpart = [a.lower() for a in counterpart if a]
    contact = (cand.contact_email or "").lower()
    if contact and contact in counterpart:
        signals.append((0.9, "the address you applied to"))
    elif contact and domain_of(contact) not in FREEMAIL and any(domain_of(a) == domain_of(contact) for a in counterpart):
        signals.append((0.6, "same organisation as the address you applied to"))

    subject, text = _norm(item.subject), _norm(item.text)
    sender_name = _norm(item.from_name or "")
    tokens = _company_tokens(cand.company)
    if tokens:
        phrase = " ".join(tokens)
        domains = [domain_of(a) for a in counterpart]
        squashed = "".join(tokens)
        def _company_domain(d: str) -> bool:
            base = _base_domain(d).replace("-", "")
            # The whole name must match ("exampledevices"); one word only for one-word names ("contoso").
            return squashed in base if len(tokens) > 1 else base == squashed or base.startswith(squashed)
        if any(d not in FREEMAIL and not _is_ats(d) and _company_domain(d) for d in domains):
            signals.append((0.65, "sender's domain matches the company"))
        if re.search(rf"\b{re.escape(phrase)}\b", sender_name):
            signals.append((0.55, "the company is the sender"))
        if re.search(rf"\b{re.escape(phrase)}\b", subject):
            signals.append((0.5, "the company is named in the subject"))
        elif re.search(rf"\b{re.escape(phrase)}\b", text):
            signals.append((0.35, "the company is named in the email"))

    title = normalize_title(cand.title)
    if title and (re.search(rf"\b{re.escape(title)}\b", subject) or re.search(rf"\b{re.escape(title)}\b", text)):
        signals.append((0.3, "the job title is mentioned"))
    else:
        words = [w for w in title.split() if len(w) > 2]
        found = sum(bool(re.search(rf"\b{re.escape(w)}\b", f"{subject} {text}")) for w in words)
        if words and found / len(words) >= 0.6:
            signals.append((0.12, "most of the job title is mentioned"))
    original = _norm(cand.application_subject or "")
    if original and original in subject:
        signals.append((0.55, "replies to your application's subject line"))
    if not signals:
        return 0.0, ""
    if not any(r.startswith(("the address", "same organisation", "sender's domain", "the company")) for _, r in signals):
        signals = [(p * 0.5, r) for p, r in signals]  # the title alone never identifies the employer
    return _combine(signals)


def match(item: MailItem, candidates: list[Candidate], *, threads: dict[str, int], linked_ids: dict[str, int]) -> Match:
    """``threads``: thread id → application; ``linked_ids``: Message-ID of linked emails → application."""
    if item.thread_id and item.thread_id in threads:
        return Match(threads[item.thread_id], THREAD, "same email conversation as a linked email")
    for ref in item.references:
        if ref in linked_ids:
            return Match(linked_ids[ref], THREAD, "a reply to a linked email")
    scored = []
    for cand in candidates:
        if cand.applied_at and item.sent_at < cand.applied_at - timedelta(days=2):
            continue  # sent before you applied
        conf, reason = score(item, cand)
        if conf > 0:
            scored.append((conf, cand.id, reason))
    if not scored:
        return Match(None, 0.0, "no application matches this email")
    scored.sort(key=lambda s: -s[0])
    best_conf, best_id, best_reason = scored[0]
    alternatives = tuple((cid, conf) for conf, cid, _ in scored[1:4])
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_conf >= AUTO_LINK and best_conf - second >= MARGIN:
        return Match(best_id, best_conf, best_reason, alternatives)
    if best_conf >= SUGGEST:
        why = best_reason + ("; another application is almost as likely" if best_conf - second < MARGIN else "")
        return Match(best_id, round(min(best_conf, AUTO_LINK - 0.01), 2), why, alternatives)
    return Match(None, best_conf, "too little evidence to link it to an application", ((best_id, best_conf),))
