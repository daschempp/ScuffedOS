"""M2: mem0 mirror link + pgvector extension.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("mem0_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_memories_mem0_id"), "memories", ["mem0_id"])
    # Mem0's vector store lives in this same database (spec §2). The extension
    # ships with Supabase and the pgvector docker image; SQLite (tests) skips it.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.drop_index(op.f("ix_memories_mem0_id"), table_name="memories")
    op.drop_column("memories", "mem0_id")
