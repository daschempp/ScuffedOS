"""M6 config: Moodle base URL + moodle-sync knobs land on Settings with spec defaults."""
from app.config import Settings


def test_moodle_defaults():
    # Assert declared code defaults on the model fields, independent of any local
    # backend/.env or env vars — a real WolfWare setup never fills these in .env,
    # but this defaults check must hold regardless (matches test_email_config.py).
    d = Settings.model_fields
    assert d["moodle_base_url"].default.endswith("wolfware.ncsu.edu")
    assert d["moodle_base_url"].default == "https://moodle-courses2527.wolfware.ncsu.edu"
    assert d["moodle_sync_enabled"].default is True
    assert d["moodle_sync_seconds"].default == 900
    assert d["moodle_backfill_days_ahead"].default == 60


def test_moodle_settings_have_the_annotated_types():
    fields = Settings.model_fields
    assert fields["moodle_base_url"].annotation is str
    assert fields["moodle_sync_enabled"].annotation is bool
    assert fields["moodle_sync_seconds"].annotation is int
    assert fields["moodle_backfill_days_ahead"].annotation is int
