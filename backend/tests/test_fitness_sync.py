"""Sync engine (M4): one tick pulls connected providers into normalized tables,
advances the cursor, and never crashes — a near-clone of the reminders tick."""
from datetime import date, datetime, timedelta, timezone

from app import fitness_sync, providers
from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
from app.store import store


def _utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class FakeProvider:
    """A pull provider that replays fixture rows and records the `since` it saw."""

    name = "whoop"
    kind = "pull"

    def __init__(self, recovery=(), sleep=(), workouts=(), fail_auth=False):
        self._recovery = list(recovery)
        self._sleep = list(sleep)
        self._workouts = list(workouts)
        self._fail_auth = fail_auth
        self.since_seen: list = []
        self.injected_tokens: list = []   # records set_tokens() calls

    def authorize_url(self, state):
        return f"https://example.test/auth?state={state}"

    def exchange_code(self, code):
        return Tokens(access_token="a", refresh_token="r", expires_at=None)

    def refresh(self, tokens):
        return tokens

    def set_tokens(self, tokens):
        self.injected_tokens.append(tokens)

    def fetch_recovery(self, since):
        self.since_seen.append(("recovery", since))
        return list(self._recovery)

    def fetch_sleep(self, since):
        self.since_seen.append(("sleep", since))
        return list(self._sleep)

    def fetch_workouts(self, since):
        self.since_seen.append(("workouts", since))
        return list(self._workouts)

    def revoke(self, tokens):
        pass


def _connect(provider="whoop"):
    store.upsert_provider_account(
        provider,
        Tokens(access_token="a", refresh_token="r",
               expires_at=_utc(2030, 1, 1), scopes="read:recovery"),
    )


def test_tick_upserts_merged_snapshot_and_workout_then_advances_cursor():
    day = date(2026, 6, 28)
    recovery = [NormalizedSnapshot(source="whoop", day=day, recovery_pct=66, hrv_ms=48.0,
                                   resting_hr=54)]
    sleep = [NormalizedSnapshot(source="whoop", day=day, sleep_quality_pct=82,
                               sleep_hours=7.4, respiratory_rate=14.2)]
    workouts = [NormalizedWorkout(source="whoop", source_id="w-uuid-1", name="Run",
                                  sport="running", started_at=_utc(2026, 6, 28, 13, 0),
                                  duration_min=42, strain=11.3, calories=480,
                                  avg_hr=150, max_hr=171)]
    fake = FakeProvider(recovery=recovery, sleep=sleep, workouts=workouts)
    providers.configure([fake])
    _connect()

    n = fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0))
    assert n == 2  # one merged snapshot + one workout

    today = store.fitness_today(day)
    assert today["recovery_pct"] == 66
    assert today["sleep_quality_pct"] == 82          # sleep merged onto recovery row
    assert today["day_strain"] is None               # no strain in this fixture
    assert {v["key"]: v["value"] for v in today["vitals"]}["hrv"] == 48.0

    rows = store.list_workouts()
    assert [w["source_id"] for w in rows] == ["w-uuid-1"]
    assert rows[0]["calories"] == 480

    # Cursor advanced to the tick's `now`.
    acct = next(a for a in store.list_provider_accounts() if a["provider"] == "whoop")
    assert acct["last_sync_at"] == _utc(2026, 6, 30, 12, 0)


def test_tick_injects_stored_tokens_into_provider_before_fetch():
    """The sync engine must load the connected account's stored tokens and
    inject them (set_tokens) so authed fetch_* carry a Bearer token. Without
    this, real WHOOP calls 401 — a bug FakeProvider would otherwise hide."""
    fake = FakeProvider()
    providers.configure([fake])
    store.upsert_provider_account(
        "whoop",
        Tokens(access_token="the-access", refresh_token="r",
               expires_at=_utc(2030, 1, 1), scopes="read:recovery"),
    )
    fitness_sync.tick(now=_utc(2026, 6, 30, 12, 0))
    # set_tokens was called once, with the stored access token.
    assert len(fake.injected_tokens) == 1
    assert fake.injected_tokens[0].access_token == "the-access"


def test_first_tick_backfills_from_now_minus_backfill_days():
    fake = FakeProvider()
    providers.configure([fake])
    _connect()
    now = _utc(2026, 6, 30, 12, 0)
    fitness_sync.tick(now=now)
    # No prior last_sync_at -> since == now - whoop_backfill_days (default 30).
    since_values = {kind: s for kind, s in fake.since_seen}
    assert since_values["recovery"] == now - timedelta(days=30)
    assert since_values["sleep"] == now - timedelta(days=30)
    assert since_values["workouts"] == now - timedelta(days=30)


def test_second_tick_uses_stored_cursor_as_since():
    fake = FakeProvider()
    providers.configure([fake])
    _connect()
    first = _utc(2026, 6, 30, 12, 0)
    fitness_sync.tick(now=first)
    fake.since_seen.clear()
    second = _utc(2026, 6, 30, 18, 0)
    fitness_sync.tick(now=second)
    since_values = {kind: s for kind, s in fake.since_seen}
    # The cursor from the first tick (its `now`) is the new `since`.
    assert since_values["recovery"] == first
