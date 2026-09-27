"""Fix MessageSubProcessSourceEnum: rename FUNCTION_CALLING → FUNCTION_CALL

The installed version of llama-index emits CBEventType.FUNCTION_CALL (no
"ING" suffix).  The enum in the database still has the old "FUNCTION_CALLING"
value from the initial migration, causing an
asyncpg.exceptions.InvalidTextRepresentationError on every request that
triggers a function-call event.

This migration:
  1. Adds the new label "FUNCTION_CALL" to the enum.
     PostgreSQL requires ALTER TYPE … ADD VALUE to be committed before the new
     value can be used, so we commit the open transaction first, then issue
     ADD VALUE, then begin a new transaction for the UPDATE.
  2. Back-fills any existing rows that still carry the old label.
  3. DOES NOT drop "FUNCTION_CALLING" — PostgreSQL does not support removing
     enum values without recreating the type; keeping it is harmless and safe.

Revision ID: 0002_fix_function_call_enum
Revises: 0001_initial
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "0002_fix_function_call_enum"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires that ALTER TYPE … ADD VALUE is committed BEFORE the
    # new value can be used in any DML.  Alembic wraps each migration in a
    # transaction by default, which prevents this.
    #
    # The recommended workaround (works with both psycopg2 and asyncpg) is to:
    #   1. Commit the open transaction explicitly.
    #   2. Run ADD VALUE (now outside any transaction — committed immediately).
    #   3. Re-open a new transaction for subsequent DML.
    #
    # We use op.get_context().bind to get the underlying synchronous
    # connection that Alembic has already set up.

    conn = op.get_bind()

    # ── Step 1: commit the open transaction ──────────────────────────────────
    conn.execute(sa.text("COMMIT"))

    # ── Step 2: ADD VALUE runs outside any transaction block ─────────────────
    conn.execute(
        sa.text(
            "ALTER TYPE \"MessageSubProcessSourceEnum\" ADD VALUE IF NOT EXISTS 'FUNCTION_CALL'"
        )
    )

    # ── Step 3: back-fill stale rows in a new transaction ────────────────────
    conn.execute(sa.text("BEGIN"))
    conn.execute(
        sa.text(
            """
            UPDATE messagesubprocess
            SET    source = 'FUNCTION_CALL'::"MessageSubProcessSourceEnum"
            WHERE  source = 'FUNCTION_CALLING'::"MessageSubProcessSourceEnum"
            """
        )
    )
    # Alembic will issue the final COMMIT when the migration context exits.


def downgrade() -> None:
    # PostgreSQL does not allow removing enum values, so downgrade is a no-op.
    # Re-running the previous migration (0001_initial downgrade) will drop the
    # entire type along with the table.
    pass
