"""add google_id to users, make hashed_password nullable

Revision ID: c7d2e4f8a1b5
Revises: b5e9f3a7d1c2
Create Date: 2026-06-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = 'c7d2e4f8a1b5'
down_revision: Union[str, None] = 'b5e9f3a7d1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    existing_cols    = {c['name'] for c in inspector.get_columns('users')}
    existing_indexes = {i['name'] for i in inspector.get_indexes('users')}

    if 'google_id' not in existing_cols:
        op.add_column('users', sa.Column('google_id', sa.String(), nullable=True))

    if 'ix_users_google_id' not in existing_indexes:
        op.create_index('ix_users_google_id', 'users', ['google_id'], unique=True)

    # Make hashed_password nullable for Google OAuth users.
    # op.alter_column is idempotent on PostgreSQL when the target nullable
    # state already matches — safe to run even if already nullable.
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(),
                    nullable=False)
    op.drop_index('ix_users_google_id', table_name='users')
    op.drop_column('users', 'google_id')
