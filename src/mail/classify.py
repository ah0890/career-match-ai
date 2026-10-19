"""Rule-based classification of recruitment emails, with a confidence score.

Each category has weighted phrases. The strongest category wins; confidence grows with its
weight and drops when another category is nearly as strong. Quoted earlier messages (your own
application, or a previous reply) are removed first, so they never decide the result.
High-impact results — interviews, offers, rejections — need more confidence before they are
applied automatically; anything less goes to the review queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.tracker.recruitment import HIGH_IMPACT
from src.tracker.repository import OTHER_COMMUNICATION

AUTO_THRESHOLD = 0.70
HIGH_IMPACT_THRESHOLD = 0.82

_F = re.I | re.S
_RULES: dict[str, tuple[tuple[re.Pattern, float], ...]] = {
    "Rejected": tuple((re.compile(p, _F), w) for p, w in (
        (r"\bregret to (inform|let you know|advise)", 3.5),
        (r"\b(decided|chosen|elected|opted) (to )?(move|proceed|go|continue) (forward )?with (other|another|a different) candidate", 4),
        (r"\b(will|would|are) not (be )?(moving|progressing|proceeding|taking) (forward|further|your application)", 3.5),
        (r"\bnot (to )?(move|moving|progress|progressing|proceed|proceeding) (forward |further )?with your (application|candidacy)", 3.5),
        (r"\bdecided not to (proceed|progress|move forward|pursue)", 3.5),
        (r"\byour application (has been|was|is) unsuccessful|\bunsuccessful on this occasion", 3.5),
        (r"\b(have|has) not been (selected|shortlisted|successful)|\bnot been selected\b", 3),
        (r"\b(are|am) (not able|unable) to offer you", 3.5),
        (r"\bposition has (now )?been filled", 2.5),
        (r"\bunfortunately\b", 1.2),
        (r"\bwish you (the best|every success|all the best|luck) (of luck )?(in|with) your (job )?search", 1.5),
    )),
    "Offer Received": tuple((re.compile(p, _F), w) for p, w in (
        (r"\b(pleased|delighted|happy|thrilled|excited|glad) to (formally )?(offer you|extend (you )?(an|a|the|our) (formal |written |verbal )?offer)", 4.5),
        (r"\bwe would (like|love) to offer you\b", 4.5),
        (r"\boffer (letter|of employment)\b", 3),
        (r"\b(formal|written|verbal|conditional|contingent) (job )?offer\b", 2.5),
        (r"\b(job|employment) offer\b", 2),
        (r"\b(accept|sign) (the|this|your) offer\b", 2),
    )),
    "Assessment": tuple((re.compile(p, _F), w) for p, w in (
        (r"\b(online|technical|coding|skills?|aptitude|personality|psychometric|cognitive|case) (assessment|test|challenge|exercise|study)", 3),
        (r"\btake[- ]home (assignment|task|exercise|test|challenge)", 3.5),
        (r"\bcomplete (the|an|this|our|a short) (online )?(assessment|assignment|test|questionnaire)", 3),
        (r"\b(hackerrank|codility|testgorilla|codesignal|hirevue|pymetrics|coderbyte|shl\.com|criteria corp)", 2.5),
    )),
    "Interview Scheduled": tuple((re.compile(p, _F), w) for p, w in (
        (r"\b(interview|call|meeting|conversation)\b[^.]{0,40}\b(is |has been |now )?(confirmed|scheduled|booked)\b", 3.5),
        (r"\bconfirm(ing|ation of|s)? (your|the|our) (upcoming )?interview", 3.5),
        (r"^(updated )?invitation: [^\n]*interview", 4),
        (r"\b(calendar )?invite (has been |was )?sent\b", 1.5),
        (r"\blook(ing)? forward to (speaking|meeting|talking) (with|to) you (on|at) ", 2),
    )),
    "Interview Invitation": tuple((re.compile(p, _F), w) for p, w in (
        (r"\b(like|love|happy|pleased|delighted) to invite you (to|for) (a |an |the |our )?[\w\s-]{0,25}(interview|conversation|call|chat|meeting)", 4.5),
        (r"\binvit(e|ation|ing) you (to|for) (a |an |the )?[\w\s-]{0,25}interview", 4),
        (r"\b(schedule|arrange|book|set up) (a |an |the )?[\w\s-]{0,20}(interview|call with)", 2.5),
        (r"\bnext (step|stage|round)\b[^.]{0,80}\binterview", 3),
        (r"\b(your )?availability\b[^.]{0,60}\b(interview|call|chat)", 2.5),
        (r"\b(calendly\.com|goodtime\.io|cal\.com|scheduleonce|calendar\.app\.google)", 2),
        (r"\bmove (you )?forward to the (next|interview) (stage|round)", 3),
    )),
    "Under Review": tuple((re.compile(p, _F), w) for p, w in (
        (r"\b(your )?(application|profile|cv|resume|candidacy)\b[^.]{0,30}\b(is|are) (currently |now )?(under review|being (reviewed|considered))", 3),
        (r"\bwe are (currently )?(reviewing|considering) (your|all) (application|applications|profile|candidacy)", 3),
        (r"\b(hiring|recruiting) (team|manager) (is|are) (currently )?review", 2.5),
        (r"\bwe (will|'ll) (review|be reviewing) (your|all) (application|applications)", 1),
    )),
    "Application Received": tuple((re.compile(p, _F), w) for p, w in (
        (r"\b(thank you|thanks) (so much )?for (your )?(applying|application|interest in (the|our|this)? ?(role|position|job|opening))", 3),
        (r"\b(we have|we've|we) (successfully )?received your application", 3.5),
        (r"\byour application (has been|was) (successfully )?(received|submitted)", 3.5),
        (r"\bapplication (received|confirmation)\b", 2.5),
    )),
}

_RECRUITMENT_TERMS = re.compile(
    r"\b(application|applied|applying|candidate|candidacy|position|role|vacancy|recruit\w*|hiring|interview|"
    r"talent acquisition|job opening|cv|resume|offer)\b", re.I)
_JOB_ALERT = re.compile(
    r"\b(job alert|jobs? (you may|you might) (be interested in|like)|recommended jobs|new jobs (for you|matching)|"
    r"jobs matching your|similar jobs|people are viewing your profile|weekly digest)\b", re.I)
_QUOTE_START = re.compile(
    r"(^|\n)(on [^\n]{4,120}wrote:|-{2,} ?original message ?-{2,}|_{5,}|from: [^\n]+\n(sent|date): )", re.I)
_CALENDAR_SUBJECT = re.compile(r"^(updated )?invitation: ", re.I)


@dataclass(frozen=True)
class Classification:
    kind: str | None  # a status, OTHER_COMMUNICATION, or None (not recruitment-related)
    confidence: float
    reason: str
    scores: tuple[tuple[str, float], ...] = ()

    @property
    def is_recruitment(self) -> bool:
        return self.kind is not None

    @property
    def auto_apply(self) -> bool:
        threshold = HIGH_IMPACT_THRESHOLD if self.kind in HIGH_IMPACT else AUTO_THRESHOLD
        return self.kind is not None and self.confidence >= threshold


def strip_quoted(text: str) -> str:
    """Only the newest part of an email: quoted earlier messages are removed."""
    match = _QUOTE_START.search(text)
    newest = text[:match.start()] if match else text
    return "\n".join(line for line in newest.splitlines() if not line.lstrip().startswith(">"))


def _confidence(top: float, second: float) -> float:
    conf = min(0.97, 0.45 + 0.12 * top)
    if second and second >= 0.75 * top:
        conf -= 0.2  # two categories are nearly as likely: let the user decide
    return round(max(conf, 0.05), 2)


def classify(subject: str, text: str) -> Classification:
    subject = " ".join((subject or "").split())
    body = strip_quoted(text or "")
    content = f"{subject}\n{body}"
    if _JOB_ALERT.search(content):
        return Classification(None, 0.9, "looks like a job alert or newsletter")
    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for kind, rules in _RULES.items():
        for pattern, weight in rules:
            target = subject if pattern.pattern.startswith("^") else content
            if m := pattern.search(target):
                scores[kind] = scores.get(kind, 0) + weight
                hits.setdefault(kind, []).append(m.group(0).strip()[:60])
    terms = len(set(t.lower() for t in _RECRUITMENT_TERMS.findall(content)))
    if not scores:
        if terms >= 2:
            return Classification(OTHER_COMMUNICATION, round(min(0.9, 0.4 + 0.1 * terms), 2),
                                  "mentions your application but fits no specific stage")
        return Classification(None, 0.8, "no recruitment wording found")
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (kind, top), second = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    conf = _confidence(top, second)
    if kind.startswith("Interview") and "interview" not in content.lower() and not _CALENDAR_SUBJECT.search(subject):
        conf = round(conf - 0.15, 2)  # a "call" or "meeting" may not be an interview
    reason = f"matched “{hits[kind][0]}”"
    if second and second >= 0.75 * top:
        reason += f"; also looks like {ranked[1][0]}"
    return Classification(kind, conf, reason, tuple((k, round(v, 2)) for k, v in ranked))
