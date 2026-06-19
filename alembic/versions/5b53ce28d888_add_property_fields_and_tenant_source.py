"""add missing property fields + property_tenants.source

Revision ID: 5b53ce28d888
Revises: 9a8946a074f7
Create Date: 2026-06-20

Checked the model against the import template's candidate field list first
(market, submarket, land_sf, units, num_stories, construction_type,
parking_spaces, parking_ratio, year_built, year_renovated, lat, lng) —
sf_land/units/stories/parking_ratio/year_built/lat/lng already exist
under those names. Only the five genuinely-missing columns are added here.

property_tenants.source mirrors property_parties.source (manual/import/
parsed) — needed so the generalized property importer can mark the
default "Whole Building" space it creates per the brief.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '5b53ce28d888'
down_revision: Union[str, None] = '9a8946a074f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('market',            sa.String(),  nullable=True))
    op.add_column('properties', sa.Column('submarket',         sa.String(),  nullable=True))
    op.add_column('properties', sa.Column('construction_type', sa.String(),  nullable=True))
    op.add_column('properties', sa.Column('parking_spaces',    sa.Integer(), nullable=True))
    op.add_column('properties', sa.Column('year_renovated',    sa.Integer(), nullable=True))

    op.add_column('property_tenants', sa.Column(
        'source', sa.Text(), nullable=False, server_default='manual'))


def downgrade() -> None:
    op.drop_column('property_tenants', 'source')

    op.drop_column('properties', 'year_renovated')
    op.drop_column('properties', 'parking_spaces')
    op.drop_column('properties', 'construction_type')
    op.drop_column('properties', 'submarket')
    op.drop_column('properties', 'market')
