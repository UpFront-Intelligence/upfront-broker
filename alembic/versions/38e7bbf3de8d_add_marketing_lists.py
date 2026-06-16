"""add marketing lists

Revision ID: 38e7bbf3de8d
Revises: b8c9d0e1f2a3
Create Date: 2026-06-16

marketing_lists  — broker-owned, named segment of accounts/contacts for outreach
marketing_list_members — junction: exactly one of account_id / contact_id per row
                         (CHECK enforced), partial unique indexes prevent dups.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '38e7bbf3de8d'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'marketing_lists',
        sa.Column('id',          sa.Integer(),  nullable=False),
        sa.Column('owner_id',    sa.Integer(),  nullable=False),
        sa.Column('name',        sa.String(),   nullable=False),
        sa.Column('description', sa.Text(),     nullable=True),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_id', 'name', name='uq_marketing_lists_owner_name'),
    )
    op.create_index('idx_marketing_lists_owner', 'marketing_lists', ['owner_id'])

    op.create_table(
        'marketing_list_members',
        sa.Column('id',         sa.Integer(), nullable=False),
        sa.Column('list_id',    sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('source',     sa.Text(),    nullable=False, server_default='manual'),
        sa.Column('note',       sa.Text(),    nullable=True),
        sa.Column('added_at',   sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['list_id'],    ['marketing_lists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'],        ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'],        ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            'num_nonnulls(account_id, contact_id) = 1',
            name='chk_mlm_exactly_one_entity',
        ),
    )
    # Partial unique indexes — prevent duplicate membership per entity type
    op.create_index(
        'uix_mlm_list_account',
        'marketing_list_members',
        ['list_id', 'account_id'],
        unique=True,
        postgresql_where=sa.text('account_id IS NOT NULL'),
    )
    op.create_index(
        'uix_mlm_list_contact',
        'marketing_list_members',
        ['list_id', 'contact_id'],
        unique=True,
        postgresql_where=sa.text('contact_id IS NOT NULL'),
    )
    op.create_index('idx_mlm_list_id', 'marketing_list_members', ['list_id'])


def downgrade() -> None:
    op.drop_index('idx_mlm_list_id',       table_name='marketing_list_members')
    op.drop_index('uix_mlm_list_contact',  table_name='marketing_list_members')
    op.drop_index('uix_mlm_list_account',  table_name='marketing_list_members')
    op.drop_table('marketing_list_members')
    op.drop_index('idx_marketing_lists_owner', table_name='marketing_lists')
    op.drop_table('marketing_lists')
