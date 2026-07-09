"""M6 base contract (§B): the six Normalized* Moodle dataclasses instantiate
with their frozen fields, MoodleSnapshot bundles them with empty-list defaults,
and MoodleProvider is a runtime_checkable Protocol extending OAuthProvider."""
from datetime import datetime, timezone

from app.providers.base import (
    MoodleProvider,
    MoodleSnapshot,
    NormalizedAnnouncement,
    NormalizedAssignment,
    NormalizedCourse,
    NormalizedDeadline,
    NormalizedGrade,
    NormalizedNotification,
    OAuthProvider,
)

UTC = timezone.utc


def test_normalized_course_fields():
    c = NormalizedCourse(source="moodle", source_id="72", shortname="CSC216",
                         fullname="Programming Concepts — Java")
    assert c.source == "moodle" and c.source_id == "72"
    assert c.shortname == "CSC216"
    # defaults
    assert c.progress is None and c.start_at is None and c.end_at is None
    assert c.last_access_at is None and c.hidden is False


def test_normalized_deadline_requires_due_at():
    due = datetime(2026, 7, 10, 23, 59, tzinfo=UTC)
    d = NormalizedDeadline(source="moodle", source_id="e1", course_id="72",
                           name="Summative assignment is due", module_name="assign",
                           event_type="due", due_at=due)
    assert d.due_at == due and d.overdue is False and d.url == ""


def test_normalized_assignment_defaults():
    a = NormalizedAssignment(source="moodle", source_id="a1", course_id="72",
                             cmid="900", name="Project 1")
    assert a.due_at is None and a.cutoff_at is None and a.grade_max is None
    assert a.submission_status == "none" and a.grading_status == "" and a.graded is False


def test_normalized_grade_defaults():
    g = NormalizedGrade(source="moodle", source_id="gi1", course_id="72",
                        item_name="Project 1", item_type="mod")
    assert g.grade_formatted == "-" and g.grade_raw is None
    assert g.grade_min is None and g.grade_max is None and g.graded_at is None


def test_normalized_announcement_requires_created_at():
    created = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    an = NormalizedAnnouncement(source="moodle", source_id="d1", course_id="72",
                                forum_id="f1", subject="Welcome", author="Prof X",
                                created_at=created)
    assert an.created_at == created and an.summary_html == "" and an.url == ""


def test_normalized_notification_defaults():
    n = NormalizedNotification(source="moodle", source_id="n1", subject="Graded")
    assert n.full_message == "" and n.context_url == ""
    assert n.created_at is None and n.read is False


def test_moodle_snapshot_defaults_to_empty_lists():
    snap = MoodleSnapshot()
    assert snap.courses == [] and snap.deadlines == [] and snap.assignments == []
    assert snap.grades == [] and snap.announcements == [] and snap.notifications == []
    # distinct list instances (field(default_factory=list), not a shared mutable)
    snap.courses.append(1)
    assert MoodleSnapshot().courses == []


def test_moodle_provider_is_runtime_checkable_and_extends_oauth():
    # Py3.14 typing.Protocol.__subclasscheck__ raises TypeError for
    # issubclass() between two Protocols that have a non-method member
    # (OAuthProvider.name: str) — same limitation already applies to
    # FitnessProvider/EmailProvider, neither of which use issubclass() in
    # their own tests (see test_providers_base.py, isinstance()-only).
    # Assert the real class hierarchy directly instead.
    assert OAuthProvider in MoodleProvider.__mro__

    class _Impl:
        name = "moodle"
        def authorize_url(self, state): return ""
        def exchange_code(self, code): ...
        def refresh(self, tokens): ...
        def revoke(self, tokens): ...
        def set_tokens(self, tokens): ...
        def on_connected(self): ...
        def on_disconnect(self): ...
        def get_site_info(self, token): return {}
        def fetch_school_snapshot(self, since): return MoodleSnapshot()

    assert isinstance(_Impl(), MoodleProvider)
