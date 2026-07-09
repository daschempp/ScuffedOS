"""M5 config: Google OAuth credentials + email-sync knobs land on Settings with spec defaults."""
from app.config import Settings


def test_google_and_email_sync_defaults():
    # Assert declared code defaults on the model fields, independent of any local
    # backend/.env or env vars — a real Google setup fills client_id/secret in .env,
    # which must NOT break this defaults check (matches test_fitness_config.py).
    d = Settings.model_fields
    assert d["google_client_id"].default == ""
    assert d["google_client_secret"].default == ""
    assert d["google_redirect_uri"].default == ""
    assert d["email_sync_enabled"].default is True
    assert d["email_sync_seconds"].default == 900
    assert d["email_backfill_count"].default == 50


def test_email_settings_have_the_annotated_types():
    fields = Settings.model_fields
    assert fields["google_client_id"].annotation is str
    assert fields["google_client_secret"].annotation is str
    assert fields["google_redirect_uri"].annotation is str
    assert fields["email_sync_enabled"].annotation is bool
    assert fields["email_sync_seconds"].annotation is int
    assert fields["email_backfill_count"].annotation is int
