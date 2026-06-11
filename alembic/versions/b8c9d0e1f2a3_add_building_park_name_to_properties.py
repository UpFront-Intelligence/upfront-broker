"""add building_name, park_name to properties

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-11

Display/search-friendly text for the import overhaul. building_name is the
official building name (e.g. "One Towne Square"); park_name is the business
or industrial park the building sits in (e.g. "Galleria Officentre").
properties.name is unchanged and continues to serve as the display name.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    existing = {c['name'] for c in inspector.get_columns('properties')}
    if 'building_name' not in existing:
        op.add_column('properties', sa.Column('building_name', sa.Text(), nullable=True))
    if 'park_name' not in existing:
        op.add_column('properties', sa.Column('park_name', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'park_name')
    op.drop_column('properties', 'building_name')
