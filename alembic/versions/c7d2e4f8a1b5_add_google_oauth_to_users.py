"""add google_id to users, make hashed_password nullable

Revision ID: c7d2e4f8a1b5
Revises: b5e9f3a7d1c2
Create Date: 2026-06-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c7d2e4f8a1b5'
down_revision: Union[str, None] = 'b5e9f3a7d1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('google_id', sa.String(), nullable=True))
    op.create_index('ix_users_google_id', 'users', ['google_id'], unique=True)
    # Google OAuth users have no password — make the column nullable
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(),
                    nullable=False)
    op.drop_index('ix_users_google_id', table_name='users')
    op.drop_column('users', 'google_id')
