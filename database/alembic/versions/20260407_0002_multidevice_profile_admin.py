from __future__ import annotations

from alembic import op


revision = "20260407_0002"
down_revision = "20260407_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE devices
        ADD COLUMN IF NOT EXISTS public_key VARCHAR(4096);
        """
    )
    op.execute(
        """
        ALTER TABLE devices
        ADD COLUMN IF NOT EXISTS key_algorithm VARCHAR(64) NOT NULL DEFAULT 'p256-ecdh-v1';
        """
    )
    op.execute(
        """
        ALTER TABLE devices
        ADD COLUMN IF NOT EXISTS key_updated_at TIMESTAMP;
        """
    )

    op.execute(
        """
        ALTER TABLE sessions
        ADD COLUMN IF NOT EXISTS device_id VARCHAR(255);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_sessions_device_id ON sessions (device_id);
        """
    )

    op.execute(
        """
        ALTER TABLE messages
        ADD COLUMN IF NOT EXISTS sender_device_id VARCHAR(255);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_sender_device_id ON messages (sender_device_id);
        """
    )

    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS profile_tag VARCHAR(32);
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_users_is_banned ON users (is_banned);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_users_is_active ON users (is_active);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_is_active;")
    op.execute("DROP INDEX IF EXISTS ix_users_is_banned;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_banned;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS profile_tag;")

    op.execute("DROP INDEX IF EXISTS ix_messages_sender_device_id;")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS sender_device_id;")

    op.execute("DROP INDEX IF EXISTS ix_sessions_device_id;")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS device_id;")

    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS key_updated_at;")
    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS key_algorithm;")
    op.execute("ALTER TABLE devices DROP COLUMN IF EXISTS public_key;")
