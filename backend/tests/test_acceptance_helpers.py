"""Non-manual coverage for the macOS Contacts acceptance module's real-App-Support
plumbing (M10 hardening Task 3): `real_settings_values()` and the `real_app_support`
fixture that let acceptance tests 3/4 escape the per-test tmp dir the autouse
`contacts_photos_tmpdir` fixture substitutes everywhere else. No FDA, no live
AddressBook, no RUN_MACOS_ACCEPTANCE -- these run in the ordinary suite.
"""
from __future__ import annotations

from app.config import Settings

# Bringing the fixture into this module's namespace is what makes pytest treat it
# as usable here too -- fixture lookup is by name in the requesting module's (or a
# conftest's) namespace, not only where the fixture happens to be defined.
from tests.test_macos_contacts_acceptance import real_app_support  # noqa: F401


def real_settings_values() -> tuple[str, str]:
    """(app_support_dir, contacts_photos_dir) from a FRESH `Settings()` instance --
    what a correctly-configured machine actually resolves: `APP_SUPPORT_DIR` (no
    env_prefix on Settings) or a backend/.env file, falling back to the class
    defaults. `_env_file=None` keeps this hermetic: whatever is or is not on disk
    at backend/.env must never change what these tests assert."""
    fresh = Settings(_env_file=None)
    return fresh.app_support_dir, fresh.contacts_photos_dir


def test_real_settings_values_honours_env_var(monkeypatch):
    monkeypatch.setenv("APP_SUPPORT_DIR", "/tmp/x")
    app_support_dir, _contacts_photos_dir = real_settings_values()
    assert app_support_dir == "/tmp/x"


def test_real_settings_values_falls_back_to_class_default(monkeypatch):
    monkeypatch.delenv("APP_SUPPORT_DIR", raising=False)
    app_support_dir, _contacts_photos_dir = real_settings_values()
    assert app_support_dir == Settings.model_fields["app_support_dir"].default


def test_real_app_support_fixture_overrides_the_autouse_tmpdir(real_app_support):
    """While `real_app_support` is active, `settings.app_support_dir` is the REAL
    configured value from `real_settings_values()`, not the per-test tmp dir the
    autouse `contacts_photos_tmpdir` fixture substitutes for every other test --
    i.e. the override actually wins."""
    from app.config import settings

    app_support_dir, _contacts_photos_dir = real_settings_values()
    assert settings.app_support_dir == app_support_dir
