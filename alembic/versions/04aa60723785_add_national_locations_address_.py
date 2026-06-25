"""add_national_locations_address_normalized

Revision ID: 04aa60723785
Revises: 1323d6d9faea
Create Date: 2026-06-25

Adds address_normalized to national_locations so the per-property
passive cross-linking (services/national_locations.py) can do a fast
indexed lookup instead of loading every location in the city and
normalizing in Python.

The table is empty until scripts/ingest_overture_michigan.py is run,
so no data backfill is needed here.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '04aa60723785'
down_revision: Union[str, None] = '1323d6d9faea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('national_locations', sa.Column('address_normalized', sa.Text(), nullable=True))
    op.create_index('ix_national_locations_address_normalized', 'national_locations', ['address_normalized'])


def downgrade() -> None:
    op.drop_index('ix_national_locations_address_normalized', table_name='national_locations')
    op.drop_column('national_locations', 'address_normalized')
