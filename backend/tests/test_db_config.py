"""URL normalization + a guard that CI really ran the dialect it claims to."""
import os

from app.db import normalize_database_url
from app.store import store


def test_normalize_accepts_raw_supabase_urls():
    # Both spellings providers hand out get rewritten to the psycopg driver.
    assert normalize_database_url(
        "postgresql://postgres.ref:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
    ).startswith("postgresql+psycopg://postgres.ref:pw@")
    assert normalize_database_url("postgres://u:p@host:5432/db") == \
        "postgresql+psycopg://u:p@host:5432/db"


def test_normalize_leaves_explicit_urls_alone():
    assert normalize_database_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"
    assert normalize_database_url("sqlite+pysqlite:///:memory:") == "sqlite+pysqlite:///:memory:"


def test_suite_runs_against_the_advertised_dialect():
    """When TEST_DATABASE_URL points at Postgres, the suite must actually be
    on Postgres — otherwise the CI Postgres job could silently degrade into a
    second SQLite run."""
    engine = store._session_factory.kw["bind"]
    if os.environ.get("TEST_DATABASE_URL", "").startswith(("postgres", "postgresql")):
        assert engine.dialect.name == "postgresql"
    else:
        assert engine.dialect.name == "sqlite"
