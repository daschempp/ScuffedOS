"""M7 Finance (Plaid) settings — defaults + env override (contract §8)."""
from app.config import Settings


def test_finance_settings_defaults():
    s = Settings(_env_file=None)
    assert s.plaid_env == "production"
    assert s.plaid_client_id == ""
    assert s.plaid_secret == ""
    assert s.plaid_country_codes == ["US"]
    assert s.finance_sync_enabled is True
    assert s.finance_sync_seconds == 1800
    assert s.plaid_backfill_days == 90


def test_finance_settings_env_override(monkeypatch):
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "sek")
    s = Settings(_env_file=None)
    assert s.plaid_env == "sandbox"
    assert s.plaid_client_id == "cid"
    assert s.plaid_secret == "sek"
