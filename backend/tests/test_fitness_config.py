"""M4 config: WHOOP credentials + fitness-sync knobs land on Settings with spec defaults."""
from app.config import Settings, settings


def test_whoop_and_sync_defaults():
    assert settings.whoop_client_id == ""
    assert settings.whoop_client_secret == ""
    assert settings.whoop_redirect_uri == "https://scuffedcorporation.com/auth/whoop/callback"
    assert settings.fitness_sync_enabled is True
    assert settings.fitness_sync_seconds == 1800
    assert settings.whoop_backfill_days == 30


def test_settings_have_the_annotated_types():
    fields = Settings.model_fields
    assert fields["whoop_client_id"].annotation is str
    assert fields["fitness_sync_enabled"].annotation is bool
    assert fields["fitness_sync_seconds"].annotation is int
    assert fields["whoop_backfill_days"].annotation is int
