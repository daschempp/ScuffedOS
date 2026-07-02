"""Vendor-neutral provider seam: normalized dataclasses + Protocols + AuthError.

M5 split the single FitnessProvider Protocol into a shared OAuthProvider base
(the connect/callback/disconnect plumbing the shared router drives) plus two
domain protocols: FitnessProvider (WHOOP-style pull data) and EmailProvider
(Gmail-style message reads). No provider field names leak past the provider
module — every provider maps its payloads into these dataclasses. ``AuthError``
is the typed auth/refresh failure the sync engines catch to flip a provider to
``needs_reauth`` (the real providers raise WhoopAuthError / GoogleAuthError).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable


class AuthError(Exception):
    """Auth/refresh failure raised by a provider. The sync engines catch
    ``except AuthError`` and flip the provider to ``status='needs_reauth'``.
    The real providers' WhoopAuthError / GoogleAuthError subclass this."""


@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None          # aware UTC
    scopes: str = ""                      # space-delimited, as granted
    provider_user_id: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class NormalizedSnapshot:
    source: str                          # 'whoop'
    day: date
    recovery_pct: int | None = None
    day_strain: float | None = None
    sleep_quality_pct: int | None = None
    hrv_ms: float | None = None
    resting_hr: int | None = None
    respiratory_rate: float | None = None
    sleep_hours: float | None = None
    metrics_json: dict = field(default_factory=dict)


@dataclass
class NormalizedWorkout:
    source: str                          # 'whoop'
    source_id: str | None
    name: str
    sport: str | None
    started_at: datetime                 # aware UTC
    duration_min: int
    strain: float | None = None
    calories: int | None = None          # kcal (already kJ->kcal converted)
    avg_hr: int | None = None
    max_hr: int | None = None


@dataclass
class NormalizedEmail:
    source: str                          # 'google'
    source_id: str                       # gmail message id
    thread_id: str
    from_name: str
    from_email: str
    subject: str
    snippet: str                         # gmail preview
    received_at: datetime                # aware UTC, sort key
    unread: bool = False
    body_excerpt: str = ""               # bounded ~2 KB plain-text, triage-only, NOT persisted
    starred: bool = False                # 'STARRED' in Gmail labelIds
    label_ids: list = field(default_factory=list)   # Gmail labelIds, sync-authoritative


@runtime_checkable
class OAuthProvider(Protocol):
    """The connect/callback/disconnect plumbing the shared oauth router drives.
    Both FitnessProvider and EmailProvider extend it."""
    name: str                            # 'whoop' | 'google'

    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def revoke(self, tokens: Tokens) -> None: ...
    def set_tokens(self, tokens: Tokens | None) -> None: ...
    def success_redirect(self) -> str: ...      # screen to land on after connect
    def on_connected(self) -> None: ...          # post-connect hook (kick a sync)
    def on_disconnect(self) -> None: ...         # delete this provider's domain data


@runtime_checkable
class FitnessProvider(OAuthProvider, Protocol):
    kind: Literal["pull", "push"]        # whoop/oura='pull'; apple_health='push'

    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...


@runtime_checkable
class EmailProvider(OAuthProvider, Protocol):
    def fetch_messages(self, since: datetime | None) -> list[NormalizedEmail]: ...
    def get_message(self, source_id: str) -> str: ...   # full plain-text body, on demand
    def send_message(self, raw_rfc822: bytes, thread_id: str | None = None) -> str: ...
    def trash_message(self, source_id: str) -> None: ...
    def modify_labels(self, source_id: str, add: list[str] = (), remove: list[str] = ()) -> None: ...
    def list_labels(self) -> list[dict]: ...
    def get_message_meta(self, source_id: str) -> dict: ...
