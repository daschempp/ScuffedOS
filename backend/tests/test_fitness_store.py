"""Store-layer fitness logic: provider accounts, snapshots, workouts (M4).

All against SQLite via the fresh_db fixture — no network, no providers.
"""
from datetime import date, datetime, timedelta, timezone

from app.providers.base import NormalizedSnapshot, NormalizedWorkout, Tokens
from app.store import store

UTC = timezone.utc


def _tokens(**kw):
    base = dict(
        access_token="acc-1", refresh_token="ref-1",
        expires_at=datetime(2026, 7, 1, tzinfo=UTC),
        scopes="read:recovery read:workout", provider_user_id="whoop-user-9",
        meta={"foo": "bar"},
    )
    base.update(kw)
    return Tokens(**base)


def test_get_provider_account_absent_is_none():
    assert store.get_provider_account("whoop") is None
    assert store.get_provider_tokens("whoop") is None
    assert store.list_provider_accounts() == []


def test_upsert_provider_account_creates_safe_dict_without_tokens():
    safe = store.upsert_provider_account("whoop", _tokens())
    assert safe["provider"] == "whoop"
    assert safe["status"] == "connected"
    assert safe["provider_user_id"] == "whoop-user-9"
    assert safe["connected_at"] is not None
    assert safe["last_sync_at"] is None
    # Tokens must never appear in the client-safe dict.
    assert "access_token" not in safe
    assert "refresh_token" not in safe
    assert "scopes" not in safe
    assert "meta" not in safe


def test_get_provider_tokens_round_trips_secrets():
    store.upsert_provider_account("whoop", _tokens())
    tok = store.get_provider_tokens("whoop")
    assert tok.access_token == "acc-1"
    assert tok.refresh_token == "ref-1"
    assert tok.expires_at == datetime(2026, 7, 1, tzinfo=UTC)
    assert tok.scopes == "read:recovery read:workout"
    assert tok.provider_user_id == "whoop-user-9"
    assert tok.meta == {"foo": "bar"}


def test_upsert_is_get_or_create_by_owner_provider():
    first = store.upsert_provider_account("whoop", _tokens())
    second = store.upsert_provider_account("whoop", _tokens(access_token="acc-2"))
    assert first["connected_at"] == second["connected_at"]  # same row, not recreated
    assert len(store.list_provider_accounts()) == 1
    assert store.get_provider_tokens("whoop").access_token == "acc-2"  # rotated in place
    # Reconnecting flips a needs_reauth row back to connected.
    store.set_provider_status("whoop", "needs_reauth")
    again = store.upsert_provider_account("whoop", _tokens())
    assert again["status"] == "connected"


def test_set_provider_status_and_synced():
    store.upsert_provider_account("whoop", _tokens())
    store.set_provider_status("whoop", "needs_reauth")
    assert store.get_provider_account("whoop")["status"] == "needs_reauth"
    when = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    store.set_provider_synced("whoop", when)
    assert store.get_provider_account("whoop")["last_sync_at"] == when


DAY = date(2026, 6, 30)


def test_upsert_snapshot_creates_row():
    out = store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, day_strain=14.2,
        hrv_ms=88.5, resting_hr=52,
    ))
    assert out["source"] == "whoop"
    assert out["day"] == DAY
    assert out["recovery_pct"] == 72
    assert out["day_strain"] == 14.2
    assert out["hrv_ms"] == 88.5
    assert out["resting_hr"] == 52


def test_upsert_snapshot_is_idempotent_by_owner_source_day():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=80))
    from sqlalchemy import select as _select

    from app.models import DailySnapshot
    with store._session() as s:
        rows = s.scalars(_select(DailySnapshot)).all()
    assert len(rows) == 1
    assert rows[0].recovery_pct == 80  # latest non-None wins


def test_upsert_snapshot_merges_recovery_and_sleep_same_day():
    # Recovery snapshot lands first (recovery + hrv), no sleep fields.
    store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, recovery_pct=72, hrv_ms=88.5, resting_hr=52,
    ))
    # Sleep snapshot lands second (sleep fields), recovery fields all None.
    merged = store.upsert_snapshot(NormalizedSnapshot(
        source="whoop", day=DAY, sleep_quality_pct=91,
        respiratory_rate=14.6, sleep_hours=7.4,
    ))
    # Non-None from both lands on the one row; the earlier values survive.
    assert merged["recovery_pct"] == 72
    assert merged["hrv_ms"] == 88.5
    assert merged["resting_hr"] == 52
    assert merged["sleep_quality_pct"] == 91
    assert merged["respiratory_rate"] == 14.6
    assert merged["sleep_hours"] == 7.4


def test_upsert_snapshot_none_does_not_clobber():
    store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=72))
    out = store.upsert_snapshot(NormalizedSnapshot(source="whoop", day=DAY, recovery_pct=None, day_strain=10.0))
    assert out["recovery_pct"] == 72  # None left the prior value intact
    assert out["day_strain"] == 10.0
