"""Rule-based CV review: category scores out of 100, concrete suggested changes and questions.

Every suggestion only rewords, reformats or reorders what the CV already states. Anything that
would need a new fact (a figure, a date, a skill) becomes a *question* for the user instead —
the engine never fills in missing information.

Scores are guidance from transparent rules, not a prediction of hiring success.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from src.cv.ats import score_band
from src.cv.parsing import ACTION_VERBS, DATE_RANGE_RE, EMAIL_RE, extract_date_ranges, estimate_experience_years
from src.matching.text import content_stems
from src.workspace.document import CVDocument, Entry, Item, Section

Priority = Literal["High", "Medium", "Low"]
Action = Literal["replace", "add", "remove", "dates", "reorder", "advice"]

SCORE_NOTE = ("Scores are guidance from transparent writing and formatting rules. They are not a measure of how "
              "an employer or applicant tracking system will rank you, and they cannot predict hiring success.")

CATEGORIES: dict[str, tuple[str, float]] = {  # key → (label, weight in the overall score)
    "language": ("Language & grammar", 20),
    "structure": ("Structure & ATS readability", 20),
    "summary": ("Professional summary", 10),
    "experience": ("Experience & achievements", 25),
    "skills": ("Skills, education & certifications", 15),
    "relevance": ("Relevance to your target roles", 10),
}
BULLET_KINDS = ("experience", "projects", "volunteering")
_PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


@dataclass
class Suggestion:
    key: str  # stable identity within one review, e.g. "text:<item id>"
    category: str
    priority: Priority
    action: Action
    section_title: str
    original: str
    proposed: str
    explanation: str
    benefit: str
    section_id: str | None = None
    entry_id: str | None = None
    item_id: str | None = None
    verification: str | None = None  # what the user must confirm is true before it is used
    warnings: str | None = None
    payload: dict | None = None
    source: str = "rules"


@dataclass(frozen=True)
class QuestionSpec:
    key: str
    question: str
    hint: str
    essential: bool
    target: str  # contact.email · entry:<id>:dates · entry:<id>:add · item:<id> · section:<kind>


@dataclass(frozen=True)
class CategoryScore:
    key: str
    label: str
    score: int | None  # None = not assessed
    findings: tuple[str, ...] = ()


@dataclass
class ReviewReport:
    score: int
    band: str
    categories: tuple[CategoryScore, ...]
    suggestions: list[Suggestion]
    questions: list[QuestionSpec]
    note: str = SCORE_NOTE
    target_roles: tuple[str, ...] = field(default_factory=tuple)


# --- word lists -----------------------------------------------------------------------------

MISSPELLINGS = {
    "accomodate": "accommodate", "accomodated": "accommodated", "acheive": "achieve", "acheived": "achieved",
    "acheivement": "achievement", "acheivements": "achievements", "acknowledgement": "acknowledgement",
    "adress": "address", "analysys": "analysis", "begining": "beginning", "beleive": "believe",
    "buisness": "business", "calender": "calendar", "collegue": "colleague", "collegues": "colleagues",
    "comittee": "committee", "commited": "committed", "communciation": "communication",
    "comunication": "communication", "concious": "conscious", "definately": "definitely",
    "developement": "development", "enviroment": "environment", "enviromental": "environmental",
    "excercise": "exercise", "existance": "existence", "experiance": "experience", "experince": "experience",
    "goverment": "government", "guidence": "guidance", "independant": "independent", "knowlege": "knowledge",
    "liase": "liaise", "liasing": "liaising", "maintainance": "maintenance", "maintenence": "maintenance",
    "managment": "management", "occured": "occurred", "occurence": "occurrence", "oppurtunity": "opportunity",
    "persue": "pursue", "proffesional": "professional", "profesional": "professional",
    "recieve": "receive", "recieved": "received", "recomend": "recommend", "recomended": "recommended",
    "refered": "referred", "relevent": "relevant", "responsibilty": "responsibility",
    "responsibilites": "responsibilities", "seperate": "separate", "seperately": "separately",
    "sucess": "success", "succesful": "successful", "sucessful": "successful", "succesfully": "successfully",
    "sucessfully": "successfully", "supervisior": "supervisor", "tecnical": "technical", "teh": "the",
    "untill": "until", "wich": "which", "wrok": "work", "achived": "achieved", "implimented": "implemented",
    "impliment": "implement", "stratergy": "strategy", "perfomance": "performance", "proccess": "process",
    "proccesses": "processes", "requirments": "requirements", "comission": "commission",
}
_MISSPELLING_RE = re.compile(r"\b(" + "|".join(sorted(MISSPELLINGS, key=len, reverse=True)) + r")\b", re.I)

# Plain replacements that never change meaning.
FILLERS: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"\bin order to\b", re.I), "to", "“in order to” → “to”"),
    (re.compile(r"\bon a daily basis\b", re.I), "daily", "“on a daily basis” → “daily”"),
    (re.compile(r"\bon a weekly basis\b", re.I), "weekly", "“on a weekly basis” → “weekly”"),
    (re.compile(r"\bon a monthly basis\b", re.I), "monthly", "“on a monthly basis” → “monthly”"),
    (re.compile(r"\butili[sz]ed\b", re.I), "used", "“utilised” → “used”"),
    (re.compile(r"\butili[sz]ing\b", re.I), "using", "“utilising” → “using”"),
    (re.compile(r"\butili[sz]e\b", re.I), "use", "“utilise” → “use”"),
    (re.compile(r"\bwith regards? to\b", re.I), "regarding", "“with regard to” → “regarding”"),
    (re.compile(r"^successfully\s+", re.I), "", "dropped the opening “Successfully”"),
)

CLICHES = ("hard-working", "hardworking", "team player", "results-driven", "results driven", "go-getter",
           "detail-oriented", "detail oriented", "self-motivated", "self motivated", "dynamic", "passionate",
           "think outside the box", "synergy", "best of breed", "go-to person")

# "Responsible for managing X" → "Managed X": the same claim, stated directly.
_WEAK_OPENER = re.compile(
    r"^(?:(?:I\s+)?(?:was|am|have been)\s+)?(?:responsible for|in charge of|duties included|tasked with|"
    r"accountable for)\s+(?P<verb>[a-z]+ing)\b", re.I)
# Openers that hide what the person actually did; rewriting them could overstate the role.
_VAGUE_OPENER = re.compile(r"^(?:(?:I\s+)?(?:was\s+)?)?(?:involved in|worked on|helped(?: to| with)?|assisted(?: with| in)?|"
                           r"participated in|responsible for|exposure to)\b", re.I)
_FIRST_PERSON_LEAD = re.compile(r"^(?:I|We)\s+(?:have\s+|had\s+)?(?P<rest>[a-z].*)$", re.I)
_FIRST_PERSON_ANY = re.compile(r"\b(I|me|my|myself)\b")
_QUANTIFIED = re.compile(r"\d|%|\bpercent\b", re.I)
_LONG_WORDS = 35

_IRREGULAR_PAST = {
    "leading": "led", "building": "built", "running": "ran", "writing": "wrote", "making": "made",
    "overseeing": "oversaw", "teaching": "taught", "selling": "sold", "setting": "set", "cutting": "cut",
    "bringing": "brought", "holding": "held", "driving": "drove", "giving": "gave", "taking": "took",
    "meeting": "met", "keeping": "kept", "buying": "bought", "speaking": "spoke", "choosing": "chose",
    "growing": "grew", "winning": "won", "spending": "spent", "sending": "sent", "finding": "found",
    "telling": "told", "thinking": "thought", "understanding": "understood", "putting": "put",
    "rewriting": "rewrote", "undertaking": "undertook", "seeing": "saw", "doing": "did", "having": "had",
    "beginning": "began", "forecasting": "forecast", "shutting": "shut",
}


def past_tense(gerund: str) -> str | None:
    """managing → managed, leading → led, planning → planned. None when unsure."""
    word = gerund.lower()
    if word in _IRREGULAR_PAST:
        return _IRREGULAR_PAST[word]
    if not word.endswith("ing") or len(word) < 5:
        return None
    stem = word[:-3]
    if stem.endswith("y") and len(stem) > 1 and stem[-2] not in "aeiou":
        return stem[:-1] + "ied"
    if stem.endswith("e"):
        return stem + "d"
    return stem + "ed"


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _match_case(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    return _cap(replacement) if original[:1].isupper() else replacement


# --- per-item text fixes ----------------------------------------------------------------------

@dataclass
class _Fix:
    text: str
    reasons: list[str] = field(default_factory=list)
    kinds: set[str] = field(default_factory=set)


def _spelling(fix: _Fix) -> None:
    found: list[str] = []

    def repl(m: re.Match) -> str:
        right = _match_case(m.group(0), MISSPELLINGS[m.group(0).lower()])
        found.append(f"“{m.group(0)}” → “{right}”")
        return right

    fix.text = _MISSPELLING_RE.sub(repl, fix.text)
    if found:
        fix.reasons.append("Spelling: " + ", ".join(found))
        fix.kinds.add("spelling")


def _first_person(fix: _Fix) -> None:
    m = _FIRST_PERSON_LEAD.match(fix.text)
    if m and not re.match(r"(?i)(am|was|have been)\b", m.group("rest")):
        fix.text = _cap(m.group("rest"))
        fix.reasons.append("Removed the opening “I” — CV bullets are conventionally written without pronouns")
        fix.kinds.add("first_person")


def _weak_opener(fix: _Fix) -> None:
    m = _WEAK_OPENER.match(fix.text)
    if not m or (past := past_tense(m.group("verb"))) is None:
        return
    fix.text = _cap(past) + fix.text[m.end():]
    fix.reasons.append(f"Starts with what you did (“{_cap(past)}”) instead of “{m.group(0)[:-len(m.group('verb'))].strip()}”")
    fix.kinds.add("weak_opener")


def _fillers(fix: _Fix) -> None:
    for pattern, repl, reason in FILLERS:
        new = pattern.sub(lambda m: _match_case(m.group(0), repl) if repl else "", fix.text)
        if new != fix.text:
            fix.text = _cap(new.strip())
            fix.reasons.append(reason)
            fix.kinds.add("filler")


def _punctuation(fix: _Fix, end_with_period: bool | None) -> None:
    text = re.sub(r"\s{2,}", " ", fix.text).replace(" ,", ",").replace(" .", ".").strip()
    text = re.sub(r",(?=[A-Za-z])", ", ", text) if re.search(r"[a-z],[A-Za-z]{3,}", text) else text
    text = _cap(text)
    if end_with_period is True and text and text[-1] not in ".!?:":
        text += "."
    elif end_with_period is False and text.endswith(".") and not text.endswith(("etc.", "Ltd.", "Inc.", "...")):
        text = text[:-1]
    if text != fix.text:
        changed_end = text.rstrip(".") == fix.text.strip().rstrip(".") and text != fix.text.strip()
        fix.reasons.append("Consistent end punctuation" if changed_end else "Tidied spacing, punctuation and capitals")
        fix.kinds.add("punctuation")
        fix.text = text


# --- dates ---------------------------------------------------------------------------------

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_TOKEN = re.compile(r"(?i)^(?P<m>[a-z]{3,9})\.?\s+(?P<y>\d{4})$")
_NUMERIC_TOKEN = re.compile(r"^(?P<m>\d{1,2})[/.-](?P<y>\d{4})$")
_PRESENT = re.compile(r"(?i)^(present|current|now|today|date|ongoing)$")


def _date_token(token: str) -> tuple[str, str] | None:
    """(style, normalised) for one side of a range: 'Jan 2019', '2019' or 'Present'."""
    token = token.strip().rstrip(".")
    if _PRESENT.match(token):
        return "present", "Present"
    if re.fullmatch(r"\d{4}", token):
        return "year", token
    if m := _MONTH_TOKEN.match(token):
        month = m.group("m")[:3].lower()
        if month in _MONTHS:
            style = "month-short" if len(m.group("m")) <= 4 else "month-long"
            return style, f"{month.title()} {m.group('y')}"
    if m := _NUMERIC_TOKEN.match(token):
        n = int(m.group("m"))
        if 1 <= n <= 12:
            return "numeric", f"{_MONTHS[n - 1].title()} {m.group('y')}"
    return None


def _dates_signature(dates: str) -> tuple[tuple[str, str], str] | None:
    """((style, separator), normalised) for a date range written in an entry header."""
    m = DATE_RANGE_RE.search(dates or "")
    if not m:
        return None
    start, end = _date_token(m.group("start")), _date_token(m.group("end"))
    if start is None or end is None:
        return None
    sep = dates[m.end("start"):m.start("end")].strip().lower()
    style = start[0] if start[0] != "year" else (end[0] if end[0] not in ("present", "year") else "year")
    normalised = dates[:m.start()] + f"{start[1]} – {end[1]}" + dates[m.end():]
    return (style, sep), normalised.strip()


# --- the review ------------------------------------------------------------------------------

def _bullet_items(doc: CVDocument) -> list[tuple[Section, Entry, Item]]:
    return [(s, e, i) for s, e, i in doc.iter_items(include_hidden=False) if s.kind in BULLET_KINDS]


def _first_word(text: str) -> str:
    words = text.split()
    return re.sub(r"[^a-z]", "", words[0].lower()) if words else ""


def _text_suggestions(doc: CVDocument) -> list[Suggestion]:
    bullets = _bullet_items(doc)
    ends = Counter(i.text.rstrip().endswith(".") for _, _, i in bullets)
    period = None if len(bullets) < 3 or len(ends) < 2 else ends.most_common(1)[0][0]
    out = []
    for s, e, i in doc.iter_items(include_hidden=False):
        if s.kind in ("skills", "languages", "interests", "references"):
            continue
        fix = _Fix(i.text)
        _spelling(fix)
        if s.kind in BULLET_KINDS:
            _first_person(fix)
            _weak_opener(fix)
            _fillers(fix)
            _punctuation(fix, period)
        elif s.kind == "summary":
            _fillers(fix)
            _punctuation(fix, None)
        if fix.text == i.text or not fix.text:
            continue
        if "spelling" in fix.kinds:
            category, priority, benefit = "language", "High", "Spelling mistakes are among the first things readers notice."
        elif "weak_opener" in fix.kinds:
            category, priority, benefit = ("experience", "Medium",
                                           "Starting with an action verb shows your contribution at a glance.")
        elif "first_person" in fix.kinds:
            category, priority, benefit = "language", "Medium", "A consistent, professional CV voice."
        elif "filler" in fix.kinds:
            category, priority, benefit = "language", "Low", "Shorter, clearer sentences are easier to scan."
        else:
            category, priority, benefit = "language", "Low", "Consistent formatting looks careful and professional."
        where = s.title + (f" · {e.title}" if e.title else "")
        out.append(Suggestion(
            f"text:{i.id}", category, priority, "replace", where, i.text, fix.text,
            "; ".join(fix.reasons) + ". The meaning and every fact stay the same.", benefit,
            section_id=s.id, entry_id=e.id, item_id=i.id))
    return out


def _duplicate_suggestions(doc: CVDocument) -> list[Suggestion]:
    out = []
    for s in doc.sections:
        seen: dict[str, Item] = {}
        for e in s.entries:
            for i in e.items:
                if i.hidden:
                    continue
                norm = " ".join(re.sub(r"[^\w\s]", "", i.text.lower()).split())
                if norm in seen and len(norm) > 2:
                    out.append(Suggestion(
                        f"duplicate:{i.id}", "skills" if s.kind == "skills" else "experience", "Medium", "remove",
                        s.title, i.text, "", "This line repeats one that appears earlier in the same section. "
                        "It is only left out of the CV — you can bring it back at any time.",
                        "Removing repetition makes room for distinct achievements.",
                        section_id=s.id, entry_id=e.id, item_id=i.id))
                else:
                    seen[norm] = i
    return out


def _date_suggestions(doc: CVDocument) -> tuple[list[Suggestion], bool]:
    entries = [(s, e) for s in doc.sections if s.kind in ("experience", "education", *BULLET_KINDS)
               for e in s.entries if e.dates and not e.hidden]
    signatures = {e.id: sig for s, e in entries if (sig := _dates_signature(e.dates))}
    styles = Counter(sig[0][0] for sig in signatures.values() if sig[0][0] != "year")
    seps = Counter(sig[0][1] for sig in signatures.values())
    if len(styles) <= 1 and len(seps) <= 1:
        return [], False
    out = []
    for s, e in entries:
        sig = signatures.get(e.id)
        if sig and sig[1] != e.dates:
            out.append(Suggestion(
                f"dates:{e.id}", "structure", "Low", "dates", f"{s.title} · {e.title or e.organization}",
                e.dates, sig[1], "Your CV writes dates in more than one way. This uses one format "
                "(“Jan 2019 – Present”) everywhere; the dates themselves are unchanged.",
                "Consistent dates are easier to read and parse.", section_id=s.id, entry_id=e.id))
    return out, bool(out)


def _summary_draft(doc: CVDocument) -> str | None:
    """A factual starting point from the CV's own headline, dates and skills — or None."""
    exp = doc.section("experience")
    title = doc.contact.headline or (exp.entries[0].title if exp and exp.entries else "")
    if not title:
        return None
    years = estimate_experience_years(extract_date_ranges(doc.to_text()))
    skills_section = doc.section("skills")
    skills = list(dict.fromkeys(i.text for e in (skills_section.entries if skills_section else []) for i in e.items
                                if not i.hidden))[:4]
    parts = [f"{title} with {int(years)}+ years of experience" if years >= 1 else title]
    if skills:
        parts.append(", skilled in " + (", ".join(skills[:-1]) + " and " + skills[-1] if len(skills) > 1
                                           else skills[0]))
    return "".join(parts) + "."


def _cliches(text: str) -> list[str]:
    lowered = text.lower()
    return [c for c in CLICHES if re.search(rf"\b{re.escape(c)}\b", lowered)]


def review(doc: CVDocument, target_roles: tuple[str, ...] | list[str] = ()) -> ReviewReport:
    """Analyse a CV. Pure function: it never changes ``doc``."""
    target_roles = tuple(r.strip() for r in target_roles if r and r.strip())
    suggestions = _text_suggestions(doc) + _duplicate_suggestions(doc)
    date_suggestions, mixed_dates = _date_suggestions(doc)
    suggestions += date_suggestions
    questions: list[QuestionSpec] = []
    findings: dict[str, list[str]] = {k: [] for k in CATEGORIES}

    def advice(key, category, priority, where, explanation, benefit, original="", **ids) -> None:
        suggestions.append(Suggestion(key, category, priority, "advice", where, original, "", explanation, benefit,
                                      **ids))

    kinds = Counter(s.kind for s in doc.sections if not s.hidden)
    text_fixes = [s for s in suggestions if s.key.startswith("text:")]
    spelling = sum("Spelling" in s.explanation for s in text_fixes)
    fixed = {s.item_id: s.proposed for s in text_fixes}
    first_person_left = [i for _, _, i in _bullet_items(doc) if _FIRST_PERSON_ANY.search(fixed.get(i.id, i.text))]

    # --- language ----------------------------------------------------------------------------
    language = 100 - min(45, 15 * spelling) - min(20, 4 * len(first_person_left)) \
        - min(25, 3 * (len(text_fixes) - spelling))
    if spelling:
        findings["language"].append(f"{spelling} line(s) with spelling mistakes")
    if first_person_left:
        findings["language"].append(f"{len(first_person_left)} bullet(s) still use “I”, “me” or “my”")
        advice("first_person", "language", "Low", "Experience",
               "Some bullets use “I”, “me” or “my” in the middle of the sentence. Rephrase them without pronouns, "
               "for example “Mentored my team” → “Mentored a team of four” (only with numbers you can support).",
               "A consistent, professional voice.", original="\n".join(i.text for i in first_person_left[:3]))
    if len(text_fixes) - spelling:
        findings["language"].append(f"{len(text_fixes) - spelling} line(s) can be tightened or tidied")

    # --- structure ------------------------------------------------------------------------------
    c = doc.contact
    structure = 100
    if not c.name:
        structure -= 15
        questions.append(QuestionSpec("contact.name", "What is your full name as it should appear on your CV?", "",
                                      True, "contact.name"))
    if not c.email or not EMAIL_RE.fullmatch(c.email):
        structure -= 25
        findings["structure"].append("No email address found")
        questions.append(QuestionSpec("contact.email", "Which email address should employers use?",
                                      "Use a professional address you check often.", True, "contact.email"))
    if not c.phone:
        structure -= 10
        findings["structure"].append("No phone number found")
        questions.append(QuestionSpec("contact.phone", "Which phone number should employers call?",
                                      "Include the country code if you apply abroad.", True, "contact.phone"))
    if not c.location:
        questions.append(QuestionSpec("contact.location", "Where are you based (city and country)?",
                                      "Many employers filter by location. Leave blank to keep it off your CV.", False,
                                      "contact.location"))
    if not any("linkedin" in link.lower() for link in c.links):
        questions.append(QuestionSpec("contact.links", "Do you have a LinkedIn profile or portfolio link to add?",
                                      "Optional. Paste the full address.", False, "contact.links"))
    if not kinds["experience"]:
        structure -= 15
        findings["structure"].append("No experience section was recognised")
    undated = [(s, e) for s in doc.sections if s.kind == "experience" and not s.hidden
               for e in s.entries if not e.hidden and not e.dates]
    if undated:
        structure -= min(30, 10 * len(undated))
        findings["structure"].append(f"{len(undated)} role(s) without dates")
        for s, e in undated:
            questions.append(QuestionSpec(
                f"dates:{e.id}", f"When did you work as {e.title or 'this role'}"
                + (f" at {e.organization}" if e.organization else "") + "?",
                "For example “Jan 2020 – Mar 2023”. Recruiters and ATS software expect dates for every role.", True,
                f"entry:{e.id}:dates"))
    custom = [s for s in doc.sections if s.kind == "custom" and not s.hidden]
    for s in custom:
        structure -= 5
        advice(f"heading:{s.id}", "structure", "Low", s.title,
               f"“{s.title}” is not a standard CV heading. If one of Experience, Projects, Certifications, Awards or "
               "Additional Information fits, renaming it helps ATS software file the content correctly.",
               "Standard headings are read reliably by ATS software.", section_id=s.id)
    words = doc.word_count()
    if words > 1100:
        structure -= 10
        findings["structure"].append(f"{words} words — long for most roles")
        advice("length", "structure", "Medium", "Whole CV",
               f"Your CV has about {words} words. Two pages (roughly 500–900 words) suit most roles; consider leaving "
               "out older or less relevant detail.", "A focused CV is read more thoroughly.")
    elif words < 150:
        structure -= 10
        findings["structure"].append(f"Only {words} words")
    if mixed_dates:
        structure -= 10
        findings["structure"].append("Dates are written in more than one format")
    structure = max(0, structure)

    # --- summary --------------------------------------------------------------------------------
    summary_section = doc.section("summary")
    summary_text = " ".join(i.text for e in (summary_section.entries if summary_section else []) for i in e.items
                            if not i.hidden)
    if not summary_text:
        summary = 30
        findings["summary"].append("No professional summary")
        draft = _summary_draft(doc)
        if draft:
            suggestions.append(Suggestion(
                "summary:add", "summary", "High", "add", "Professional Summary", "", draft,
                "A two-line summary tells a reader who you are before they scan the details. This draft uses only "
                "your CV's own headline, dates and skills — edit it so it sounds like you.",
                "Recruiters often decide within seconds whether to keep reading.",
                verification="Check the summary is accurate (title, years and skills) before accepting it."))
        questions.append(QuestionSpec(
            "summary", "In one or two sentences, what do you want employers to know about you?",
            "Your strongest experience and the kind of role you want. This becomes your professional summary.",
            False, "section:summary"))
    else:
        summary = 100
        n = len(summary_text.split())
        if n > 90:
            summary -= 20
            findings["summary"].append(f"{n} words — long for a summary")
            advice("summary:long", "summary", "Medium", "Professional Summary",
                   "Your summary is long. Two to four lines (about 40–80 words) is easier to read.",
                   "A short summary is actually read.", original=summary_text)
        elif n < 12:
            summary -= 15
            findings["summary"].append("Very short summary")
        if found := _cliches(summary_text):
            summary -= min(30, 10 * len(found))
            findings["summary"].append("Generic phrases: " + ", ".join(found))
            advice("summary:cliches", "summary", "Medium", "Professional Summary",
                   "Phrases like " + ", ".join(f"“{x}”" for x in found) + " appear on many CVs and tell a reader "
                   "little. Replace them with something specific you have done.",
                   "Specific evidence is more convincing than adjectives.", original=summary_text)

    # --- experience -----------------------------------------------------------------------------
    bullets = _bullet_items(doc)
    fixed_text = {s.item_id: s.proposed for s in text_fixes}
    if bullets:
        firsts = [_first_word(fixed_text.get(i.id, i.text)) for _, _, i in bullets]
        action_ratio = sum(w in ACTION_VERBS for w in firsts) / len(bullets)
        quantified = [i for _, _, i in bullets if _QUANTIFIED.search(i.text)]
        quant_ratio = len(quantified) / len(bullets)
        long = [(s, e, i) for s, e, i in bullets if len(i.text.split()) > _LONG_WORDS]
        repeated = [(w, n) for w, n in Counter(firsts).items() if n >= 3 and w]
        experience = round(45 * min(1, action_ratio / 0.8) + 35 * min(1, quant_ratio / 0.5)
                           + 10 * (1 - min(1, len(long) / 3)) + 10 * (0 if repeated else 1))
        if action_ratio < 0.8:
            findings["experience"].append(f"{round(100 * action_ratio)}% of bullets start with an action verb")
        findings["experience"].append(f"{len(quantified)} of {len(bullets)} bullets include a measurable result")
        for s, e, i in bullets:
            if _VAGUE_OPENER.match(i.text) and not _WEAK_OPENER.match(i.text):
                advice(f"vague:{i.id}", "experience", "Medium", s.title + (f" · {e.title}" if e.title else ""),
                       "This bullet says you were involved but not what you did. Describe your own part with an "
                       "action verb — only you know what that was, so this is not rewritten automatically.",
                       "Clear ownership is what employers look for.", original=i.text, section_id=s.id,
                       entry_id=e.id, item_id=i.id)
                questions.append(QuestionSpec(
                    f"own:{i.id}", f"What exactly did you do here? “{i.text[:120]}”",
                    "Rewrite the line starting with what you did, e.g. “Designed…”, “Tested…”. Your answer replaces "
                    "the line.", False, f"item:{i.id}"))
        if quant_ratio < 0.5:
            candidates = [(s, e, i) for s, e, i in bullets if not _QUANTIFIED.search(i.text)
                          and _first_word(fixed_text.get(i.id, i.text)) in ACTION_VERBS][:3]
            for s, e, i in candidates:
                questions.append(QuestionSpec(
                    f"measure:{i.id}", f"Can you add a measurable result to: “{fixed_text.get(i.id, i.text)[:140]}”?",
                    "For example time saved, cost reduced, volume handled or team size. Only use figures you can "
                    "support in an interview. Your answer replaces the line.", False, f"item:{i.id}"))
        for s, e, i in long:
            advice(f"long:{i.id}", "experience", "Low", s.title + (f" · {e.title}" if e.title else ""),
                   f"This bullet has {len(i.text.split())} words. Splitting it, or keeping only the result, makes it "
                   "easier to scan.", "Short bullets are read; long ones are skimmed.", original=i.text,
                   section_id=s.id, entry_id=e.id, item_id=i.id)
        for w, n in repeated:
            advice(f"repeat:{w}", "experience", "Low", "Experience",
                   f"{n} bullets start with “{w.title()}”. Varying the verb (where it is accurate) reads better.",
                   "Varied, precise verbs keep the reader's attention.")
            findings["experience"].append(f"“{w.title()}” starts {n} bullets")
    else:
        experience = 25 if kinds["experience"] else 0
        findings["experience"].append("No achievement bullets found")
    roles = [(s, e) for s in doc.sections if s.kind == "experience" for e in s.entries if not e.hidden]
    for s, e in roles:
        visible = [i for i in e.items if not i.hidden]
        if not visible:
            questions.append(QuestionSpec(
                f"add:{e.id}", f"What did you achieve as {e.title or 'this role'}"
                + (f" at {e.organization}" if e.organization else "") + "?",
                "Two or three lines, each starting with what you did. Leave blank to keep the role as it is.",
                False, f"entry:{e.id}:add"))
        elif len(visible) > 7:
            advice(f"many:{e.id}", "experience", "Low", f"{s.title} · {e.title}",
                   f"This role has {len(visible)} bullets. Keeping the 4–6 most relevant makes the strongest ones "
                   "stand out (you can hide the rest per version).", "Focus on what matters most for the job.",
                   section_id=s.id, entry_id=e.id)

    # --- skills & education ---------------------------------------------------------------------
    skills_section = doc.section("skills")
    skill_items = [i for e in (skills_section.entries if skills_section else []) for i in e.items if not i.hidden]
    skills = 0
    if skill_items:
        skills += 45
        skills += 20 if 5 <= len(skill_items) <= 40 else 8
        if len(skill_items) > 40:
            advice("skills:many", "skills", "Low", "Skills",
                   f"{len(skill_items)} skills are listed. Keeping the most relevant ones makes them easier to find.",
                   "Readers notice a focused skills list.")
    else:
        findings["skills"].append("No skills section")
        questions.append(QuestionSpec("skills", "Which key skills, tools or methods should your CV list?",
                                      "Comma-separated, only skills you can discuss confidently.", False,
                                      "section:skills"))
        advice("skills:missing", "skills", "High", "Skills",
               "Add a short skills section. Many ATS searches match on skill keywords.",
               "Makes your strengths easy to find by people and software.")
    if kinds["education"]:
        skills += 25
    else:
        findings["skills"].append("No education section")
        questions.append(QuestionSpec("education", "What is your highest qualification (degree, institution, year)?",
                                      "Leave blank if you prefer not to list education.", False, "section:education"))
    skills += 10 if not any(s.key.startswith("duplicate:") and s.category == "skills" for s in suggestions) else 0
    if kinds["certifications"]:
        findings["skills"].append(f"{sum(len(e.items) for s in doc.sections if s.kind == 'certifications' for e in s.entries)} certification(s) listed")

    # --- relevance ------------------------------------------------------------------------------
    relevance: int | None = None
    if target_roles:
        cv_stems = set(content_stems(doc.to_text()))
        head_stems = set(content_stems(" ".join([doc.contact.headline, summary_text]
                                                + [e.title for _, e in roles])))
        role_scores = []
        for role in target_roles:
            stems = set(content_stems(role))
            if not stems:
                continue
            in_cv, in_head = len(stems & cv_stems) / len(stems), len(stems & head_stems) / len(stems)
            role_scores.append(60 * in_cv + 40 * in_head)
            if in_head < 0.5:
                advice(f"role:{role.lower()}", "relevance", "Medium", "Headline & summary",
                       f"Your headline, summary and job titles do not mention “{role}”. If it accurately describes "
                       "you, say so in your headline or summary — never change a past job title.",
                       "Readers check quickly whether you fit the role they are hiring for.")
        if role_scores:
            relevance = round(max(role_scores))
            findings["relevance"].append(f"Best fit: {relevance}/100 for " + ", ".join(target_roles))

    scores = {"language": max(0, language), "structure": structure, "summary": max(0, summary),
              "experience": max(0, experience), "skills": min(100, skills), "relevance": relevance}
    assessed = {k: v for k, v in scores.items() if v is not None}
    total_weight = sum(CATEGORIES[k][1] for k in assessed)
    overall = round(sum(CATEGORIES[k][1] * v for k, v in assessed.items()) / total_weight) if total_weight else 0
    categories = tuple(CategoryScore(k, CATEGORIES[k][0], scores[k], tuple(findings[k])) for k in CATEGORIES)
    suggestions.sort(key=lambda s: (_PRIORITY_ORDER[s.priority], s.action == "advice"))
    unique: dict[str, QuestionSpec] = {}
    for q in questions:
        unique.setdefault(q.key, q)
    ordered_q = sorted(unique.values(), key=lambda q: not q.essential)
    return ReviewReport(overall, score_band(overall), categories, suggestions, ordered_q, target_roles=target_roles)
