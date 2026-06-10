"""add engagements table

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-10

Brokerage engagement pipeline — tracks the broker's mandate with a client
(listing, rep, BOV, consulting, referral) independent of `deals`, which
represents an actual property transaction. client_account_id and
subject_property_id are nullable, ON DELETE SET NULL so deleting an
account/property doesn't take the engagement record with it.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'engagements',
        sa.Column('id',                  sa.Integer(),  nullable=False),
        sa.Column('owner_id',            sa.Integer(),  nullable=False),
        sa.Column('type',                sa.String(),   nullable=False),
        sa.Column('stage',                sa.String(),  nullable=False, server_default='pursuing'),
        sa.Column('signed_agreement',    sa.Boolean(),  nullable=False, server_default='false'),
        sa.Column('agreement_date',      sa.Date(),     nullable=True),
        sa.Column('client_account_id',   sa.Integer(),  nullable=True),
        sa.Column('subject_property_id', sa.Integer(),  nullable=True),
        sa.Column('name',                sa.String(),   nullable=False),
        sa.Column('notes',               sa.Text(),     nullable=True),
        sa.Column('created_at',          sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['owner_id'],            ['users.id']),
        sa.ForeignKeyConstraint(['client_account_id'],   ['accounts.id'],   ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['subject_property_id'], ['properties.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_engagements_owner_stage', 'engagements', ['owner_id', 'stage'])
    op.create_index('idx_engagements_owner_type',  'engagements', ['owner_id', 'type'])


def downgrade() -> None:
    op.drop_index('idx_engagements_owner_type',  table_name='engagements')
    op.drop_index('idx_engagements_owner_stage', table_name='engagements')
    op.drop_table('engagements')
