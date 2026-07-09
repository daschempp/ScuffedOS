"""The vendor-neutral normalized dataclasses + Protocol + AuthError the store,
sync engine and providers share."""
from datetime import date, datetime, timezone

from app.providers.base import (
    AuthError,
    FitnessProvider,
    NormalizedSnapshot,
    NormalizedWorkout,
    Tokens,
)


def test_auth_error_is_an_exception():
    # The sync engine catches `except AuthError`; the real provider's
    # WhoopAuthError subclasses this. It must be a plain Exception.
    assert issubclass(AuthError, Exception)
    err = AuthError("token revoked")
    assert isinstance(err, Exception)


def test_tokens_defaults():
    t = Tokens(access_token="a", refresh_token="r", expires_at=None)
    assert t.access_token == "a"
    assert t.refresh_token == "r"
    assert t.expires_at is None
    assert t.scopes == ""
    assert t.provider_user_id is None
    assert t.meta == {}
    # meta default is not shared across instances
    t.meta["k"] = 1
    assert Tokens(access_token="b", refresh_token=None, expires_at=None).meta == {}


def test_normalized_snapshot_optional_fields_default_none():
    snap = NormalizedSnapshot(source="whoop", day=date(2026, 6, 30))
    assert snap.source == "whoop"
    assert snap.day == date(2026, 6, 30)
    assert snap.recovery_pct is None
    assert snap.day_strain is None
    assert snap.sleep_quality_pct is None
    assert snap.hrv_ms is None
    assert snap.resting_hr is None
    assert snap.respiratory_rate is None
    assert snap.sleep_hours is None
    assert snap.metrics_json == {}


def test_normalized_workout_required_and_optional():
    started = datetime(2026, 6, 30, 6, 10, tzinfo=timezone.utc)
    w = NormalizedWorkout(
        source="whoop", source_id="uuid-1", name="Run", sport="running",
        started_at=started, duration_min=42,
    )
    assert (w.source, w.source_id, w.name, w.sport) == ("whoop", "uuid-1", "Run", "running")
    assert w.started_at == started
    assert w.duration_min == 42
    assert w.strain is None
    assert w.calories is None
    assert w.avg_hr is None
    assert w.max_hr is None


class _MinimalProvider:
    name = "whoop"
    kind = "pull"

    def authorize_url(self, state, code_challenge=None): return ""
    def exchange_code(self, code, verifier=None): return Tokens("a", None, None)
    def refresh(self, tokens): return tokens
    def fetch_recovery(self, since): return []
    def fetch_sleep(self, since): return []
    def fetch_workouts(self, since): return []
    def revoke(self, tokens): return None
    def set_tokens(self, tokens): pass
    def on_connected(self): pass
    def on_disconnect(self): pass


def test_runtime_checkable_protocol_accepts_a_conforming_object():
    assert isinstance(_MinimalProvider(), FitnessProvider)


def test_oauth_methods_accept_optional_pkce_params():
    p = _MinimalProvider()
    # New optional PKCE params must be accepted by every OAuthProvider signature.
    assert p.authorize_url("st8", code_challenge="chal") == ""
    p.exchange_code("code", verifier="vrf")  # must not raise TypeError


def test_runtime_checkable_protocol_rejects_a_missing_method():
    class Broken:
        name = "x"
        kind = "pull"
        def authorize_url(self, state): return ""
        # no other methods
    assert not isinstance(Broken(), FitnessProvider)
