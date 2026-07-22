"""add property_parties reverse-lookup indexes (account_id, contact_id)

Revision ID: f112218c13fe
Revises: 97ff9ec4ed1c
Create Date: 2026-07-22

The only indexes on property_parties today all lead with property_id
(uix_pp_property_account_role, uix_pp_property_contact_role, idx_pp_property_id)
— built for "list this property's parties" (property.html's Parties card).
Contact/Account detail pages now run the reverse query ("list this
contact/account's properties", WHERE account_id = X or WHERE contact_id = X,
no property_id in the filter), which can't use a leftmost-prefix match on
any of those. Partial indexes here (mirroring the existing partial unique
indexes' WHERE-not-null style on this same table) since roughly half of
all rows have a null account_id and the other half a null contact_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f112218c13fe'
down_revision: Union[str, None] = '97ff9ec4ed1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'idx_pp_account_id', 'property_parties', ['account_id'],
        postgresql_where=sa.text('account_id IS NOT NULL'),
    )
    op.create_index(
        'idx_pp_contact_id', 'property_parties', ['contact_id'],
        postgresql_where=sa.text('contact_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('idx_pp_contact_id', table_name='property_parties')
    op.drop_index('idx_pp_account_id', table_name='property_parties')
