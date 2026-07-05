"""End-to-end smoke test for the live Moodle read-only pipeline (M6).

Drives the REAL MoodleProvider against a live Moodle web-services endpoint
(NC State WolfWare by default) using the stored wstoken, then exercises every
read-only fetch. Unlike the pytest suite (which fakes every provider via
conftest), this makes real authenticated Moodle requests. It performs NO
writes of any kind — Moodle slice-1 is read-only, so this only lists.

Moodle uses a static per-user wstoken (not an OAuth code exchange), so this
runs in two modes:

  * Already connected -- a `provider_accounts` row for 'moodle' exists with a
    token. The script validates it via core_webservice_get_site_info, then
    reads courses / deadlines / grades / announcements / notifications and
    prints counts.
  * Not connected -- prints how to obtain and paste a token (the Security-keys
    page on your Moodle site), then exits 2 (setup needed, not a failure).

Run it by hand once a token is stored (NOT in CI):

    python -m app.smoke_moodle

Exit status: 0 if every leg passed, 1 on a pipeline failure, 2 if Moodle isn't
connected yet (paste a token via POST /api/moodle/connect first).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from . import providers
from .config import settings
from .store import store


class Reporter:
    def __init__(self) -> None:
        self.failed = False

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
        self.failed = self.failed or not ok
        return ok


def _print_connect_help() -> None:
    print("\nMoodle is not connected yet. To connect end-to-end:")
    print(f"  1. Sign in to your Moodle site ({settings.moodle_base_url}).")
    print("  2. Go to your profile -> Preferences -> Security keys (or")
    print("     '/user/managetoken.php') and copy the 'Moodle mobile web service'")
    print("     token (a 32-character hex string).")
    print("  3. Start the backend and POST the token to the connect endpoint:")
    print("       curl -s -X POST http://localhost:8000/api/moodle/connect \\")
    print("            -H 'Content-Type: application/json' \\")
    print("            -d '{\"token\": \"<your-wstoken>\"}'")
    print("     (or paste it into the Connect Moodle card on the School screen).")
    print("  4. Re-run `python -m app.smoke_moodle` afterwards.")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="    ! %(name)s: %(message)s")
    r = Reporter()
    print("Scuffed OS -- live Moodle read-only pipeline smoke test")
    print(f"  owner={settings.owner!r}  moodle_base_url={settings.moodle_base_url!r}")

    print("\nPreconditions:")
    if not r.check(bool(settings.database_url),
                   "DATABASE_URL configured (the stored token lives in the database)"):
        print("\nAborting: no DATABASE_URL -- there is nowhere for a token to be stored.")
        return 1

    provider = providers.get("moodle")
    if not r.check(provider is not None, "Moodle provider registered"):
        return 1

    account = store.get_provider_account("moodle")
    if account is None:
        r.check(False, "Moodle account connected (provider_accounts row exists)",
                "not connected -- see steps below")
        _print_connect_help()
        return 2
    r.check(True, "Moodle account connected",
            f"status={account['status']} provider_user_id={account.get('provider_user_id')}")

    try:
        print("\n1. Token validity (core_webservice_get_site_info):")
        tokens = store.get_provider_tokens("moodle")
        if not r.check(tokens is not None and bool(tokens.access_token),
                       "wstoken present server-side"):
            return 1
        provider.set_tokens(tokens)
        info = provider.get_site_info(tokens.access_token)
        userid = info.get("userid")
        r.check(bool(info.get("sitename")) and bool(info.get("release")),
                "site info resolved",
                f"sitename={info.get('sitename')!r} release={info.get('release')!r}")
        if not r.check(isinstance(userid, int) and userid > 0,
                       "site info returned a numeric userid", str(userid)):
            return 1

        print("\n2. Courses (core_enrol_get_users_courses):")
        courses = provider.fetch_courses(userid)
        r.check(True, "courses fetched", f"{len(courses)}")
        r.check(bool(courses), "Moodle returned at least one enrolled course")
        course_ids = [c.source_id for c in courses]
        for c in courses[:5]:
            print(f"        - {c.shortname!r} :: {c.fullname!r} "
                  f"(progress={c.progress})")

        print("\n3. Deadline timeline (core_calendar_get_action_events_by_timesort):")
        now = datetime.now(timezone.utc)
        deadlines = provider.fetch_deadlines(now)
        r.check(True, "deadlines fetched", f"{len(deadlines)}")
        for d in deadlines[:5]:
            print(f"        - {d.name!r} ({d.module_name}) due {d.due_at} "
                  f"course={d.course_id}")

        print("\n4. Grades (gradereport_user_get_grade_items, per course):")
        grades = provider.fetch_grades(userid, course_ids)
        r.check(True, "grades fetched", f"{len(grades)}")
        for g in grades[:5]:
            print(f"        - {g.item_name!r} ({g.item_type}) = {g.grade_formatted!r} "
                  f"course={g.course_id}")

        print("\n5. Announcements (mod_forum news forums):")
        announcements = provider.fetch_announcements(userid, course_ids)
        r.check(True, "announcements fetched", f"{len(announcements)}")
        for a in announcements[:5]:
            print(f"        - {a.subject!r} by {a.author!r} at {a.created_at} "
                  f"course={a.course_id}")

        print("\n6. Notifications (message_popup_get_popup_notifications):")
        notifications = provider.fetch_notifications(userid)
        r.check(True, "notifications fetched", f"{len(notifications)}")
        for n in notifications[:5]:
            print(f"        - {n.subject!r} read={n.read} at {n.created_at}")
    except Exception as exc:  # a live call blew up -- report, don't traceback-dump
        r.check(False, f"pipeline raised {type(exc).__name__}", str(exc)[:140])

    print("\nRESULT:", "ALL PASSED" if not r.failed else "FAILURES -- see above")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
