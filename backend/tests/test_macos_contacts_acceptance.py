"""Acceptance record for the signed macOS package's Full Disk Access gate (M10 s1).

Run by hand on a signed, notarized ScuffedOS.app. Flip RUN_MACOS_ACCEPTANCE=1 on
the target machine to un-skip this module; none of the four checks below is
safely automatable from a bare pytest process, so each carries its own further
gate or is an unconditional manual-checklist skip:

- test 1 additionally needs RUN_INSIDE_BUNDLE=1: `probe_access()` run from pytest
  only proves the pytest PROCESS has Full Disk Access, not that the signed app
  BUNDLE is the TCC responsible process (granting FDA to Terminal alone would
  wrongly pass it). Confirming the bundle is responsible needs `pgrep` +
  `launchctl procinfo` against the actually-running packaged backend -- see the
  test's skip reason for the exact commands.
- test 2 always self-skips with a manual checklist. Verifying the Settings ->
  Connectors "Grant Full Disk Access" button opens the real System Settings pane
  needs a human's eyes on the actual pane; shelling out to `open` directly
  bypasses the app's own button, which is the thing that was actually broken.
- tests 3 and 4 read the live, actively-written AddressBook (WAL mode, so a
  private snapshot must include -wal/-shm) and write to the REAL App Support
  contacts-photos root via the `real_app_support` fixture below -- not the
  per-test tmp dir the autouse `contacts_photos_tmpdir` fixture (conftest.py)
  substitutes for every other test in the suite.
"""
from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("RUN_MACOS_ACCEPTANCE") != "1",
        reason="manual: signed macOS bundle + Full Disk Access only (not CI/tauri dev)",
    ),
]


@pytest.fixture()
def real_app_support(contacts_photos_tmpdir):
    """Point `settings.app_support_dir` / `settings.contacts_photos_dir` at the
    REAL configured values (APP_SUPPORT_DIR / a .env file / the class default),
    restoring both on teardown.

    Requesting `contacts_photos_tmpdir` -- the autouse fixture (conftest.py) that
    redirects both settings to a per-test tmp dir for every test -- makes pytest
    set THIS fixture up strictly after it, and tear it down strictly before it
    (fixture finalizers run in reverse setup order). That ordering, not an
    assumption about how pytest sequences autouse vs. requested fixtures, is what
    guarantees the real values are what's actually in effect when the test body
    runs, and that teardown hands a clean per-test tmp dir back to the autouse
    fixture's own teardown.
    """
    from app.config import settings
    from tests.test_acceptance_helpers import real_settings_values

    app_support_dir, contacts_photos_dir = real_settings_values()
    prev_support = settings.app_support_dir
    prev_photos = settings.contacts_photos_dir
    settings.app_support_dir = app_support_dir
    settings.contacts_photos_dir = contacts_photos_dir
    yield
    settings.app_support_dir = prev_support
    settings.contacts_photos_dir = prev_photos


@pytest.mark.skipif(
    os.environ.get("RUN_INSIDE_BUNDLE") != "1",
    reason=(
        "manual, from inside the running packaged app only: probe_access() called "
        "from a bare pytest process only proves pytest itself has Full Disk "
        "Access, not that the signed bundle is the TCC responsible process. To "
        "check that: find the packaged backend's pid (`pgrep -f "
        "scuffedos-backend`), then run `sudo launchctl procinfo <pid> | grep -i "
        "responsible` and confirm it names /Applications/ScuffedOS.app. Set "
        "RUN_INSIDE_BUNDLE=1 and re-run only once you've done that."
    ),
)
def test_fda_responsible_process_is_the_signed_bundle():
    """With FDA granted to ScuffedOS.app, probe_access() -> 'granted' from inside
    the bundle; granting FDA to Terminal alone must NOT satisfy it (see the
    skip reason for the manual check that actually proves this)."""
    from app.providers import macos_contacts
    macos_contacts.configure()                 # real detection
    assert macos_contacts.probe_access() == "granted"


def test_system_settings_deep_link_opens_full_disk_access():
    """The 'Grant Full Disk Access' button (Settings -> Connectors -> Apple
    Contacts card) must open the real Full Disk Access pane. This can only be
    confirmed by a human watching the actual pane appear, so this always
    self-skips with the checklist rather than shelling out to `open` directly
    -- that shortcut bypasses the app's own button, which is the thing that
    was actually broken."""
    pytest.skip(
        "manual checklist, run in the packaged app with FDA off: "
        "1) open ScuffedOS.app -> Settings -> Connectors -> the Apple Contacts "
        "card; 2) click 'Grant Full Disk Access'; 3) confirm the Privacy & "
        "Security -> Full Disk Access pane actually opens (the "
        "x-apple.systempreferences: scheme is allowed via "
        "src-tauri/capabilities/default.json's opener:allow-open-url permission, "
        "scoped to x-apple.systempreferences:*, from Task 1); 4) confirm "
        "ScuffedOS is listed there so it can be toggled on."
    )


def test_live_wal_read_returns_current_contacts(real_app_support):
    """Against the real, actively-written AddressBook (WAL mode), a full sync reads
    a non-empty COMPLETE snapshot including a contact you edited seconds earlier."""
    from app.config import settings
    from app.providers import macos_contacts
    from app.providers.macos_contacts import SnapshotStatus

    macos_contacts.configure()
    snap = macos_contacts.read_snapshot(
        region=settings.contacts_default_region,
        photos_dir=settings.contacts_photos_root())
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people


def test_photos_land_under_app_support_not_repo(real_app_support):
    """Extracted photos are written under the REAL App Support contact_photos
    root, with a detected media type, never in the repo/./data. Independent of
    the other live-read test: performs its own read_snapshot() first so it
    doesn't rely on test-ordering or shared state."""
    from app.config import settings
    from app.providers import macos_contacts

    macos_contacts.configure()
    root = settings.contacts_photos_root()
    macos_contacts.read_snapshot(
        region=settings.contacts_default_region,
        photos_dir=root)
    assert os.path.isdir(root)
    files = os.listdir(root)
    assert any(f.split(".")[-1] in {"jpg", "jpeg", "png", "heic"} for f in files)
