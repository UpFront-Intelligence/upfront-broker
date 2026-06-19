"""add contact address/city/state/zip/lat/lng

Revision ID: 3f514cfabf0e
Revises: 5b53ce28d888
Create Date: 2026-06-20

CLAUDE.md's CONTACT schema block has described address/city/state/zip as
existing columns for a while — they weren't (see corrected doc note).
This migration makes that part of the claim true. lat/lng added ahead of
need for upcoming office-location mapping; nullable, no importer wiring yet.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3f514cfabf0e'
down_revision: Union[str, None] = '5b53ce28d888'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('address', sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('city',    sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('state',   sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('zip',     sa.String(), nullable=True))
    op.add_column('contacts', sa.Column('lat',     sa.Float(),  nullable=True))
    op.add_column('contacts', sa.Column('lng',     sa.Float(),  nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'lng')
    op.drop_column('contacts', 'lat')
    op.drop_column('contacts', 'zip')
    op.drop_column('contacts', 'state')
    op.drop_column('contacts', 'city')
    op.drop_column('contacts', 'address')
