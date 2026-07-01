"""M4 config: WHOOP credentials + fitness-sync knobs land on Settings with spec defaults."""
from app.config import Settings


def test_whoop_and_sync_defaults():
    # Assert the declared code defaults on the model fields, independent of any
    # local backend/.env or env vars — a real WHOOP setup fills client_id/secret
    # in .env, which must NOT break this defaults check.
    d = Settings.model_fields
    assert d["whoop_client_id"].default == ""
    assert d["whoop_client_secret"].default == ""
    assert d["whoop_redirect_uri"].default == "https://scuffedcorporation.com/auth/whoop/callback"
    assert d["fitness_sync_enabled"].default is True
    assert d["fitness_sync_seconds"].default == 1800
    assert d["whoop_backfill_days"].default == 30


def test_settings_have_the_annotated_types():
    fields = Settings.model_fields
    assert fields["whoop_client_id"].annotation is str
    assert fields["fitness_sync_enabled"].annotation is bool
    assert fields["fitness_sync_seconds"].annotation is int
    assert fields["whoop_backfill_days"].annotation is int
