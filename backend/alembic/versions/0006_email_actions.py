"""Email actions (M5 slice-2): starred + label_ids on the emails table.

- emails.starred: bool, from Gmail's STARRED label — surfaced in the reading
  pane and list star indicator.
- emails.label_ids: JSON list of Gmail label ids — the label menu source of
  truth; sync + the label-write endpoints keep Gmail authoritative.
  NO body column — still never persisted (unchanged from 0005).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

JSONField = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "emails",
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "emails",
        sa.Column("label_ids", JSONField, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("emails", "label_ids")
    op.drop_column("emails", "starred")
