"""add tenant_id to contacts

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: str = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('contacts',
        sa.Column('tenant_id', sa.Integer(),
                  sa.ForeignKey('tenants.id', ondelete='SET NULL'),
                  nullable=True))
    op.create_index('idx_contacts_tenant_id', 'contacts', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('idx_contacts_tenant_id', table_name='contacts')
    op.drop_column('contacts', 'tenant_id')
