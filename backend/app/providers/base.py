"""Vendor-neutral fitness seam: normalized dataclasses + Protocol + AuthError.

No provider field names (WHOOP's ``recovery_score`` etc.) leak past the
provider module — every provider maps its payloads into these dataclasses,
and the store/sync engine only ever see these. ``AuthError`` is the typed
auth/refresh failure the sync engine catches to flip a provider to
``needs_reauth``; the real ``WhoopProvider`` raises a ``WhoopAuthError``
subclass of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable


class AuthError(Exception):
    """Auth/refresh failure raised by a provider. ``fitness_sync.tick`` catches
    ``except AuthError`` and flips the provider to ``status='needs_reauth'``.
    The real provider's ``WhoopAuthError`` subclasses this."""


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


@runtime_checkable
class FitnessProvider(Protocol):
    name: str                            # 'whoop'
    kind: Literal["pull", "push"]        # whoop/oura='pull'; apple_health='push'

    def authorize_url(self, state: str) -> str: ...
    def exchange_code(self, code: str) -> Tokens: ...
    def refresh(self, tokens: Tokens) -> Tokens: ...
    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]: ...
    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]: ...
    def revoke(self, tokens: Tokens) -> None: ...
