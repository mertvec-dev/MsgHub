from __future__ import annotations

from alembic import op


revision = "20260414_0003"
down_revision = "20260407_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS role VARCHAR(32) NOT NULL DEFAULT 'user';
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_users_role ON users (role);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_role;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS role;")
