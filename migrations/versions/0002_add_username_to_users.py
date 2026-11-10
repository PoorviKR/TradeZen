"""Add username column to users table with data preservation and backfill.

Revision ID: 0002_username
Revises: 0001_initial
Create Date: 2026-11-10 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0002_username'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add username as nullable initially so existing records can be backfilled safely
    op.add_column('users', sa.Column('username', sa.String(length=50), nullable=True))

    # 2. Backfill existing user accounts preserving all user data
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind else "postgresql"

    if dialect_name == "postgresql":
        op.execute(
            "UPDATE users SET username = LOWER(REGEXP_REPLACE(SPLIT_PART(email, '@', 1), '[^a-zA-Z0-9_]', '_', 'g')) "
            "WHERE username IS NULL;"
        )
        op.execute(
            "UPDATE users SET username = 'user_' || id "
            "WHERE username IS NULL OR LENGTH(username) < 3;"
        )
    else:
        op.execute("UPDATE users SET username = 'user_' || id WHERE username IS NULL;")

    # 3. Enforce NOT NULL constraint
    op.alter_column('users', 'username', nullable=False)

    # 4. Create unique index on username
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_column('users', 'username')
