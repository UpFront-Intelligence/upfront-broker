"""Helpers for working with Account records."""


def ensure_role(account, role):
    """Add `role` to account.roles if not already present.

    Reassigns the list (rather than mutating in place) so SQLAlchemy
    tracks the change to the ARRAY column.
    """
    if role not in account.roles:
        account.roles = account.roles + [role]
