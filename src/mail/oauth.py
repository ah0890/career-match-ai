"""OAuth 2.0 for installed apps: authorization code + PKCE with a one-time loopback redirect.

The user signs in on Google's or Microsoft's own page in their browser; CareerMatch never sees
the email password. The browser is sent back to http://127.0.0.1:<random port>/, where a tiny
server accepts exactly one request with the expected ``state`` and then stops.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from config.settings import Settings


class OAuthError(RuntimeError):
    """A user-safe message about a failed sign-in."""


class OAuthUnreachable(OAuthError):
    """The provider could not be reached: worth retrying later, not a reason to reconnect."""


@dataclass(frozen=True)
class ProviderConfig:
    key: str
    label: str
    auth_url: str
    token_url: str
    scopes: tuple[str, ...]
    extra_auth_params: tuple[tuple[str, str], ...] = ()
    revoke_url: str | None = None


GMAIL = ProviderConfig(
    "gmail", "Gmail",
    "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
    ("https://www.googleapis.com/auth/gmail.readonly",),  # read-only: CareerMatch never sends or changes email
    (("access_type", "offline"), ("prompt", "consent")),
    "https://oauth2.googleapis.com/revoke",
)
OUTLOOK = ProviderConfig(
    "outlook", "Outlook / Microsoft 365",
    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    ("offline_access", "https://graph.microsoft.com/User.Read", "https://graph.microsoft.com/Mail.Read"),
    (("prompt", "select_account"),),
)
PROVIDERS = {p.key: p for p in (GMAIL, OUTLOOK)}


def client_credentials(provider: ProviderConfig, settings: Settings) -> tuple[str, str | None]:
    if provider.key == "gmail":
        if not settings.gmail_client_id or not settings.gmail_client_secret:
            raise OAuthError("Gmail is not set up yet: add CAREERMATCH_GMAIL_CLIENT_ID and "
                             "CAREERMATCH_GMAIL_CLIENT_SECRET to your .env file (see README, Email tracking).")
        return settings.gmail_client_id, settings.gmail_client_secret.get_secret_value()
    if not settings.outlook_client_id:
        raise OAuthError("Outlook is not set up yet: add CAREERMATCH_OUTLOOK_CLIENT_ID to your .env file "
                         "(see README, Email tracking).")
    return settings.outlook_client_id, None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


_DONE_PAGE = (b"<!doctype html><meta charset='utf-8'><title>CareerMatch AI</title>"
              b"<body style='font-family:system-ui;padding:40px;color:#0F172A'>"
              b"<h2>%s</h2><p>You can close this tab and return to CareerMatch AI.</p></body>")


@dataclass
class LoopbackFlow:
    """One sign-in attempt. ``start()`` returns the URL to open; ``result`` fills in when the browser returns."""

    provider: ProviderConfig
    client_id: str
    state: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    verifier: str = ""
    redirect_uri: str = ""
    auth_url: str = ""  # the provider's sign-in page for this attempt
    code: str | None = None
    error: str | None = None
    _server: HTTPServer | None = None
    _deadline: float = 0.0

    def start(self, timeout_s: int = 300) -> str:
        self.verifier, challenge = pkce_pair()
        flow = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                query = parse_qs(urlsplit(self.path).query)
                if query.get("state", [""])[0] != flow.state:
                    self.send_response(400)
                    self.end_headers()
                    return  # not our sign-in: ignore and keep waiting
                if "code" in query:
                    flow.code = query["code"][0]
                    message = b"Mailbox connected"
                else:
                    flow.error = query.get("error_description", query.get("error", ["Sign-in was cancelled."]))[0][:200]
                    message = b"Sign-in did not complete"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(_DONE_PAGE % message)

            def log_message(self, *_args) -> None:  # keep codes out of logs
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 1
        self.redirect_uri = f"http://127.0.0.1:{self._server.server_port}/"
        self._deadline = time.monotonic() + timeout_s
        threading.Thread(target=self._serve, daemon=True).start()
        params = {"client_id": self.client_id, "response_type": "code", "redirect_uri": self.redirect_uri,
                  "scope": " ".join(self.provider.scopes), "state": self.state,
                  "code_challenge": challenge, "code_challenge_method": "S256", **dict(self.provider.extra_auth_params)}
        self.auth_url = f"{self.provider.auth_url}?{urlencode(params)}"
        return self.auth_url

    def _serve(self) -> None:
        assert self._server is not None
        while self.code is None and self.error is None and time.monotonic() < self._deadline:
            self._server.handle_request()
        self._server.server_close()
        if self.code is None and self.error is None:
            self.error = "Sign-in timed out. Try again."

    @property
    def finished(self) -> bool:
        return self.code is not None or self.error is not None


def _token_request(provider: ProviderConfig, data: dict, client: httpx.Client) -> dict:
    try:
        response = client.post(provider.token_url, data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError:
        raise OAuthUnreachable(f"Could not reach {provider.label}. Check your connection and try again.") from None
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or "access_token" not in payload:
        code = payload.get("error", f"HTTP {response.status_code}")
        raise OAuthError(f"{provider.label} refused the sign-in ({code}).")
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token") or data.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in", 3600)) - 60,
        "scope": payload.get("scope", " ".join(provider.scopes)),
    }


def exchange_code(flow: LoopbackFlow, client_secret: str | None, client: httpx.Client) -> dict:
    data = {"grant_type": "authorization_code", "code": flow.code, "redirect_uri": flow.redirect_uri,
            "client_id": flow.client_id, "code_verifier": flow.verifier}
    if client_secret:
        data["client_secret"] = client_secret
    token = _token_request(flow.provider, data, client)
    if not token.get("refresh_token"):
        raise OAuthError(f"{flow.provider.label} did not allow offline access. Try connecting again.")
    return token


def refresh(provider: ProviderConfig, token: dict, client_id: str, client_secret: str | None,
            client: httpx.Client) -> dict:
    data = {"grant_type": "refresh_token", "refresh_token": token["refresh_token"], "client_id": client_id}
    if client_secret:
        data["client_secret"] = client_secret
    if provider.key == "outlook":
        data["scope"] = " ".join(provider.scopes)
    return _token_request(provider, data, client)


def revoke(provider: ProviderConfig, token: dict, client: httpx.Client) -> None:
    """Best effort: Google supports revocation; Microsoft public clients simply forget the token."""
    if provider.revoke_url and token.get("refresh_token"):
        try:
            client.post(provider.revoke_url, data={"token": token["refresh_token"]})
        except httpx.HTTPError:
            pass
