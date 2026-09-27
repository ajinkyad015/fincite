"""Initial schema — full consolidated migration

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-23

Creates all tables from scratch to match the current SQLAlchemy models:

  conversation        — id, title, created_at, updated_at
  conversationdocument— id, conversation_id, document_id, created_at, updated_at
  document            — id, url, metadata_map,
                        filename, status, progress,
                        company_name, company_symbol, exchange,
                        document_type, financial_year, report_date,
                        pages, file_size, language, error_message,
                        created_at, updated_at
  message             — id, conversation_id, content, role, status,
                        created_at, updated_at
  messagesubprocess   — id, message_id, source, status, metadata_map,
                        created_at, updated_at
  messagesource       — id, message_id, document_id, index, page,
                        excerpt, score, created_at, updated_at
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Enum definitions (must be created before the tables that use them)
# ---------------------------------------------------------------------------

message_role_enum = postgresql.ENUM(
    "user", "assistant",
    name="MessageRoleEnum",
    create_type=False,
)

message_status_enum = postgresql.ENUM(
    "PENDING", "SUCCESS", "ERROR",
    name="MessageStatusEnum",
    create_type=False,
)

message_subprocess_status_enum = postgresql.ENUM(
    "PENDING", "FINISHED",
    name="MessageSubProcessStatusEnum",
    create_type=False,
)

# All known MessageSubProcessSourceEnum values (union of CBEventType + custom).
# NOTE: llama-index >= 0.10.x emits FUNCTION_CALL (not FUNCTION_CALLING).
# TREE is no longer in CBEventType but kept here for backward compat.
message_subprocess_source_enum = postgresql.ENUM(
    "CHUNKING",
    "NODE_PARSING",
    "EMBEDDING",
    "LLM",
    "QUERY",
    "RETRIEVE",
    "SYNTHESIZE",
    "TREE",
    "SUB_QUESTION",
    "TEMPLATING",
    "FUNCTION_CALL",
    "EXCEPTION",
    "AGENT_STEP",
    "RERANKING",
    "CONSTRUCTED_QUERY_ENGINE",
    "SUB_QUESTIONS",
    name="MessageSubProcessSourceEnum",
    create_type=False,
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Create enum types
    # ------------------------------------------------------------------
    message_role_enum.create(op.get_bind(), checkfirst=True)
    message_status_enum.create(op.get_bind(), checkfirst=True)
    message_subprocess_status_enum.create(op.get_bind(), checkfirst=True)
    message_subprocess_source_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # conversation
    # ------------------------------------------------------------------
    op.create_table(
        "conversation",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversation_id"), "conversation", ["id"], unique=False)

    # ------------------------------------------------------------------
    # document
    # ------------------------------------------------------------------
    op.create_table(
        "document",
        sa.Column("id", sa.UUID(), nullable=False),
        # Legacy / core fields
        sa.Column("url", sa.String(), nullable=False),
        sa.Column(
            "metadata_map",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        # Promoted product-facing fields
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ready"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("company_name", sa.String(), nullable=True),
        sa.Column("company_symbol", sa.String(), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("document_type", sa.String(), nullable=True),
        sa.Column("financial_year", sa.String(), nullable=True),
        sa.Column("report_date", sa.String(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index(op.f("ix_document_id"), "document", ["id"], unique=False)

    # ------------------------------------------------------------------
    # conversationdocument
    # ------------------------------------------------------------------
    op.create_table(
        "conversationdocument",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversationdocument_id"),
        "conversationdocument",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversationdocument_conversation_id"),
        "conversationdocument",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversationdocument_document_id"),
        "conversationdocument",
        ["document_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # message
    # ------------------------------------------------------------------
    op.create_table(
        "message",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column(
            "role",
            message_role_enum,
            nullable=True,
        ),
        sa.Column(
            "status",
            message_status_enum,
            nullable=True,
            server_default="PENDING",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_message_id"), "message", ["id"], unique=False)
    op.create_index(
        op.f("ix_message_conversation_id"),
        "message",
        ["conversation_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # messagesubprocess
    # ------------------------------------------------------------------
    op.create_table(
        "messagesubprocess",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column(
            "source",
            message_subprocess_source_enum,
            nullable=True,
        ),
        sa.Column(
            "status",
            message_subprocess_status_enum,
            nullable=False,
            server_default="FINISHED",
        ),
        sa.Column(
            "metadata_map",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messagesubprocess_id"), "messagesubprocess", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_messagesubprocess_message_id"),
        "messagesubprocess",
        ["message_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # messagesource  (citations / grounding references)
    # ------------------------------------------------------------------
    op.create_table(
        "messagesource",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messagesource_id"), "messagesource", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_messagesource_message_id"),
        "messagesource",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_messagesource_document_id"),
        "messagesource",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_index(op.f("ix_messagesource_document_id"), table_name="messagesource")
    op.drop_index(op.f("ix_messagesource_message_id"), table_name="messagesource")
    op.drop_index(op.f("ix_messagesource_id"), table_name="messagesource")
    op.drop_table("messagesource")

    op.drop_index(op.f("ix_messagesubprocess_message_id"), table_name="messagesubprocess")
    op.drop_index(op.f("ix_messagesubprocess_id"), table_name="messagesubprocess")
    op.drop_table("messagesubprocess")

    op.drop_index(op.f("ix_message_conversation_id"), table_name="message")
    op.drop_index(op.f("ix_message_id"), table_name="message")
    op.drop_table("message")

    op.drop_index(op.f("ix_conversationdocument_document_id"), table_name="conversationdocument")
    op.drop_index(op.f("ix_conversationdocument_conversation_id"), table_name="conversationdocument")
    op.drop_index(op.f("ix_conversationdocument_id"), table_name="conversationdocument")
    op.drop_table("conversationdocument")

    op.drop_index(op.f("ix_document_id"), table_name="document")
    op.drop_table("document")

    op.drop_index(op.f("ix_conversation_id"), table_name="conversation")
    op.drop_table("conversation")

    # Drop enum types
    message_subprocess_source_enum.drop(op.get_bind(), checkfirst=True)
    message_subprocess_status_enum.drop(op.get_bind(), checkfirst=True)
    message_status_enum.drop(op.get_bind(), checkfirst=True)
    message_role_enum.drop(op.get_bind(), checkfirst=True)
