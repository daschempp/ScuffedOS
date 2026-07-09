"""WhoopProvider — WHOOP v2 adapter (M4 design §4, §13).

Hand-rolled OAuth + authed REST over httpx (no Authlib; one provider doesn't
justify a dependency). All WHOOP field/endpoint names are confined to THIS
module — everything past it speaks the normalized dataclasses in base.py.

The http layer is a test seam mirroring llm.py: configure(fake_http=obj)
installs a fake exposing .post()/.get(); configure() (fake_http='unset')
restores the lazy real httpx.Client. Tokens are refreshed transparently when
within ~60s of expiry; a refresh failure raises WhoopAuthError, which the
sync engine/store translate into status='needs_reauth'.

CONFIRMED against the live v2 docs:
  auth   https://api.prod.whoop.com/oauth/oauth2/auth
  token  https://api.prod.whoop.com/oauth/oauth2/token
  base   https://api.prod.whoop.com/developer/v2/
  list responses: {"records": [...], "next_token": "..."}; query param nextToken
  metrics nested under a per-record "score" object; score_state in
          {"SCORED","PENDING_SCORE","UNSCORABLE"}
  workout sport field is "sport_name" in v2 (v1 used sport_id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..config import settings
from .base import (
    AuthError,
    NormalizedSnapshot,
    NormalizedWorkout,
    Tokens,
)

log = logging.getLogger("scuffed_os.whoop")

# [confirm-against-live] — verified against WHOOP v2 docs during M4 impl.
WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_REVOKE_URL = "https://api.prod.whoop.com/oauth/oauth2/revoke"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2/"
WHOOP_PROFILE_PATH = "user/profile/basic"  # [confirm-against-live] basic-profile collection
WHOOP_SCOPES = "read:recovery read:sleep read:workout read:cycles read:profile offline"
KJ_TO_KCAL = 0.239006  # calories = round(kilojoule * KJ_TO_KCAL)

# Refresh when the access token is within this many seconds of expiring.
_REFRESH_SKEW = timedelta(seconds=60)


class WhoopAuthError(AuthError):
    """Token refresh/exchange failed irrecoverably — caller flips needs_reauth.

    Subclasses providers.base.AuthError (NOT RuntimeError) so the sync engine's
    `except AuthError` catches it and flips the provider to needs_reauth."""


class WhoopProvider:
    name = "whoop"
    kind = "pull"

    def __init__(self) -> None:
        self._http: object | str = "unset"   # 'unset' → lazy real httpx.Client
        self._client = None
        self._tokens: Tokens | None = None    # injected by the sync engine before fetch_*

    # ---- http seam (mirrors llm._override) ----
    def configure(self, fake_http: object | str = "unset") -> None:
        """Tests install a fake exposing .post()/.get(); configure() restores real."""
        self._http = fake_http
        self._client = None

    def set_tokens(self, tokens: Tokens | None) -> None:
        """The sync engine injects the stored (possibly-refreshed) tokens here
        before calling fetch_recovery/sleep/workouts so authed calls carry a
        Bearer token. Without this every fetch would 401 (empty token)."""
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
        q = urlencode({
            "client_id": settings.whoop_client_id,
            "redirect_uri": settings.whoop_redirect_uri,
            "response_type": "code",
            "scope": WHOOP_SCOPES,
            "state": state,
        })
        return f"{WHOOP_AUTH_URL}?{q}"

    def _token_request(self, data: dict) -> Tokens:
        res = self._transport().post(WHOOP_TOKEN_URL, data=data)
        if getattr(res, "status_code", 200) >= 400:
            raise WhoopAuthError(f"WHOOP token endpoint returned {res.status_code}")
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
            "redirect_uri": settings.whoop_redirect_uri,
            "client_id": settings.whoop_client_id,
            "client_secret": settings.whoop_client_secret,
        })

    def refresh(self, tokens: Tokens) -> Tokens:
        if not tokens.refresh_token:
            raise WhoopAuthError("no refresh_token on record")
        try:
            fresh = self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "scope": "offline",
            })
        except WhoopAuthError:
            raise
        except Exception as exc:  # network etc. — treat as reauth-needed
            raise WhoopAuthError(f"refresh failed: {exc}") from exc
        # WHOOP may not echo a new refresh_token — keep the old one if absent.
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
                WHOOP_REVOKE_URL,
                data={
                    "client_id": settings.whoop_client_id,
                    "client_secret": settings.whoop_client_secret,
                    "token": tokens.access_token,
                },
            )
        except Exception as exc:
            log.warning("WHOOP revoke failed (continuing): %s", exc)

    # ---- OAuthProvider hooks (M5: the shared oauth router drives these) ----
    def on_connected(self) -> None:
        """Post-connect hook: kick an immediate fitness sync (backfill). The
        fresh account has no last_sync_at, so tick() backfills on this pass."""
        from .. import fitness_sync
        fitness_sync.tick()

    def on_disconnect(self) -> None:
        """Disconnect hook: delete WHOOP's daily_snapshots/workouts (source=
        'whoop'); manual workouts are preserved. Idempotent with the shared
        router's own delete_provider_data call (row already gone → no-op)."""
        from ..store import store
        store.delete_provider_data(self.name)

    def fetch_profile(self, tokens: Tokens) -> str | None:
        """GET the WHOOP basic profile and return the provider user id.

        Called by the OAuth callback right after exchange_code so the account's
        provider_user_id is populated (it is NOT inferred from the token
        payload). Best-effort: a profile fetch failure returns None rather than
        blocking the connect — the id is non-critical metadata. The id field
        name is [confirm-against-live] (WHOOP v2 basic profile)."""
        try:
            res = self._transport().get(
                WHOOP_API_BASE + WHOOP_PROFILE_PATH,
                headers={"Authorization": f"Bearer {tokens.access_token}"},
                params=None,
            )
            if getattr(res, "status_code", 200) >= 400:
                log.warning("WHOOP profile returned %s", getattr(res, "status_code", "?"))
                return None
            body = res.json() or {}
            uid = body.get("user_id")
            return str(uid) if uid is not None else None
        except Exception as exc:
            log.warning("WHOOP profile fetch failed (continuing): %s", exc)
            return None

    # ---- authed pull ----
    def _headers(self) -> dict:
        tokens = self._ensure_fresh(self._tokens) if self._tokens else None
        if tokens is not None:
            self._tokens = tokens   # keep rotated tokens for the rest of the run
        access = tokens.access_token if tokens else ""
        return {"Authorization": f"Bearer {access}"}

    def _get_records(self, path: str, since: datetime | None) -> list[dict]:
        """Page through a v2 collection, returning every record across pages.

        Query params (confirm-against-live): start (ISO), limit, nextToken.
        Response body: {"records": [...], "next_token": "..."}.
        """
        url = WHOOP_API_BASE + path
        headers = self._headers()
        records: list[dict] = []
        params: dict = {"limit": 25}
        if since is not None:
            params["start"] = since.isoformat()
        next_token: str | None = None
        for _ in range(50):  # hard page cap — never loop forever
            if next_token:
                params["nextToken"] = next_token
            res = self._transport().get(url, headers=headers, params=dict(params))
            if getattr(res, "status_code", 200) >= 400:
                raise WhoopAuthError(f"WHOOP {path} returned {res.status_code}")
            body = res.json()
            records.extend(body.get("records", []))
            next_token = body.get("next_token")
            if not next_token:
                break
        return records

    @staticmethod
    def _scored(rec: dict) -> dict | None:
        """The score object for a SCORED record, else None (skip unscored)."""
        if rec.get("score_state") != "SCORED":
            return None
        return rec.get("score") or None

    @staticmethod
    def _local_day(iso: str):
        """WHOOP timestamp (ISO, UTC) → local calendar day (matches display.py)."""
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().date()

    def fetch_recovery(self, since: datetime | None) -> list[NormalizedSnapshot]:
        """Recovery (recovery_pct/hrv/resting_hr) folded with cycle strain by day.

        Recovery records key on cycle_id; cycle records carry the physiological
        day's start + strain. We index cycles by id, then stamp each recovery
        day with that cycle's strain so one snapshot per day carries both.
        """
        cycles = {c["id"]: c for c in self._get_records("cycle", since)}
        snaps: list[NormalizedSnapshot] = []
        for rec in self._get_records("recovery", since):
            score = self._scored(rec)
            if score is None:
                continue
            cycle = cycles.get(rec.get("cycle_id"))
            # Day = cycle start (physiological day) when available, else the
            # recovery's created_at; both in local tz.
            day_src = (cycle or {}).get("start") or rec.get("created_at")
            if not day_src:
                continue
            cyc_score = self._scored(cycle) if cycle else None
            snaps.append(NormalizedSnapshot(
                source=self.name,
                day=self._local_day(day_src),
                recovery_pct=score.get("recovery_score"),
                resting_hr=score.get("resting_heart_rate"),
                hrv_ms=score.get("hrv_rmssd_milli"),
                day_strain=(cyc_score or {}).get("strain"),
            ))
        return snaps

    def fetch_sleep(self, since: datetime | None) -> list[NormalizedSnapshot]:
        snaps: list[NormalizedSnapshot] = []
        for rec in self._get_records("activity/sleep", since):
            if rec.get("nap"):
                continue  # naps don't define the day's sleep summary
            score = self._scored(rec)
            start = rec.get("start")
            if score is None or not start:
                continue
            stages = score.get("stage_summary") or {}
            in_bed = stages.get("total_in_bed_time_milli")
            awake = stages.get("total_awake_time_milli") or 0
            sleep_hours = None
            if in_bed is not None:
                sleep_hours = round((in_bed - awake) / 3_600_000, 1)
            snaps.append(NormalizedSnapshot(
                source=self.name,
                day=self._local_day(start),
                sleep_quality_pct=score.get("sleep_performance_percentage"),
                respiratory_rate=score.get("respiratory_rate"),
                sleep_hours=sleep_hours,
            ))
        return snaps

    def fetch_workouts(self, since: datetime | None) -> list[NormalizedWorkout]:
        outs: list[NormalizedWorkout] = []
        for rec in self._get_records("activity/workout", since):
            score = self._scored(rec)
            start, end = rec.get("start"), rec.get("end")
            if score is None or not start or not end:
                continue
            started = datetime.fromisoformat(start.replace("Z", "+00:00"))
            ended = datetime.fromisoformat(end.replace("Z", "+00:00"))
            duration_min = max(0, round((ended - started).total_seconds() / 60))
            sport = rec.get("sport_name")
            kj = score.get("kilojoule")
            outs.append(NormalizedWorkout(
                source=self.name,
                source_id=str(rec["id"]),
                name=(sport or "Workout").replace("_", " ").title(),
                sport=sport,
                started_at=started,
                duration_min=duration_min,
                strain=score.get("strain"),
                calories=round(kj * KJ_TO_KCAL) if kj is not None else None,
                avg_hr=score.get("average_heart_rate"),
                max_hr=score.get("max_heart_rate"),
            ))
        return outs
