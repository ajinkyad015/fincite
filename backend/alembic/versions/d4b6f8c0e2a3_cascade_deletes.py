"""ON DELETE CASCADE for conversation/message children

``DELETE /api/conversation/{id}`` used to fail with a foreign-key violation on
any thread that had messages. The application layer also deletes children
explicitly (see ``crud.delete_conversation``); this migration is the database-
level guarantee so no code path can leave orphans behind.

Constraints are re-created with their default Postgres names
(``<table>_<column>_fkey``), which is what the original migrations produced.

Revision ID: d4b6f8c0e2a3
Revises: c3a5e7b9d1f2
Create Date: 2026-10-26 00:00:03.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4b6f8c0e2a3"
down_revision = "c3a5e7b9d1f2"
branch_labels = None
depends_on = None


_FOREIGN_KEYS = (
    # (table, column, referred_table, constraint_name)
    ("message", "conversation_id", "conversation", "message_conversation_id_fkey"),
    ("messagesubprocess", "message_id", "message", "messagesubprocess_message_id_fkey"),
    (
        "conversationdocument",
        "conversation_id",
        "conversation",
        "conversationdocument_conversation_id_fkey",
    ),
    (
        "conversationdocument",
        "document_id",
        "document",
        "conversationdocument_document_id_fkey",
    ),
)


def upgrade() -> None:
    for table, column, referred, constraint in _FOREIGN_KEYS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint,
            table,
            referred,
            [column],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    for table, column, referred, constraint in _FOREIGN_KEYS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(constraint, table, referred, [column], ["id"])
