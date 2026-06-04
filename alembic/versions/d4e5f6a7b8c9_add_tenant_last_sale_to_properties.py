"""add tenant, last_sale_price, last_sale_date to properties

Revision ID: d4e5f6a7b8c9
Revises: c7d2e4f8a1b5
Create Date: 2026-06-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c7d2e4f8a1b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    existing = {c['name'] for c in inspector.get_columns('properties')}
    if 'tenant' not in existing:
        op.add_column('properties', sa.Column('tenant', sa.String(), nullable=True))
    if 'last_sale_price' not in existing:
        op.add_column('properties', sa.Column('last_sale_price', sa.Float(), nullable=True))
    if 'last_sale_date' not in existing:
        op.add_column('properties', sa.Column('last_sale_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('properties', 'last_sale_date')
    op.drop_column('properties', 'last_sale_price')
    op.drop_column('properties', 'tenant')
