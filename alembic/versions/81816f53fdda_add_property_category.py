"""add property_category

Revision ID: 81816f53fdda
Revises: c7e65628672c
Create Date: 2026-06-22

10-category taxonomy derived from property_type via
backend/services/property_category.py's pattern matching — not a
client-settable field, see CLAUDE.md's PROPERTY_CATEGORY section.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '81816f53fdda'
down_revision: Union[str, None] = 'c7e65628672c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('properties', sa.Column('property_category', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'property_category')
