"""Helpers that turn provider fields into clean, normalised values."""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from src.jobs.models import EmploymentType

_BLOCK_TAGS = ("p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr")


def html_to_text(html: str | None, max_chars: int = 20000) -> str:
    """Convert provider HTML to plain text. Scripts and styles are dropped; nothing is executed."""
    if not html:
        return ""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MarkupResemblesLocatorWarning)
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
        tag.decompose()
    for li in soup.find_all("li"):
        li.insert_before("\n- ")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def clean_text(value: object, max_len: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:max_len] or None


def parse_datetime(value: object) -> datetime | None:
    """Parse ISO-8601 strings or Unix timestamps into aware UTC datetimes. Invalid input → None."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value <= 0:
                return None
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if (dt - datetime.now(timezone.utc)).total_seconds() > 86400:
        return None  # posting dates more than a day in the future are not trustworthy
    return dt


def parse_expiry(value: object) -> datetime | None:
    """Like parse_datetime, but future dates are expected and allowed."""
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str) and value.strip():
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return None


_COMPANY_SUFFIXES = re.compile(
    r"\b(incorporated|inc|ltd|limited|llc|llp|plc|gmbh|ag|sa|sas|bv|nv|pty|pvt|private|co|corp|corporation|"
    r"company|group|holdings|the)\b\.?", re.I)
_TITLE_NOISE = re.compile(
    r"\((?:remote|hybrid|on-?site|m/f/d|f/m/d|m/w/d|all genders)\)"
    r"|^\s*(?:remote|hybrid)\s*[-–:|]"
    r"|[-–:|]\s*(?:remote|hybrid|on-?site)\s*$", re.I)


def normalize_company(name: str | None) -> str:
    if not name:
        return ""
    name = _COMPANY_SUFFIXES.sub(" ", name.lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name).split())


def normalize_title(title: str) -> str:
    title = _TITLE_NOISE.sub(" ", title.lower())
    title = re.sub(r"\bsr\b\.?", "senior", title)
    title = re.sub(r"\bjr\b\.?", "junior", title)
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", title).split())


_TRACKING_PARAMS = re.compile(r"^(utm_|ref$|referrer$|source$|src$|fbclid$|gclid$)", re.I)


def canonical_url(url: str | None) -> str | None:
    """Comparable form of a URL: lowercase host, no tracking parameters, fragment or trailing slash."""
    if not url:
        return None
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)))
    host = (parts.hostname or "").lower().removeprefix("www.")
    return urlunsplit(("https", host, parts.path.rstrip("/"), query, ""))


_EMPLOYMENT_MAP = {
    "full_time": EmploymentType.FULL_TIME, "full-time": EmploymentType.FULL_TIME, "fulltime": EmploymentType.FULL_TIME,
    "full time": EmploymentType.FULL_TIME,
    "part_time": EmploymentType.PART_TIME, "part-time": EmploymentType.PART_TIME, "part time": EmploymentType.PART_TIME,
    "contract": EmploymentType.CONTRACT, "contractor": EmploymentType.CONTRACT, "freelance": EmploymentType.CONTRACT,
    "temporary": EmploymentType.TEMPORARY, "temp": EmploymentType.TEMPORARY,
    "internship": EmploymentType.INTERNSHIP, "intern": EmploymentType.INTERNSHIP,
}


def parse_employment_type(value: object) -> EmploymentType:
    if not isinstance(value, str):
        return EmploymentType.UNKNOWN
    return _EMPLOYMENT_MAP.get(value.strip().lower(), EmploymentType.UNKNOWN)


def positive_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
