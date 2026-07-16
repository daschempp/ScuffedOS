from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401  — register tables on Base.metadata
from app.db import Base


def test_all_three_tables_exist_on_metadata():
    names = set(Base.metadata.tables)
    assert {"people", "person_handle", "contacts_sync_state"} <= names


def test_people_columns():
    cols = {c.name for c in Base.metadata.tables["people"].columns}
    assert {
        "owner", "source", "source_id", "display_name", "first_name",
        "last_name", "nickname", "organization", "job_title", "phones",
        "emails", "photo_key", "has_photo", "relationship",
        "relationship_strength", "notes", "pinned", "last_contacted_at",
        "removed_from_source_at", "meta", "created_at", "updated_at",
    } <= cols


def test_person_handle_columns():
    cols = {c.name for c in Base.metadata.tables["person_handle"].columns}
    assert {"owner", "person_id", "kind", "value", "possible", "created_at"} <= cols


def test_contacts_sync_state_columns():
    cols = {c.name for c in Base.metadata.tables["contacts_sync_state"].columns}
    assert {
        "owner", "enabled", "status", "access", "normalization_region",
        "last_sync_at", "last_error", "enabled_at", "created_at", "updated_at",
    } <= cols


def test_contacts_sync_state_owner_is_unique():
    table = Base.metadata.tables["contacts_sync_state"]
    unique_cols = {tuple(c.name for c in con.columns)
                   for con in table.constraints
                   if con.__class__.__name__ == "UniqueConstraint"}
    assert ("owner",) in unique_cols


def test_enabled_defaults_off():
    # App consent is OFF until the user explicitly connects (contract).
    col = Base.metadata.tables["contacts_sync_state"].columns["enabled"]
    assert col.default.arg is False


def test_create_all_builds_all_three_on_sqlite():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    tables = set(inspect(eng).get_table_names())
    assert {"people", "person_handle", "contacts_sync_state"} <= tables
    eng.dispose()
