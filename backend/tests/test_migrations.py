"""The Alembic migration chain must build the schema the models expect."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.db import Base, make_engine, normalize_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _make_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def alembic_cfg(tmp_path):
    return _make_cfg(f"sqlite:///{tmp_path}/migrated.db")


ALL_TABLES = {
    "tasks", "memories", "conversations", "conversation_messages",
    "task_reminders", "events", "habits", "habit_completions",
    "meals", "water_days", "nutrition_targets",
    "provider_accounts", "daily_snapshots", "workouts", "insights", "emails",
    "moodle_courses", "moodle_deadlines", "moodle_assignments",
    "moodle_grades", "moodle_announcements", "moodle_notifications",
    "finance_items", "finance_accounts", "finance_transactions",
    "finance_securities", "finance_holdings", "finance_budgets",
    "finance_recurring", "finance_liabilities", "finance_investment_transactions",
    "people", "person_handle", "contacts_sync_state",
}


def test_upgrade_head_builds_full_schema(alembic_cfg, tmp_path):
    command.upgrade(alembic_cfg, "head")
    engine = create_engine(f"sqlite:///{tmp_path}/migrated.db")
    tables = set(inspect(engine).get_table_names())
    assert ALL_TABLES <= tables

    task_cols = {c["name"] for c in inspect(engine).get_columns("tasks")}
    assert {"bucket", "deadline", "prio", "list", "subtasks", "labels",
            "recurrence", "files", "created_at", "completed_at"} <= task_cols
    assert "reminders" not in task_cols  # dropped in 0003 — they fire from task_reminders now

    email_cols = {c["name"] for c in inspect(engine).get_columns("emails")}
    assert {"owner", "source", "source_id", "thread_id", "from_name",
            "from_email", "subject", "snippet", "received_at", "unread",
            "category", "summary_json", "triaged_at", "starred", "label_ids"} <= email_cols
    assert "body" not in email_cols  # privacy: bodies never persisted

    deadline_cols = {c["name"] for c in inspect(engine).get_columns("moodle_deadlines")}
    assert {"owner", "source", "source_id", "course_id", "name",
            "module_name", "event_type", "due_at", "overdue", "url",
            "meta", "created_at", "updated_at"} <= deadline_cols
    assignment_cols = {c["name"] for c in inspect(engine).get_columns("moodle_assignments")}
    assert {"owner", "source", "source_id", "course_id", "cmid", "name",
            "due_at", "cutoff_at", "grade_max", "submission_status",
            "grading_status", "graded", "meta"} <= assignment_cols
    grade_cols = {c["name"] for c in inspect(engine).get_columns("moodle_grades")}
    assert {"owner", "source", "source_id", "course_id", "item_name",
            "item_type", "grade_formatted", "grade_raw", "grade_min",
            "grade_max", "graded_at", "meta"} <= grade_cols
    course_cols = {c["name"] for c in inspect(engine).get_columns("moodle_courses")}
    assert {"owner", "source", "source_id", "shortname", "fullname",
            "progress", "start_at", "end_at", "last_access_at", "hidden",
            "meta"} <= course_cols
    announcement_cols = {c["name"] for c in inspect(engine).get_columns("moodle_announcements")}
    assert {"owner", "source", "source_id", "course_id", "forum_id",
            "subject", "author", "created_at", "summary_html", "url",
            "meta"} <= announcement_cols
    notification_cols = {c["name"] for c in inspect(engine).get_columns("moodle_notifications")}
    assert {"owner", "source", "source_id", "subject", "full_message",
            "context_url", "created_at", "read", "meta"} <= notification_cols

    people_cols = {c["name"] for c in inspect(engine).get_columns("people")}
    assert {"owner", "source", "source_id", "display_name", "first_name",
            "last_name", "nickname", "organization", "job_title", "phones",
            "emails", "photo_key", "has_photo", "relationship",
            "relationship_strength", "notes", "pinned", "last_contacted_at",
            "removed_from_source_at", "meta", "created_at", "updated_at"} <= people_cols

    handle_cols = {c["name"] for c in inspect(engine).get_columns("person_handle")}
    assert {"owner", "person_id", "kind", "value", "possible", "created_at"} <= handle_cols

    state_cols = {c["name"] for c in inspect(engine).get_columns("contacts_sync_state")}
    assert {"owner", "enabled", "status", "access", "normalization_region",
            "last_sync_at", "last_error", "enabled_at",
            "created_at", "updated_at"} <= state_cols

    # Idempotent-upsert + resolve integrity: the composite/unique keys exist.
    people_uqs = {tuple(uc["column_names"])
                  for uc in inspect(engine).get_unique_constraints("people")}
    assert ("owner", "source", "source_id") in people_uqs
    handle_uqs = {tuple(uc["column_names"])
                  for uc in inspect(engine).get_unique_constraints("person_handle")}
    assert ("person_id", "kind", "value") in handle_uqs
    state_uqs = {tuple(uc["column_names"])
                 for uc in inspect(engine).get_unique_constraints("contacts_sync_state")}
    assert ("owner",) in state_uqs             # one consent row per owner

    # Handle lookup + FK cleanup are indexed for resolve_handle.
    handle_idx_cols = {tuple(ix["column_names"])
                       for ix in inspect(engine).get_indexes("person_handle")}
    assert ("value",) in handle_idx_cols
    assert ("person_id",) in handle_idx_cols
    engine.dispose()


def test_downgrade_base_removes_everything(alembic_cfg, tmp_path):
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    engine = create_engine(f"sqlite:///{tmp_path}/migrated.db")
    tables = set(inspect(engine).get_table_names())
    assert not ALL_TABLES & tables
    engine.dispose()


@pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith(("postgres", "postgresql")),
    reason="needs a Postgres TEST_DATABASE_URL (CI service / local docker)",
)
def test_migrations_build_models_schema_on_postgres():
    """Run the real production path — alembic on Postgres — in a scratch
    database, then assert the migrated schema matches the models exactly."""
    admin = make_engine(TEST_DATABASE_URL)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DROP DATABASE IF EXISTS scuffedos_migrate_test (FORCE)"))
        conn.execute(text("CREATE DATABASE scuffedos_migrate_test"))
    admin.dispose()

    scratch_url = normalize_database_url(TEST_DATABASE_URL).rsplit("/", 1)[0] + "/scuffedos_migrate_test"
    command.upgrade(_make_cfg(scratch_url), "head")

    engine = create_engine(scratch_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == [], f"models and migrations drifted: {diff}"
    finally:
        engine.dispose()
