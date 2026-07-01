"""GoogleProvider — Google OAuth + Gmail adapter (M5 design §3, §4, §13).

Hand-rolled OAuth + authed REST over httpx (no google-api-python-client /
google-auth; one provider doesn't justify the dependency). All Google/Gmail
field/endpoint names are confined to THIS module — everything past it speaks
the normalized dataclasses in base.py (NormalizedEmail lands in the Gmail
phase; this file owns the OAuth half).

The http layer is a test seam mirroring whoop.py / llm.py: configure(fake_http=obj)
installs a fake exposing .post()/.get(); configure() (fake_http='unset') restores
the lazy real httpx.Client. A token exchange/refresh failure raises
GoogleAuthError (an AuthError subclass), which the email sync engine translates
into status='needs_reauth'.

[confirm-against-live] — the endpoint URLs, the access_type/prompt params, the
GOOGLE_SCOPES string, and the userinfo 'sub' field for provider_user_id are
confirmed against the live Google/Gmail API during implementation (design §13);
their constant NAMES are frozen by the interface contract.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..config import settings
from .base import AuthError, Tokens

log = logging.getLogger("scuffed_os.google")

# [confirm-against-live] — verified against the live Google/Gmail API during M5 impl.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.readonly"

# Refresh when the access token is within this many seconds of expiring.
_REFRESH_SKEW = timedelta(seconds=60)


class GoogleAuthError(AuthError):
    """Token refresh/exchange failed irrecoverably — caller flips needs_reauth.

    Subclasses providers.base.AuthError (NOT RuntimeError) so the email sync
    engine's `except AuthError` catches it and flips the provider to
    needs_reauth."""


class GoogleProvider:
    name = "google"

    def __init__(self) -> None:
        self._http: object | str = "unset"   # 'unset' → lazy real httpx.Client
        self._client = None
        self._tokens: Tokens | None = None    # injected by the email sync engine

    # ---- http seam (mirrors WhoopProvider) ----
    def configure(self, fake_http: object | str = "unset") -> None:
        """Tests install a fake exposing .post()/.get(); configure() restores real."""
        self._http = fake_http
        self._client = None

    def set_tokens(self, tokens: Tokens | None) -> None:
        """The email sync engine injects the stored (possibly-refreshed) tokens
        here before calling fetch_messages/get_message so authed Gmail calls
        carry a Bearer token."""
        self._tokens = tokens

    def _transport(self):
        if self._http != "unset":
            return self._http
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=20.0)
        return self._client

    # ---- OAuth ----
    def authorize_url(self, state: str) -> str:
        # access_type=offline + prompt=consent guarantee Google issues a
        # refresh_token (without them a re-consent may omit it).
        q = urlencode({
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"{GOOGLE_AUTH_URL}?{q}"
