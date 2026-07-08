"""M8 Ship/Tauri config seam: the SCUFFEDOS_MANAGED_PG flag defaults off
(dev/tests unchanged) and the app-support path settings expose safe,
import-time-instantiable defaults following the existing local-path idiom."""

from app.config import Settings


def test_managed_pg_defaults_off():
    field = Settings.model_fields["scuffedos_managed_pg"]
    assert field.default is False
    assert field.annotation is bool


def test_app_support_dir_default():
    field = Settings.model_fields["app_support_dir"]
    assert field.annotation is str
    assert "Application Support/ScuffedOS" in field.default


def test_managed_pg_role_and_dbname_defaults():
    assert Settings.model_fields["managed_pg_superuser"].default == "scuffedos"
    assert Settings.model_fields["managed_pg_dbname"].default == "scuffedos"


def test_managed_pg_reads_env(monkeypatch):
    monkeypatch.setenv("SCUFFEDOS_MANAGED_PG", "1")
    fresh = Settings()
    assert fresh.scuffedos_managed_pg is True


def test_flag_off_leaves_database_url_default_empty():
    # Fresh Settings with no env: default database_url stays empty so the
    # dev/external-DATABASE_URL path is entirely unaffected by the new flag.
    field = Settings.model_fields["database_url"]
    assert field.default == ""
