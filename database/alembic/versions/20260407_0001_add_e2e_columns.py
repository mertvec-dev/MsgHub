from __future__ import annotations

from alembic import op


revision = "20260407_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE rooms
        ADD COLUMN IF NOT EXISTS current_key_version INTEGER NOT NULL DEFAULT 1;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rooms_current_key_version
        ON rooms (current_key_version);
        """
    )
    op.execute(
        """
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS key_version INTEGER;
        """
    )
    op.execute(
        """
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS nonce VARCHAR(12);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rooms_current_key_version;")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS nonce;")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS key_version;")
    op.execute("ALTER TABLE rooms DROP COLUMN IF EXISTS current_key_version;")
