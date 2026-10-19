"""Company facts from Wikidata (CC0) and summaries from Wikipedia (CC BY-SA 4.0).

Both are public Wikimedia APIs. Requests identify the app with a contact URL, are
spaced out and cached for a day, as Wikimedia's API etiquette asks. Values are copied
from the sources as stated, with any "point in time" the source gives; nothing is
estimated. A missing value is reported as not available.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from src.company.models import (
    WIKIDATA_LICENCE, WIKIPEDIA_LICENCE, CompanyCandidate, CompanyProfile, Fact, Source, Summary,
)
from src.jobs.models import safe_url
from src.providers.base import ProviderError, ProviderResponseError
from src.providers.http import ProviderHttp, RequestPolicy

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
POLICY = RequestPolicy(min_interval_s=1.0, daily_limit=500, cache_ttl_s=24 * 3600)
_ENTITY_RE = re.compile(r"^Q\d{1,12}$")

# Wikidata properties used for a company profile, in display order.
FACT_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("P452", "Industry"),
    ("P571", "Founded"),
    ("P159", "Headquarters"),
    ("P17", "Country"),
    ("P1128", "Employees"),
    ("P1056", "Products"),
    ("P414", "Stock exchange"),
    ("P127", "Owned by"),
    ("P749", "Parent organisation"),
)
LEADERSHIP_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("P169", "Chief executive officer"),
    ("P488", "Chairperson"),
    ("P112", "Founded by"),
)
_MAX_VALUES = 5  # per property, e.g. products


def _wikidata_source(entity_id: str) -> Source:
    return Source("Wikidata", f"https://www.wikidata.org/wiki/{entity_id}", WIKIDATA_LICENCE)


_LEGAL_SUFFIX = re.compile(
    r"(?:[,\s]+(?:inc|incorporated|ltd|limited|llc|llp|plc|gmbh|ag|sa|sas|s\.a|bv|nv|pty|pvt|corp|corporation|co)\.?)+$",
    re.I)


def without_legal_suffix(name: str) -> str:
    """ "Inseego Corp" → "Inseego"; "Example Devices Ltd." → "Example Devices". Other words are kept."""
    return _LEGAL_SUFFIX.sub("", " ".join(name.split())).strip(" ,")


def find_companies(name: str, http: ProviderHttp, limit: int = 7) -> tuple[list[CompanyCandidate], str]:
    """Search by the name as written; if nothing is found, retry without a legal suffix.

    Returns the candidates and the name that produced them, so the UI can say what was searched.
    """
    found = search_companies(name, http, limit)
    short = without_legal_suffix(name)
    if not found and short and short.lower() != " ".join(name.split()).lower() and len(short) >= 2:
        return search_companies(short, http, limit), short
    return found, " ".join(name.split())


def search_companies(name: str, http: ProviderHttp, limit: int = 7) -> list[CompanyCandidate]:
    name = " ".join(name.split())[:120]
    if len(name) < 2:
        return []
    data = http.get_json("wikidata", WIKIDATA_API, policy=POLICY, params={
        "action": "wbsearchentities", "search": name, "language": "en", "uselang": "en", "type": "item",
        "limit": limit, "format": "json",
    }).payload
    if not isinstance(data, dict) or not isinstance(data.get("search"), list):
        raise ProviderResponseError("Wikidata returned data in an unexpected format.")
    out = []
    for item in data["search"]:
        entity_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(entity_id, str) or not _ENTITY_RE.match(entity_id):
            continue
        label = item.get("label") or entity_id
        out.append(CompanyCandidate(entity_id, str(label), item.get("description") or None,
                                    f"https://www.wikidata.org/wiki/{entity_id}"))
    # Keep the source's order, but list likely organisations first; the user still chooses.
    return sorted(out, key=lambda c: not looks_like_organisation(c))


_ORG_WORDS = re.compile(
    r"(?i)\b(?:compan(?:y|ies)|corporation|conglomerate|manufacturer|firm|business|organi[sz]ation|bank|retailer|"
    r"agency|group|enterprise|start-?up|employer|university|college|hospital|ministry|department|airline|publisher|"
    r"provider|operator|maker|developer|brand|subsidiary|insurer|consultancy|consulting|charity|non-profit|"
    r"nonprofit|foundation|institute|school|government|authority|council|studio|laboratory|chain|cooperative)\b")


def looks_like_organisation(candidate: CompanyCandidate) -> bool:
    return bool(candidate.description and _ORG_WORDS.search(candidate.description))


def _entities(http: ProviderHttp, ids: list[str], props: str) -> dict[str, Any]:
    if not ids:
        return {}
    data = http.get_json("wikidata", WIKIDATA_API, policy=POLICY, params={
        "action": "wbgetentities", "ids": "|".join(ids[:50]), "props": props, "languages": "en", "format": "json",
    }).payload
    if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
        raise ProviderResponseError("Wikidata returned data in an unexpected format.")
    return data["entities"]


def _label(entity: dict[str, Any]) -> str | None:
    return (entity.get("labels", {}).get("en") or {}).get("value")


def _preferred(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Statements in Wikidata's own preference order: preferred rank first, deprecated dropped."""
    usable = [c for c in claims if c.get("rank") != "deprecated"]
    preferred = [c for c in usable if c.get("rank") == "preferred"]
    return preferred or usable


def format_time(value: dict[str, Any]) -> str | None:
    """Wikidata time ("+1998-09-04T00:00:00Z", precision 9/10/11) → "1998", "Sep 1998", "4 Sep 1998"."""
    m = re.match(r"^[+-](\d{1,4})-(\d{2})-(\d{2})", str(value.get("time", "")))
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    precision = value.get("precision", 9)
    if not 1 <= month <= 12 or year < 1:
        return str(year) if year else None
    month_name = datetime(2000, month, 1).strftime("%b")
    if precision >= 11 and day:
        return f"{day} {month_name} {year}"
    if precision == 10:
        return f"{month_name} {year}"
    return str(year)


def _qualifier_time(claim: dict[str, Any], prop: str) -> str | None:
    for q in claim.get("qualifiers", {}).get(prop, []):
        value = (q.get("datavalue") or {}).get("value")
        if isinstance(value, dict):
            return format_time(value)
    return None


def _snak_value(claim: dict[str, Any]) -> tuple[Any, Any] | None:
    snak = claim.get("mainsnak") or {}
    if snak.get("snaktype") != "value":
        return None
    dv = snak.get("datavalue") or {}
    return dv.get("type"), dv.get("value")


def _is_current(claim: dict[str, Any]) -> bool:
    """A statement with an end date ("P582") describes the past, e.g. a former CEO."""
    return not claim.get("qualifiers", {}).get("P582")


def get_company(entity_id: str, http: ProviderHttp) -> CompanyProfile:
    if not _ENTITY_RE.match(entity_id):
        raise ProviderError("That is not a valid company reference.")
    entity = _entities(http, [entity_id], "labels|descriptions|claims|sitelinks").get(entity_id)
    if not isinstance(entity, dict) or "missing" in entity:
        raise ProviderError("Wikidata has no record for this company.")
    claims: dict[str, list] = entity.get("claims", {})
    source = _wikidata_source(entity_id)

    # Collect referenced entity ids so their names can be fetched in one request.
    wanted: list[str] = []
    for prop, _ in (*FACT_PROPERTIES, *LEADERSHIP_PROPERTIES):
        for claim in _preferred(claims.get(prop, []))[:_MAX_VALUES]:
            v = _snak_value(claim)
            if v and v[0] == "wikibase-entityid" and isinstance(v[1], dict) and v[1].get("id"):
                wanted.append(v[1]["id"])
    names = {k: _label(v) for k, v in _entities(http, list(dict.fromkeys(wanted)), "labels").items()
             if isinstance(v, dict)}

    def values(prop: str, current_only: bool = False, date_prop: str = "P585") -> list[tuple[str, str | None]]:
        out = []
        for claim in _preferred(claims.get(prop, [])):
            if current_only and not _is_current(claim):
                continue
            v = _snak_value(claim)
            if v is None:
                continue
            kind, raw = v
            as_of = _qualifier_time(claim, date_prop)  # P585 "point in time"; P580 "start time"
            if kind == "wikibase-entityid" and isinstance(raw, dict):
                text = names.get(str(raw.get("id")))
            elif kind == "time" and isinstance(raw, dict):
                text = format_time(raw)
            elif kind == "quantity" and isinstance(raw, dict):
                try:
                    text = f"{int(float(raw.get('amount', ''))):,}"
                except ValueError:
                    text = None
            elif kind == "string":
                text = str(raw)
            else:
                text = None
            if text:
                out.append((text, as_of))
            if len(out) >= _MAX_VALUES:
                break
        return out

    facts: list[Fact] = []
    not_available: list[str] = []
    for prop, label in FACT_PROPERTIES:
        vals = values(prop)
        if prop == "P1128" and vals:  # headcount: keep the most recently dated figure only
            vals = [max(vals, key=lambda v: _sortable(v[1]))]
        if vals:
            as_of = vals[0][1] if len(vals) == 1 else None
            facts.append(Fact(label, ", ".join(v for v, _ in vals), source, as_of))
        else:
            not_available.append(label)
    leadership: list[Fact] = []
    for prop, label in LEADERSHIP_PROPERTIES:
        vals = values(prop, current_only=prop != "P112", date_prop="P580")
        if vals:
            leadership.append(Fact(label, ", ".join(v for v, _ in vals), source,
                                   f"since {vals[0][1]}" if len(vals) == 1 and vals[0][1] and prop != "P112" else None))
    website = next((safe_url(v) for v, _ in values("P856") if safe_url(v)), None)
    if not website:
        not_available.append("Official website")

    name = _label(entity) or entity_id
    summary, notes = None, []
    title = ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title")
    if title:
        try:
            summary = _wikipedia_summary(title, http)
        except ProviderError as exc:
            notes.append(f"The Wikipedia summary could not be loaded: {exc.message}")
    else:
        notes.append("There is no English Wikipedia article linked to this company.")
    notes.append("Wikidata and Wikipedia are edited by volunteers and can be incomplete or out of date. Check "
                 "important facts on the company's own website.")
    return CompanyProfile(
        entity_id=entity_id, name=name, description=(entity.get("descriptions", {}).get("en") or {}).get("value"),
        summary=summary, facts=tuple(facts), leadership=tuple(leadership), official_website=website,
        not_available=tuple(not_available), retrieved_at=datetime.now(timezone.utc), notes=tuple(notes),
    )


def _sortable(as_of: str | None) -> str:
    m = re.search(r"\d{4}", as_of or "")
    return m.group(0) if m else "0000"


def _wikipedia_summary(title: str, http: ProviderHttp) -> Summary | None:
    data = http.get_json("wikipedia", WIKIPEDIA_SUMMARY + quote(title.replace(" ", "_"), safe=""),
                         policy=POLICY).payload
    if not isinstance(data, dict):
        raise ProviderResponseError("Wikipedia returned data in an unexpected format.")
    if data.get("type") == "disambiguation":
        return None
    text = " ".join(str(data.get("extract") or "").split())
    url = safe_url(((data.get("content_urls") or {}).get("desktop") or {}).get("page")) \
        or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
    return Summary(text[:1500], Source("Wikipedia", url, WIKIPEDIA_LICENCE)) if text else None
