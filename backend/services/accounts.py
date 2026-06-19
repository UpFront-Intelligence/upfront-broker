"""Helpers for working with Account records."""
from models.account import Account


def owned_accounts_query(db, owner_id):
    """Base query for an owner's accounts — excludes merged-away duplicates
    so listings, search, typeaheads, and fuzzy-match candidate pools never
    surface or match against them. Reuse this instead of querying Account
    directly wherever the result set is a "which accounts does this owner
    have" search, as opposed to a lookup of one specific account_id."""
    return db.query(Account).filter(
        Account.owner_id == owner_id, Account.merged_into_id.is_(None))


def ensure_role(account, role):
    """Add `role` to account.roles if not already present.

    Reassigns the list (rather than mutating in place) so SQLAlchemy
    tracks the change to the ARRAY column.
    """
    if role not in account.roles:
        account.roles = account.roles + [role]
