"""add account lat/lng

Revision ID: c7e65628672c
Revises: 3f514cfabf0e
Create Date: 2026-06-21

Office-location geocoding for Accounts (US Census geocoder) — Contact
already got lat/lng last migration; Account did not have them at all.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7e65628672c'
down_revision: Union[str, None] = '3f514cfabf0e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('lat', sa.Float(), nullable=True))
    op.add_column('accounts', sa.Column('lng', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('accounts', 'lng')
    op.drop_column('accounts', 'lat')
