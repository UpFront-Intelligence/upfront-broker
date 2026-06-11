"""add contact_phones table

Revision ID: a7b8c9d0e1f2
Revises: f2a3b4c5d6e7
Create Date: 2026-06-11

Multiple labeled phone numbers per contact. contacts.phone remains the
legacy/primary mirror — kept in sync whenever the primary row changes.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contact_phones',
        sa.Column('id',         sa.Integer(), nullable=False),
        sa.Column('owner_id',   sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('label',      sa.Text(),    nullable=True),
        sa.Column('number',     sa.Text(),    nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['owner_id'],   ['users.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_contact_phones_owner_contact', 'contact_phones', ['owner_id', 'contact_id'])


def downgrade() -> None:
    op.drop_index('idx_contact_phones_owner_contact', table_name='contact_phones')
    op.drop_table('contact_phones')
