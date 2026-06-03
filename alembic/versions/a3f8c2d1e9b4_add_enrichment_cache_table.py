"""add enrichment_cache table

Revision ID: a3f8c2d1e9b4
Revises:
Create Date: 2026-06-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a3f8c2d1e9b4'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'enrichment_cache',
        sa.Column('id',               sa.Integer(),                         nullable=False),
        sa.Column('lookup_type',      sa.String(),                          nullable=False),
        sa.Column('lookup_key',       sa.String(),                          nullable=False),
        sa.Column('source',           sa.String(),                          nullable=False),
        sa.Column('raw_response',     sa.JSON(),                            nullable=True),
        sa.Column('phone_numbers',    postgresql.ARRAY(sa.String()),        nullable=True),
        sa.Column('emails',           postgresql.ARRAY(sa.String()),        nullable=True),
        sa.Column('owner_name',       sa.String(),                          nullable=True),
        sa.Column('confidence_score', sa.Float(),                           nullable=True),
        sa.Column('fetched_at',       sa.DateTime(timezone=True),
                  server_default=sa.text('now()'),                          nullable=False),
        sa.Column('expires_at',       sa.DateTime(timezone=True),           nullable=False),
        sa.Column('hit_count',        sa.Integer(),
                  server_default=sa.text('0'),                              nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # Primary lookup pattern: type + key (e.g. parcel_id + "12-34-567")
    op.create_index('ix_enrichment_cache_lookup', 'enrichment_cache',
                    ['lookup_type', 'lookup_key'])
    # Used when sweeping for expired rows
    op.create_index('ix_enrichment_cache_expires_at', 'enrichment_cache',
                    ['expires_at'])


def downgrade() -> None:
    op.drop_index('ix_enrichment_cache_expires_at', table_name='enrichment_cache')
    op.drop_index('ix_enrichment_cache_lookup',     table_name='enrichment_cache')
    op.drop_table('enrichment_cache')
