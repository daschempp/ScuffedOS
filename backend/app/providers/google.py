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

import base64
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlencode

from ..config import settings
from .base import AuthError, NormalizedEmail, Tokens

log = logging.getLogger("scuffed_os.google")

# [confirm-against-live] — verified against the live Google/Gmail API during M5 impl.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = ("openid email profile "
                 "https://www.googleapis.com/auth/gmail.readonly "
                 "https://www.googleapis.com/auth/gmail.modify "
                 "https://www.googleapis.com/auth/gmail.send")   # [confirm-against-live]

# Refresh when the access token is within this many seconds of expiring.
_REFRESH_SKEW = timedelta(seconds=60)

# ~2 KB bounded plain-text excerpt sent to triage (never persisted).
_EXCERPT_LIMIT = 2048


def _decode_b64url(data: str | None) -> str:
    """Decode a Gmail base64url body part to text. Gmail omits '=' padding and
    uses the URL-safe alphabet; pad back to a multiple of 4 before decoding."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", "replace")
    except Exception:  # malformed part — treat as empty rather than crashing sync
        return ""


def _walk_plaintext(part: dict) -> str:
    """Depth-first walk of a Gmail payload tree, returning the first text/plain
    body found (falling back to any decodable body if no text/plain exists)."""
    if not part:
        return ""
    mime = part.get("mimeType", "")
    body = part.get("body") or {}
    if mime == "text/plain" and body.get("data"):
        return _decode_b64url(body["data"])
    for child in part.get("parts") or []:
        found = _walk_plaintext(child)
        if found:
            return found
    # Leaf with a body but no text/plain sibling (rare single-part text emails,
    # or an html-only multipart/alternative with no text/plain part at all).
    if not part.get("parts") and body.get("data") and mime.startswith("text/"):
        decoded = _decode_b64url(body["data"])
        return _html_to_text(decoded) if mime == "text/html" else decoded
    return ""


_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(markup: str) -> str:
    """Best-effort HTML -> readable plain text: drop script/style, strip tags,
    unescape entities, collapse whitespace. Used only when the sole decodable
    body part is text/html (no text/plain), so triage + the reading pane never
    receive raw markup."""
    if not markup:
        return ""
    text = _SCRIPT_STYLE_RE.sub(" ", markup)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()


def _excerpt(text: str) -> str:
    return text[:_EXCERPT_LIMIT]


def _header(headers: list[dict], name: str) -> str:
    lname = name.lower()
    for h in headers:
        if (h.get("name") or "").lower() == lname:
            return h.get("value") or ""
    return ""


def _parse_from(value: str) -> tuple[str, str]:
    """'Priya Rao <priya@x.io>' -> ('Priya Rao', 'priya@x.io'); a bare address
    -> ('', addr). Uses stdlib parseaddr so quoting/comments are handled."""
    name, addr = parseaddr(value)
    return name.strip(), addr.strip()


def _parse_date(value: str) -> datetime:
    """RFC 2822 Date header -> aware UTC. Falls back to now(UTC) on a bad/absent
    header so a single malformed message never breaks the sort key."""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _build_rfc822(*, to: str, subject: str, body: str, cc: str | None = None,
                   in_reply_to: str | None = None, references: str | None = None) -> bytes:
    """Assemble a plain-text RFC-822 message for Gmail's messages.send (base64url
    of these bytes becomes the 'raw' field — see send_message). From is
    omitted: Gmail always sets it to the authenticated account regardless of
    what's supplied, so setting it here would be misleading. Uses stdlib
    email.message.EmailMessage so multi-byte body text (emoji, accents) is
    MIME-encoded correctly without a third-party dependency."""
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body, subtype="plain", charset="utf-8")
    return msg.as_bytes()


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

    def _token_request(self, data: dict) -> Tokens:
        res = self._transport().post(GOOGLE_TOKEN_URL, data=data)
        if getattr(res, "status_code", 200) >= 400:
            raise GoogleAuthError(
                f"Google token endpoint returned {getattr(res, 'status_code', '?')}"
            )
        payload = res.json()
        expires_at = None
        if payload.get("expires_in") is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(payload["expires_in"])
            )
        return Tokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scopes=payload.get("scope", "") or "",
        )

    def exchange_code(self, code: str) -> Tokens:
        return self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.google_redirect_uri,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
        })

    def refresh(self, tokens: Tokens) -> Tokens:
        if not tokens.refresh_token:
            raise GoogleAuthError("no refresh_token on record")
        try:
            fresh = self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
            })
        except GoogleAuthError:
            raise
        except Exception as exc:  # network etc. — treat as reauth-needed
            raise GoogleAuthError(f"refresh failed: {exc}") from exc
        # Google usually omits refresh_token on refresh — keep the old one.
        if fresh.refresh_token is None:
            fresh.refresh_token = tokens.refresh_token
        if not fresh.scopes:
            fresh.scopes = tokens.scopes
        return fresh

    def _ensure_fresh(self, tokens: Tokens) -> Tokens:
        """Refresh transparently if within the skew of expiry; else pass through."""
        if tokens.expires_at is None:
            return tokens
        if datetime.now(timezone.utc) >= tokens.expires_at - _REFRESH_SKEW:
            return self.refresh(tokens)
        return tokens

    def revoke(self, tokens: Tokens) -> None:
        """Best-effort remote revoke; disconnect deletes local data regardless."""
        try:
            self._transport().post(
                GOOGLE_REVOKE_URL,
                data={"token": tokens.access_token},
            )
        except Exception as exc:
            log.warning("Google revoke failed (continuing): %s", exc)

    def fetch_profile(self, tokens: Tokens) -> str | None:
        """GET the Google userinfo endpoint and return the 'sub' (provider_user_id).

        Called by the shared OAuth callback right after exchange_code so the
        account's provider_user_id is populated. Best-effort: a failure returns
        None rather than blocking the connect. The 'sub' field is [confirm-against-live]."""
        try:
            res = self._transport().get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                params=None,
            )
            if getattr(res, "status_code", 200) >= 400:
                log.warning("Google userinfo returned %s", getattr(res, "status_code", "?"))
                return None
            body = res.json() or {}
            sub = body.get("sub")
            return str(sub) if sub is not None else None
        except Exception as exc:
            log.warning("Google userinfo fetch failed (continuing): %s", exc)
            return None

    # ---- OAuthProvider connect/disconnect hooks ----
    def success_redirect(self) -> str:
        return "/?screen=email&connected=google"

    def on_connected(self) -> None:
        """Post-connect hook (called by the shared callback AFTER tokens persist):
        kick an immediate first-sync backfill. Imported lazily so this module
        does not hard-depend on the Gmail-sync phase; a not-yet-authored
        email_sync is swallowed (the connect still succeeds)."""
        try:
            from .. import email_sync

            email_sync.tick()
        except Exception as exc:  # noqa: BLE001 — first-sync is best-effort
            log.warning("Google on_connected sync skipped: %s", exc)

    def on_disconnect(self) -> None:
        """Disconnect hook (called by the shared disconnect AFTER best-effort
        revoke): delete this provider's emails. Imported lazily; a store without
        delete_email_data yet (mid-plan) is swallowed."""
        try:
            from ..store import store

            store.delete_email_data(self.name)
        except Exception as exc:  # noqa: BLE001 — data deletion is idempotent/best-effort here
            log.warning("Google on_disconnect email delete skipped: %s", exc)

    # ---- authed Gmail read ----
    def _headers(self) -> dict:
        tokens = self._ensure_fresh(self._tokens) if self._tokens else None
        if tokens is not None:
            self._tokens = tokens
        access = tokens.access_token if tokens else ""
        return {"Authorization": f"Bearer {access}"}

    def _get(self, url: str, params: dict | None = None) -> dict:
        res = self._transport().get(url, headers=self._headers(), params=params)
        if getattr(res, "status_code", 200) >= 400:
            raise GoogleAuthError(f"Gmail GET {url} returned {res.status_code}")
        return res.json() or {}

    def _post(self, url: str, json: dict) -> dict:
        res = self._transport().post(url, headers=self._headers(), json=json)
        if getattr(res, "status_code", 200) >= 400:
            raise GoogleAuthError(f"Gmail POST {url} returned {res.status_code}")
        return res.json() or {}

    def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]:
        """List the INBOX (maxResults=email_backfill_count) then map each message
        (headers + snippet + a bounded plain-text body excerpt) to a
        NormalizedEmail. `since` is accepted for signature parity with the pull
        providers; Gmail idempotency is handled by store.email_exists in the
        sync (list returns the newest INBOX ids each pass). Auth/transport
        failures raise GoogleAuthError so the sync flips needs_reauth."""
        listing = self._get(
            f"{GMAIL_API_BASE}/messages",
            params={"labelIds": "INBOX", "maxResults": settings.email_backfill_count},
        )
        out: list[NormalizedEmail] = []
        for ref in listing.get("messages") or []:
            msg_id = ref.get("id")
            if not msg_id:
                continue
            msg = self._get(
                f"{GMAIL_API_BASE}/messages/{msg_id}", params={"format": "full"}
            )
            out.append(self._to_email(msg))
        return out

    @staticmethod
    def _to_email(msg: dict) -> NormalizedEmail:
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        from_name, from_email = _parse_from(_header(headers, "From"))
        label_ids = msg.get("labelIds") or []
        return NormalizedEmail(
            source="google",
            source_id=str(msg.get("id") or ""),
            thread_id=str(msg.get("threadId") or ""),
            from_name=from_name,
            from_email=from_email,
            subject=_header(headers, "Subject"),
            snippet=msg.get("snippet") or "",
            received_at=_parse_date(_header(headers, "Date")),
            unread="UNREAD" in label_ids,
            body_excerpt=_excerpt(_walk_plaintext(payload)),
            starred="STARRED" in label_ids,
            label_ids=label_ids,
        )

    def get_message(self, source_id: str) -> str:
        """On-demand full plain-text body for the reading pane. Raises
        GoogleAuthError on a transport error; the router/store catches it and
        substitutes the fallback string."""
        msg = self._get(
            f"{GMAIL_API_BASE}/messages/{source_id}", params={"format": "full"}
        )
        return _walk_plaintext(msg.get("payload") or {})

    def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str:
        """POST messages.send with the RFC-822 bytes (from _build_rfc822)
        base64url-encoded into 'raw'. thread_id (when given, e.g. a reply)
        tells Gmail to thread the new message onto the existing conversation
        instead of starting a new one. Returns the new Gmail message id."""
        payload: dict = {"raw": base64.urlsafe_b64encode(raw_rfc822).decode("ascii").rstrip("=")}
        if thread_id:
            payload["threadId"] = thread_id
        result = self._post(f"{GMAIL_API_BASE}/messages/send", json=payload)
        return str(result["id"])

    def trash_message(self, source_id: str) -> None:
        """Move a message to Gmail Trash (users.messages.trash) — never a
        permanent delete (the full-access mail.google.com scope is not
        requested). Google auto-purges Trash after ~30 days."""
        self._post(f"{GMAIL_API_BASE}/messages/{source_id}/trash", json={})

    def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None:
        """Add/remove Gmail label ids on one message. Read/unread state and
        star are both modeled as labels: unread = presence of 'UNREAD',
        starred = presence of 'STARRED' — the router computes add/remove
        from the desired flag state before calling this."""
        self._post(
            f"{GMAIL_API_BASE}/messages/{source_id}/modify",
            json={"addLabelIds": list(add), "removeLabelIds": list(remove)},
        )

    def list_labels(self) -> list[dict]:
        """All Gmail labels (system + user) for the label-picker menu."""
        result = self._get(f"{GMAIL_API_BASE}/labels")
        return list(result.get("labels") or [])

    def get_message_meta(self, source_id: str) -> dict:
        """Bounded metadata-only fetch (format=metadata, four headers) used
        to build reply/forward threading headers without pulling the full
        body. Missing headers come back as '' rather than raising, so a
        message with an unusual header set still produces a usable (if
        empty) threading context."""
        msg = self._get(
            f"{GMAIL_API_BASE}/messages/{source_id}",
            params={
                "format": "metadata",
                "metadataHeaders": ["Message-ID", "References", "Subject", "From"],
            },
        )
        headers = (msg.get("payload") or {}).get("headers") or []
        _, from_email = _parse_from(_header(headers, "From"))
        return {
            "message_id": _header(headers, "Message-ID"),
            "references": _header(headers, "References"),
            "subject": _header(headers, "Subject"),
            "from_email": from_email,
        }
