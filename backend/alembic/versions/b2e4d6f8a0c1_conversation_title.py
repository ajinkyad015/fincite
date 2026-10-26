"""conversation title + activity timestamp

Threads need a name and an ordering key so the sidebar can be server-backed:
``title`` is derived from the first question (or set explicitly on create) and
``last_message_at`` avoids joining ``message`` just to sort the list.

Existing conversations get their title from their first user message and their
``last_message_at`` from their newest message.

Revision ID: b2e4d6f8a0c1
Revises: a1f0c3d5b7e9
Create Date: 2026-10-26 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2e4d6f8a0c1"
down_revision = "a1f0c3d5b7e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column(
        "conversation", sa.Column("last_message_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        op.f("ix_conversation_last_message_at"),
        "conversation",
        ["last_message_at"],
        unique=False,
    )

    # Back-fill from existing messages.
    op.execute(
        """
        UPDATE conversation c
           SET last_message_at = m.last_at
          FROM (
                SELECT conversation_id, MAX(created_at) AS last_at
                  FROM message
              GROUP BY conversation_id
               ) m
         WHERE m.conversation_id = c.id
        """
    )
    op.execute(
        """
        UPDATE conversation c
           SET title = LEFT(regexp_replace(first_message.content, '\\s+', ' ', 'g'), 80)
          FROM (
                SELECT DISTINCT ON (conversation_id) conversation_id, content
                  FROM message
                 WHERE role = 'user' AND content IS NOT NULL
              ORDER BY conversation_id, created_at
               ) AS first_message
         WHERE first_message.conversation_id = c.id
           AND c.title IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_last_message_at"), table_name="conversation")
    op.drop_column("conversation", "last_message_at")
    op.drop_column("conversation", "title")
