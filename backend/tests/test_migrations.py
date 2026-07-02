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
    "provider_accounts", "daily_snapshots", "workouts", "emails",
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
