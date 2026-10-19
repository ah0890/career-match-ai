"""Gmail and Microsoft Graph adapters: list recent messages and read the ones worth analysing.

Both use read-only access. Gmail is asked only for messages that look recruitment-related
(subject words, applicant-tracking senders, your applications' companies and contacts); Graph
cannot filter that finely, so its messages are filtered here and unrelated ones are dropped
straight away. Message bodies are converted to plain text, truncated and never stored.
"""

from __future__ import annotations

import base64
import re
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

import httpx

from src.jobs.normalization import html_to_text
from src.mail.matching import ATS_DOMAINS
from src.mail.types import MailItem

MAX_TEXT = 6000
RETRY_STATUSES = {429, 500, 502, 503, 504}
SUBJECT_WORDS = ("application", "applying", "applied", "interview", "offer", "assessment", "position", "role",
                 "candidate", "candidacy", "vacancy", "opportunity", "recruitment", "hiring")


class MailError(RuntimeError):
    """A temporary or provider problem; the message is safe to show and never contains tokens or URLs."""


class AuthExpired(MailError):
    """The mailbox must be reconnected (access revoked or refresh token expired)."""


class MailHttp:
    """Authorised requests with retries, Retry-After, back-off and one token refresh on 401."""

    def __init__(self, client: httpx.Client, get_token: Callable[[], str], refresh_token: Callable[[], str],
                 attempts: int = 3, sleep: Callable[[float], None] | None = None) -> None:
        self.client, self.get_token, self.refresh_token = client, get_token, refresh_token
        self.attempts, self._sleep = attempts, sleep

    def sleep(self, seconds: float) -> None:
        (self._sleep or time.sleep)(seconds)

    def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        refreshed = False
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.client.get(url, params=params,
                                           headers={"Authorization": f"Bearer {self.get_token()}", **(headers or {})})
            except httpx.HTTPError:
                if attempt == self.attempts:
                    raise MailError("The mail service could not be reached. It will be retried next sync.") from None
                self.sleep(2 ** attempt)
                continue
            if response.status_code == 401 and not refreshed:
                refreshed = True
                self.refresh_token()
                continue
            if response.status_code in (401, 403):
                raise AuthExpired("Access to this mailbox was refused. Reconnect it to continue.")
            if response.status_code in RETRY_STATUSES:
                if attempt == self.attempts:
                    raise MailError(f"The mail service is busy (HTTP {response.status_code}). "
                                    "It will be retried next sync.")
                retry_after = response.headers.get("Retry-After", "")
                self.sleep(min(float(retry_after), 30.0) if retry_after.isdigit() else 2 ** attempt)
                continue
            if response.status_code >= 400:
                raise MailError(f"The mail service returned an error (HTTP {response.status_code}).")
            return response.json()
        raise MailError("The mail service could not be reached.")


def _clip(text: str) -> str:
    """Tidy whitespace but keep line breaks: they show where quoted earlier messages start."""
    if not text:
        return ""
    lines = (" ".join(line.split()) for line in text.replace("\r", "").split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:MAX_TEXT]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# --- Gmail ----------------------------------------------------------------

class GmailProvider:
    BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, http: MailHttp, address: str | None = None) -> None:
        self.http, self.address = http, address

    def profile_address(self) -> str:
        return self.http.get(f"{self.BASE}/profile")["emailAddress"].lower()

    @staticmethod
    def query(since: datetime, companies: list[str], contacts: list[str]) -> str:
        terms = [f"subject:{w}" for w in SUBJECT_WORDS] + [f"from:{d}" for d in sorted(ATS_DOMAINS)]
        terms += [f'"{c}"' for c in companies[:40] if c and '"' not in c]
        terms += [f"from:{a} to:{a}" for a in contacts[:40] if a and " " not in a]  # {…} means any of these
        return (f"after:{int(since.timestamp())} -in:chats -category:promotions -category:social "
                f"-category:forums {{{' '.join(terms)}}}")

    def message_ids(self, since: datetime, companies: list[str], contacts: list[str], limit: int) -> Iterator[str]:
        params = {"q": self.query(since, companies, contacts), "maxResults": 100}
        seen = 0
        while True:
            page = self.http.get(f"{self.BASE}/messages", params=params)
            for m in page.get("messages", []):
                yield m["id"]
                seen += 1
                if seen >= limit:
                    return
            if not page.get("nextPageToken"):
                return
            params["pageToken"] = page["nextPageToken"]

    @staticmethod
    def _body(payload: dict) -> str:
        plain, html = [], []

        def walk(part: dict) -> None:
            data = part.get("body", {}).get("data")
            mime = part.get("mimeType", "")
            if data and mime in ("text/plain", "text/html"):
                text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
                (plain if mime == "text/plain" else html).append(text)
            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload)
        return "\n".join(plain) if plain else html_to_text("\n".join(html), max_chars=MAX_TEXT * 2)

    def message(self, provider_id: str) -> MailItem:
        m = self.http.get(f"{self.BASE}/messages/{provider_id}", params={"format": "full"})
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        name, sender = parseaddr(headers.get("from", ""))
        recipients = tuple(a.lower() for _, a in getaddresses([headers.get("to", ""), headers.get("cc", "")]) if a)
        try:
            sent_at = _aware(parsedate_to_datetime(headers["date"]))
        except (KeyError, TypeError, ValueError):
            sent_at = datetime.fromtimestamp(int(m.get("internalDate", "0")) / 1000, tz=timezone.utc)
        refs = tuple((headers.get("in-reply-to", "") + " " + headers.get("references", "")).split())
        outgoing = "SENT" in m.get("labelIds", []) or (self.address is not None and sender.lower() == self.address)
        return MailItem(
            provider_id=m["id"], thread_id=m.get("threadId"), internet_id=headers.get("message-id"),
            direction="out" if outgoing else "in", from_address=sender.lower() or None, from_name=name or None,
            to_addresses=recipients, subject=headers.get("subject", "")[:500],
            text=_clip(self._body(m.get("payload", {})) or m.get("snippet", "")), sent_at=sent_at,
            web_link=f"https://mail.google.com/mail/?authuser={self.address or ''}#all/{m['id']}", references=refs)


# --- Microsoft Graph --------------------------------------------------------

class OutlookProvider:
    BASE = "https://graph.microsoft.com/v1.0/me"
    FIELDS = ("id,conversationId,internetMessageId,subject,from,toRecipients,ccRecipients,receivedDateTime,"
              "sentDateTime,body,webLink")

    def __init__(self, http: MailHttp, address: str | None = None) -> None:
        self.http, self.address = http, address
        self._cache: dict[str, dict] = {}

    def profile_address(self) -> str:
        me = self.http.get(self.BASE, params={"$select": "mail,userPrincipalName"})
        return (me.get("mail") or me["userPrincipalName"]).lower()

    def message_ids(self, since: datetime, companies: list[str], contacts: list[str], limit: int) -> Iterator[str]:
        url: str | None = f"{self.BASE}/messages"
        params: dict | None = {"$filter": f"receivedDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                               "$select": self.FIELDS, "$top": 50, "$orderby": "receivedDateTime desc"}
        seen = 0
        while url:
            page = self.http.get(url, params=params, headers={"Prefer": 'outlook.body-content-type="text"'})
            for m in page.get("value", []):
                self._cache[m["id"]] = m  # the list already carries every field: no second request
                yield m["id"]
                seen += 1
                if seen >= limit:
                    return
            url, params = page.get("@odata.nextLink"), None

    def message(self, provider_id: str) -> MailItem:
        m = self._cache.pop(provider_id, None) or self.http.get(
            f"{self.BASE}/messages/{provider_id}", params={"$select": self.FIELDS},
            headers={"Prefer": 'outlook.body-content-type="text"'})
        sender = (m.get("from") or {}).get("emailAddress", {})
        address = (sender.get("address") or "").lower()
        recipients = tuple((r.get("emailAddress", {}).get("address") or "").lower()
                           for r in (m.get("toRecipients") or []) + (m.get("ccRecipients") or []))
        stamp = m.get("receivedDateTime") or m.get("sentDateTime")
        sent_at = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else datetime.now(timezone.utc)
        return MailItem(
            provider_id=m["id"], thread_id=m.get("conversationId"), internet_id=m.get("internetMessageId"),
            direction="out" if self.address and address == self.address else "in", from_address=address or None,
            from_name=sender.get("name"), to_addresses=tuple(r for r in recipients if r),
            subject=(m.get("subject") or "")[:500], text=_clip((m.get("body") or {}).get("content", "")),
            sent_at=_aware(sent_at), web_link=m.get("webLink"))
