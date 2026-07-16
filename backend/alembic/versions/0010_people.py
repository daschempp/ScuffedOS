"""People domain (M10 s1): source-aware contacts directory + handle index +
Contacts connector consent/lifecycle state.

Creates three tables:
  * people               — contacts keyed (owner, source, source_id)
  * person_handle        — normalized handle -> person index (resolve_handle)
  * contacts_sync_state  — one row per owner; app consent (enabled, default off)
                           tracked separately from FDA access + normalization_region

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("organization", sa.Text(), nullable=False),
        sa.Column("job_title", sa.Text(), nullable=False),
        sa.Column("phones", JSONField, nullable=False),
        sa.Column("emails", JSONField, nullable=False),
        sa.Column("photo_key", sa.Text(), nullable=True),
        sa.Column("has_photo", sa.Boolean(), nullable=False),
        sa.Column("relationship", sa.String(length=32), nullable=True),
        sa.Column("relationship_strength", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_from_source_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", JSONField, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "source", "source_id",
                            name="uq_people_owner_source_source_id"),
    )
    op.create_index(op.f("ix_people_owner"), "people", ["owner"])
    op.create_index(op.f("ix_people_source"), "people", ["source"])
    op.create_index(op.f("ix_people_source_id"), "people", ["source_id"])

    op.create_table(
        "person_handle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.Integer(),
                  sa.ForeignKey("people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=320), nullable=False),
        sa.Column("possible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("person_id", "kind", "value",
                            name="uq_person_handle_person_kind_value"),
    )
    op.create_index(op.f("ix_person_handle_owner"), "person_handle", ["owner"])
    op.create_index(op.f("ix_person_handle_person_id"), "person_handle", ["person_id"])
    op.create_index(op.f("ix_person_handle_value"), "person_handle", ["value"])

    op.create_table(
        "contacts_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("access", sa.String(length=16), nullable=False),
        sa.Column("normalization_region", sa.String(length=8), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", name="uq_contacts_sync_state_owner"),
    )


def downgrade() -> None:
    op.drop_table("contacts_sync_state")
    op.drop_table("person_handle")
    op.drop_table("people")
