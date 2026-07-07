"""M8 lifespan wiring: managed-PG boot/stop is gated on SCUFFEDOS_MANAGED_PG.
Flag OFF (the dev/test default) => localdb.boot is never called and startup is
byte-for-byte the old behavior. Flag ON => boot runs before the sync loops and
its returned DSN lands in settings.database_url."""

from app import main as appmain
from app.config import settings


def test_flag_off_does_not_boot_localdb(monkeypatch):
    called = {"boot": 0}
    monkeypatch.setattr(appmain.localdb, "boot",
                        lambda *a, **k: called.__setitem__("boot", called["boot"] + 1) or "x")
    monkeypatch.setattr(settings, "scuffedos_managed_pg", False)
    # Drive only the managed-PG boot branch (not the whole lifespan/loops).
    appmain._maybe_boot_managed_pg()
    assert called["boot"] == 0


def test_flag_on_boots_and_sets_dsn(monkeypatch):
    monkeypatch.setattr(appmain.localdb, "boot",
                        lambda *a, **k: "postgresql+psycopg://scuffedos@/scuffedos?host=/x/run")
    monkeypatch.setattr(settings, "scuffedos_managed_pg", True)
    monkeypatch.setattr(settings, "database_url", "")
    appmain._maybe_boot_managed_pg()
    assert settings.database_url == "postgresql+psycopg://scuffedos@/scuffedos?host=/x/run"


def test_flag_off_shutdown_is_noop(monkeypatch):
    called = {"shutdown": 0}
    monkeypatch.setattr(appmain.localdb, "shutdown",
                        lambda *a, **k: called.__setitem__("shutdown", called["shutdown"] + 1))
    monkeypatch.setattr(settings, "scuffedos_managed_pg", False)
    appmain._maybe_stop_managed_pg()
    assert called["shutdown"] == 0
