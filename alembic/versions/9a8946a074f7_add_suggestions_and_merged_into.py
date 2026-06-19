"""add suggestions table + accounts.merged_into_id

Revision ID: 9a8946a074f7
Revises: 55f798901deb
Create Date: 2026-06-19

suggestions — general "hint" substrate (lightbulb-icon pattern). First
producer is account-duplicate detection; entity_id_a/b are typed to
accounts.id for this pass (future producers comparing other entity types
will need their own columns or table — not solved here).

accounts.merged_into_id — soft-merge pointer. We never hard-delete a
merged account (audit trail, and a safety net for any FK we missed).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9a8946a074f7'
down_revision: Union[str, None] = '55f798901deb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suggestions',
        sa.Column('id',              sa.Integer(), nullable=False),
        sa.Column('owner_id',        sa.Integer(), nullable=False),
        sa.Column('suggestion_type', sa.Text(),    nullable=False, server_default='account_duplicate'),
        sa.Column('entity_id_a',     sa.Integer(), nullable=False),
        sa.Column('entity_id_b',     sa.Integer(), nullable=False),
        sa.Column('score',           sa.Numeric(5, 2), nullable=False),
        sa.Column('reasoning',       sa.Text(), nullable=True),
        sa.Column('evidence',        sa.JSON(), nullable=True),
        sa.Column('status',          sa.Text(), nullable=False, server_default='new'),
        sa.Column('created_at',      sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('resolved_at',     sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'],    ['users.id']),
        sa.ForeignKeyConstraint(['entity_id_a'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entity_id_b'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_id_a', 'entity_id_b', name='uq_suggestions_pair'),
    )
    op.create_index('idx_suggestions_owner_status', 'suggestions', ['owner_id', 'status'])

    op.add_column('accounts', sa.Column('merged_into_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_accounts_merged_into_id', 'accounts', 'accounts',
        ['merged_into_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_accounts_merged_into_id', 'accounts', type_='foreignkey')
    op.drop_column('accounts', 'merged_into_id')
    op.drop_index('idx_suggestions_owner_status', table_name='suggestions')
    op.drop_table('suggestions')
