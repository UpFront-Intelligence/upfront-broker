"""add leasing_broker account role

Revision ID: df65bcec62ab
Revises: 38e7bbf3de8d
Create Date: 2026-06-18

Adds 'leasing_broker' to the account_roles vocabulary — the brokerage/
agent handling leasing for a property, distinct from 'property_manager'
(day-to-day building ops) and 'brokerage' (a firm acting as itself).
Used by the properties-with-parties fan-out import.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'df65bcec62ab'
down_revision: Union[str, None] = '38e7bbf3de8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO account_roles (slug, display_name, category) "
        "VALUES ('leasing_broker', 'Leasing Broker', 'brokerage_mgmt') "
        "ON CONFLICT (slug) DO NOTHING"
    ))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM account_roles WHERE slug = 'leasing_broker'"))
