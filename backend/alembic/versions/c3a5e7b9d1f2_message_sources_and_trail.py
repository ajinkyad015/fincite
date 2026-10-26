"""message.sources + research-trail labels

Citations become first-class on the message (``sources`` JSONB) so a client
does not have to walk ``sub_processes`` to render source chips, and each
sub-process gets a human label plus a duration for the trail UI.

``sources`` is back-filled from the SUB_QUESTION metadata that the callback
handler has always recorded, so existing threads keep their citations.

Revision ID: c3a5e7b9d1f2
Revises: b2e4d6f8a0c1
Create Date: 2026-10-26 00:00:02.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c3a5e7b9d1f2"
down_revision = "b2e4d6f8a0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message",
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "messagesubprocess", sa.Column("name", sa.String(length=300), nullable=True)
    )
    op.add_column(
        "messagesubprocess", sa.Column("duration_ms", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("messagesubprocess", "duration_ms")
    op.drop_column("messagesubprocess", "name")
    op.drop_column("message", "sources")
