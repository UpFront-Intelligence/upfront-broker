"""accounts: multi-role parties + canonical role vocabulary

Revision ID: d8e9f0a1b2c3
Revises: c3d4e5f6a7b8
Create Date: 2026-06-10

Adds:
  accounts.roles            — ARRAY(String), the set of role slugs an account holds
  accounts.normalized_name  — for fuzzy matching (reuses tenants' normalizer)
  account_roles             — global lookup table for the canonical role vocabulary

Backfills roles from the legacy `account_type` column if it exists (it does not
in this codebase as of this migration, but the check keeps this safe to run
against any database where it was added out-of-band).
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Must match backend/services/naming.py normalize_name()
_STRIP_WORDS = {
    'llc', 'corp', 'corporation', 'co', 'inc', 'incorporated', 'ltd', 'limited',
    'coffee', 'restaurant', 'cafe', 'company', 'the', 'group', 'holdings',
    'enterprises', 'bar', 'grill', 'kitchen', 'bistro', 'eatery', 'diner',
    'and', 'of', 'at', 'by',
    'trust', 'lp', 'llp',
}


def _normalize_name(name: str) -> str:
    if not name:
        return ''
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", ' ', n)
    words = [w for w in n.split() if w not in _STRIP_WORDS]
    return ' '.join(words) if words else n.strip()


# Known account_type -> role slug mappings; anything else falls back to
# lower-cased, space/hyphen-to-underscore so nothing is lost.
_ACCOUNT_TYPE_ROLE_MAP = {
    'owner': 'owner',
    'tenant': 'tenant',
    'buyer': 'buyer',
    'seller': 'seller',
    'investor': 'investor',
    'developer': 'developer',
    'brokerage': 'brokerage',
    'lender': 'lender',
    'attorney': 'attorney',
    'vendor': 'vendor',
    'individual': 'individual',
    '1031 exchange qi': 'qi_1031',
    'qi': 'qi_1031',
}


def _role_from_account_type(raw: str) -> str:
    key = raw.strip().lower()
    if key in _ACCOUNT_TYPE_ROLE_MAP:
        return _ACCOUNT_TYPE_ROLE_MAP[key]
    return re.sub(r'[\s-]+', '_', key)


# ── Canonical role vocabulary ──────────────────────────────────────────────────
ACCOUNT_ROLES_SEED = [
    # principals
    {'slug': 'owner',      'display_name': 'Owner',      'category': 'principals'},
    {'slug': 'tenant',     'display_name': 'Tenant',     'category': 'principals'},
    {'slug': 'buyer',      'display_name': 'Buyer',      'category': 'principals'},
    {'slug': 'seller',     'display_name': 'Seller',     'category': 'principals'},
    {'slug': 'investor',   'display_name': 'Investor',   'category': 'principals'},
    {'slug': 'developer',  'display_name': 'Developer',  'category': 'principals'},
    {'slug': 'guarantor',  'display_name': 'Guarantor',  'category': 'principals'},
    {'slug': 'individual', 'display_name': 'Individual', 'category': 'principals'},

    # brokerage_mgmt
    {'slug': 'brokerage',        'display_name': 'Brokerage',        'category': 'brokerage_mgmt'},
    {'slug': 'property_manager', 'display_name': 'Property Manager', 'category': 'brokerage_mgmt'},
    {'slug': 'asset_manager',    'display_name': 'Asset Manager',    'category': 'brokerage_mgmt'},

    # capital_finance
    {'slug': 'lender',          'display_name': 'Lender',           'category': 'capital_finance'},
    {'slug': 'mortgage_broker',  'display_name': 'Mortgage Broker',  'category': 'capital_finance'},
    {'slug': 'appraiser',       'display_name': 'Appraiser',        'category': 'capital_finance'},
    {'slug': 'loan_servicer',   'display_name': 'Loan Servicer',    'category': 'capital_finance'},
    {'slug': 'qi_1031',         'display_name': '1031 Exchange QI', 'category': 'capital_finance'},

    # legal_professional
    {'slug': 'attorney',        'display_name': 'Attorney',        'category': 'legal_professional'},
    {'slug': 'title_company',   'display_name': 'Title Company',   'category': 'legal_professional'},
    {'slug': 'escrow_agent',    'display_name': 'Escrow Agent',    'category': 'legal_professional'},
    {'slug': 'accounting_firm', 'display_name': 'Accounting Firm', 'category': 'legal_professional'},
    {'slug': 'tax_consultant',  'display_name': 'Tax Consultant',  'category': 'legal_professional'},
    {'slug': 'insurance',       'display_name': 'Insurance',       'category': 'legal_professional'},

    # diligence_project
    {'slug': 'environmental',      'display_name': 'Environmental',      'category': 'diligence_project'},
    {'slug': 'engineering',        'display_name': 'Engineering',        'category': 'diligence_project'},
    {'slug': 'surveyor',           'display_name': 'Surveyor',           'category': 'diligence_project'},
    {'slug': 'architect',          'display_name': 'Architect',          'category': 'diligence_project'},
    {'slug': 'general_contractor', 'display_name': 'General Contractor', 'category': 'diligence_project'},
    {'slug': 'zoning_consultant',  'display_name': 'Zoning Consultant',  'category': 'diligence_project'},
    {'slug': 'inspector',          'display_name': 'Inspector',          'category': 'diligence_project'},

    # government_public
    {'slug': 'municipality',       'display_name': 'Municipality',                  'category': 'government_public'},
    {'slug': 'econ_dev_authority', 'display_name': 'Economic Development Authority', 'category': 'government_public'},
    {'slug': 'utility',            'display_name': 'Utility',                       'category': 'government_public'},

    # vendor
    {'slug': 'vendor', 'display_name': 'Vendor', 'category': 'vendor'},
]


def upgrade() -> None:
    bind = op.get_bind()

    # ── New columns on accounts ────────────────────────────────────────────────
    op.add_column('accounts', sa.Column(
        'roles', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'))
    op.add_column('accounts', sa.Column('normalized_name', sa.String(), nullable=True))

    # ── account_roles — global lookup table, no owner_id ───────────────────────
    op.create_table(
        'account_roles',
        sa.Column('slug',         sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('category',     sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('slug'),
    )

    # ── Indexes ─────────────────────────────────────────────────────────────────
    op.create_index('idx_accounts_roles', 'accounts', ['roles'], postgresql_using='gin')
    op.create_index('idx_accounts_normalized_name', 'accounts', ['normalized_name'])

    accounts = sa.table(
        'accounts',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('normalized_name', sa.String),
        sa.column('roles', postgresql.ARRAY(sa.String())),
    )

    # ── Backfill normalized_name (reuses the tenants normalizer) ───────────────
    for row in bind.execute(sa.select(accounts.c.id, accounts.c.name)).fetchall():
        bind.execute(
            accounts.update()
            .where(accounts.c.id == row.id)
            .values(normalized_name=_normalize_name(row.name))
        )

    # ── Backfill roles from legacy account_type, if present ─────────────────────
    inspector = sa.inspect(bind)
    existing_columns = {c['name'] for c in inspector.get_columns('accounts')}
    if 'account_type' in existing_columns:
        rows = bind.execute(sa.text(
            "SELECT id, account_type FROM accounts "
            "WHERE account_type IS NOT NULL AND account_type <> ''"
        )).fetchall()
        for row in rows:
            slug = _role_from_account_type(row.account_type)
            bind.execute(
                accounts.update()
                .where(accounts.c.id == row.id)
                .values(roles=[slug])
            )

    # ── Seed canonical role vocabulary ──────────────────────────────────────────
    account_roles = sa.table(
        'account_roles',
        sa.column('slug', sa.String),
        sa.column('display_name', sa.String),
        sa.column('category', sa.String),
    )
    op.bulk_insert(account_roles, ACCOUNT_ROLES_SEED)


def downgrade() -> None:
    op.drop_index('idx_accounts_normalized_name', table_name='accounts')
    op.drop_index('idx_accounts_roles', table_name='accounts')
    op.drop_table('account_roles')
    op.drop_column('accounts', 'normalized_name')
    op.drop_column('accounts', 'roles')
