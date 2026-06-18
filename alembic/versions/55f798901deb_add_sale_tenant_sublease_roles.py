"""add sale_broker, tenant_rep, sublease_broker account roles

Revision ID: 55f798901deb
Revises: 3e42ae66cedd
Create Date: 2026-06-18

Extends the properties-with-parties fan-out import to recognize "Sale
Company *", "Tenant Company *", and "Sublease Broker *" column groups
(none appear in the Michigan file yet, but the detector and the role
vocabulary are ready for when they do).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '55f798901deb'
down_revision: Union[str, None] = '3e42ae66cedd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLES = [
    ('sale_broker',     'Sale Broker'),
    ('tenant_rep',      'Tenant Rep'),
    ('sublease_broker', 'Sublease Broker'),
]


def upgrade() -> None:
    for slug, display_name in ROLES:
        op.execute(sa.text(
            "INSERT INTO account_roles (slug, display_name, category) "
            "VALUES (:slug, :display_name, 'brokerage_mgmt') "
            "ON CONFLICT (slug) DO NOTHING"
        ).bindparams(slug=slug, display_name=display_name))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM account_roles WHERE slug IN ('sale_broker', 'tenant_rep', 'sublease_broker')"
    ))
