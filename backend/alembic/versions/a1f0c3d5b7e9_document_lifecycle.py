"""document lifecycle: status, progress, counts, content hash

Adds the columns the library UI polls while a filing indexes in the background:
``status`` / ``progress`` / ``error`` plus denormalised ``page_count``,
``file_size`` and ``content_hash``.

Existing rows are back-filled as ``ready`` (they were indexed synchronously by
the old upload endpoint) and their ``content_hash`` is lifted out of
``metadata_map`` into an indexed column.

Revision ID: a1f0c3d5b7e9
Revises: 663b3fea3024
Create Date: 2026-10-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1f0c3d5b7e9"
down_revision = "663b3fea3024"
branch_labels = None
depends_on = None

DOCUMENT_STATUS_VALUES = (
    "uploaded",
    "parsing",
    "chunking",
    "embedding",
    "indexing",
    "ready",
    "failed",
)


def upgrade() -> None:
    document_status = postgresql.ENUM(
        *DOCUMENT_STATUS_VALUES, name="DocumentStatusEnum", create_type=False
    )
    document_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "document",
        sa.Column(
            "status",
            postgresql.ENUM(*DOCUMENT_STATUS_VALUES, name="DocumentStatusEnum", create_type=False),
            nullable=False,
            server_default="uploaded",
        ),
    )
    op.add_column(
        "document",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("document", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("document", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("document", sa.Column("file_size", sa.BigInteger(), nullable=True))
    op.add_column("document", sa.Column("content_hash", sa.String(length=64), nullable=True))

    # Back-fill: everything that already exists was indexed by the synchronous
    # upload endpoint, so it is ready and complete.
    op.execute("UPDATE document SET status = 'ready', progress = 100")

    op.execute(
        """
        UPDATE document
           SET content_hash = metadata_map->>'content_hash'
         WHERE metadata_map ? 'content_hash'
           AND metadata_map->>'content_hash' IS NOT NULL
        """
    )

    op.create_index(
        op.f("ix_document_content_hash"), "document", ["content_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_content_hash"), table_name="document")
    op.drop_column("document", "content_hash")
    op.drop_column("document", "file_size")
    op.drop_column("document", "page_count")
    op.drop_column("document", "error")
    op.drop_column("document", "progress")
    op.drop_column("document", "status")
    op.execute('DROP TYPE IF EXISTS "DocumentStatusEnum"')
