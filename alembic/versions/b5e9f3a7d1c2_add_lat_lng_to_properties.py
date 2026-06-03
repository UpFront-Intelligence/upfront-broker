"""add lat lng to properties

Revision ID: b5e9f3a7d1c2
Revises: a3f8c2d1e9b4
Create Date: 2026-06-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = 'b5e9f3a7d1c2'
down_revision: Union[str, None] = 'a3f8c2d1e9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    existing = {c['name'] for c in inspector.get_columns('properties')}
    if 'lat' not in existing:
        op.add_column('properties', sa.Column('lat', sa.Float(), nullable=True))
    if 'lng' not in existing:
        op.add_column('properties', sa.Column('lng', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'lng')
    op.drop_column('properties', 'lat')
