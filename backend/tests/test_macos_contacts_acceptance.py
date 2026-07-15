"""Manual, on-hardware acceptance for the signed macOS package (M10 s1).

Run by hand on a signed, notarized ScuffedOS.app with Full Disk Access granted to
the BUNDLE (not to your terminal). These are skipped in CI and `tauri dev`: the
TCC responsible-process is the app bundle, System Settings deep links only open a
real settings pane, and the live AddressBook uses WAL so a private snapshot must
include -wal/-shm. Flip RUN_MACOS_ACCEPTANCE=1 on the target machine to run them.
"""
import os

import pytest

pytestmark = [
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("RUN_MACOS_ACCEPTANCE") != "1",
        reason="manual: signed macOS bundle + Full Disk Access only (not CI/tauri dev)",
    ),
]


def test_fda_responsible_process_is_the_signed_bundle():
    """With FDA granted to ScuffedOS.app, probe_access() -> 'granted' from inside
    the bundle; granting FDA to Terminal alone must NOT satisfy it."""
    from app.providers import macos_contacts
    macos_contacts.configure()                 # real detection
    assert macos_contacts.probe_access() == "granted"


def test_system_settings_deep_link_opens_full_disk_access():
    """The 'Grant Full Disk Access' button opens the Privacy_AllFiles pane. Verify
    manually that the pane appears with ScuffedOS listed."""
    import subprocess
    url = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
    assert subprocess.run(["open", url]).returncode == 0


def test_live_wal_read_returns_current_contacts():
    """Against the real, actively-written AddressBook (WAL mode), a full sync reads
    a non-empty COMPLETE snapshot including a contact you edited seconds earlier."""
    from app.providers import macos_contacts
    from app.providers.macos_contacts import SnapshotStatus
    macos_contacts.configure()
    from app.config import settings
    snap = macos_contacts.read_snapshot(
        region=settings.contacts_default_region,
        photos_dir=os.path.expanduser(settings.contacts_photos_dir))
    assert snap.status is SnapshotStatus.COMPLETE_NONEMPTY
    assert snap.people


def test_photos_land_under_app_support_not_repo():
    """Extracted photos are written under the App Support contact_photos root, with
    a detected media type, never in the repo/./data."""
    from app.config import settings
    root = os.path.join(os.path.expanduser(settings.app_support_dir), "contact_photos")
    assert os.path.isdir(root)
    files = os.listdir(root)
    assert any(f.split(".")[-1] in {"jpg", "jpeg", "png", "heic"} for f in files)
