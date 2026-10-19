"""A fake Gmail / Microsoft Graph / OAuth service for sync tests (httpx.MockTransport). All content is fictional."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs

import httpx

ME = "alex@example.com"


@dataclass
class FakeMail:
    id: str
    thread: str
    sender: str
    to: str
    subject: str
    body: str
    when: datetime
    sent: bool = False
    message_id: str | None = None
    in_reply_to: str | None = None
    sender_name: str | None = None


@dataclass
class FakeMailbox:
    messages: list[FakeMail] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    token_calls: list[dict] = field(default_factory=list)
    fail_refresh: bool = False
    unauthorized_once: bool = False
    statuses: list[int] = field(default_factory=list)  # forced responses for the next requests (e.g. 429, 503)
    page_size: int = 100

    # --- Gmail -------------------------------------------------------------
    def _gmail(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        if path == "/profile":
            return httpx.Response(200, json={"emailAddress": ME})
        if path == "/messages":
            self.queries.append(request.url.params["q"])
            start = int(request.url.params.get("pageToken", "0"))
            page = self.messages[start:start + self.page_size]
            body = {"messages": [{"id": m.id, "threadId": m.thread} for m in page]}
            if start + self.page_size < len(self.messages):
                body["nextPageToken"] = str(start + self.page_size)
            return httpx.Response(200, json=body)
        mail = next(m for m in self.messages if path == f"/messages/{m.id}")
        self.fetched.append(mail.id)
        headers = [{"name": "From", "value": f"{mail.sender_name or ''} <{mail.sender}>"},
                   {"name": "To", "value": mail.to}, {"name": "Subject", "value": mail.subject},
                   {"name": "Date", "value": format_datetime(mail.when)},
                   {"name": "Message-ID", "value": mail.message_id or f"<{mail.id}@mail.example>"}]
        if mail.in_reply_to:
            headers.append({"name": "In-Reply-To", "value": mail.in_reply_to})
        data = base64.urlsafe_b64encode(mail.body.encode()).decode()
        return httpx.Response(200, json={
            "id": mail.id, "threadId": mail.thread, "labelIds": ["SENT"] if mail.sent else ["INBOX"],
            "snippet": mail.body[:100], "internalDate": str(int(mail.when.timestamp() * 1000)),
            "payload": {"mimeType": "multipart/alternative", "headers": headers,
                        "parts": [{"mimeType": "text/plain", "body": {"data": data}}]}})

    # --- Microsoft Graph --------------------------------------------------------
    def _graph(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0/me")
        if path == "":
            return httpx.Response(200, json={"mail": ME, "userPrincipalName": ME})
        if path == "/messages":
            start = int(request.url.params.get("$skip", "0"))
            page = self.messages[start:start + self.page_size]
            body = {"value": [self._graph_message(m) for m in page]}
            if start + self.page_size < len(self.messages):
                body["@odata.nextLink"] = f"https://graph.microsoft.com/v1.0/me/messages?$skip={start + self.page_size}"
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    @staticmethod
    def _graph_message(m: FakeMail) -> dict:
        return {"id": m.id, "conversationId": m.thread, "internetMessageId": m.message_id or f"<{m.id}@x>",
                "subject": m.subject, "from": {"emailAddress": {"address": m.sender, "name": m.sender_name or ""}},
                "toRecipients": [{"emailAddress": {"address": m.to}}], "ccRecipients": [],
                "receivedDateTime": m.when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "body": {"contentType": "text", "content": m.body}, "webLink": f"https://outlook.example/{m.id}"}

    # --- OAuth token endpoint ------------------------------------------------------
    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_calls.append(form)
        if self.fail_refresh and form.get("grant_type") == "refresh_token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": f"access-{len(self.token_calls)}", "expires_in": 3600,
                                         "refresh_token": form.get("refresh_token", "refresh-1"), "scope": "x"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in ("oauth2.googleapis.com", "login.microsoftonline.com"):
            return self._token(request)
        if self.unauthorized_once and request.headers.get("Authorization") == "Bearer access-0":
            self.unauthorized_once = False
            return httpx.Response(401)
        if self.statuses:
            code = self.statuses.pop(0)
            return httpx.Response(code, headers={"Retry-After": "2"} if code == 429 else {})
        if host == "gmail.googleapis.com":
            return self._gmail(request)
        if host == "graph.microsoft.com":
            return self._graph(request)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def token(access: str = "access-0", expires_in: float = 3600) -> dict:
    import time
    return {"access_token": access, "refresh_token": "refresh-1", "expires_at": time.time() + expires_in,
            "scope": "x"}


def dump(obj) -> str:
    return json.dumps(obj)
