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


def geocode_account_if_address_changed(db, account, owner_id):
    """Geocodes the account's address via the US Census geocoder and
    propagates lat/lng onto inherited Contacts (no distinct address of
    their own, still missing lat/lng). Caller decides *whether* to call
    this (only when address/city/state actually changed) — this function
    unconditionally (re-)geocodes whatever's on the account right now."""
    from services.geocoding import geocode_address
    if not account.address:
        return
    coords = geocode_address(account.address, account.city, account.state, account.zip)
    if coords is None:
        return
    account.lat, account.lng = coords
    _propagate_account_geocode_to_contacts(db, account, owner_id)


def _propagate_account_geocode_to_contacts(db, account, owner_id):
    from models.contact import Contact
    from models.contact_account import ContactAccount
    contacts = (db.query(Contact)
                  .join(ContactAccount, ContactAccount.contact_id == Contact.id)
                  .filter(ContactAccount.account_id == account.id, Contact.owner_id == owner_id)
                  .all())
    for c in contacts:
        if c.lat is not None:
            continue
        has_distinct_address = bool(c.address or c.city or c.state) and not (
            c.address == account.address and c.city == account.city and c.state == account.state)
        if has_distinct_address:
            continue
        c.lat, c.lng = account.lat, account.lng


def geocode_contact_if_address_changed(db, contact, owner_id):
    """Geocodes a Contact directly when it has a genuinely distinct address
    from its linked Account (primary link, or first if none is primary) —
    i.e. not inherited. A Contact with no distinct address gets its
    coordinates via account-side propagation instead, see
    geocode_account_if_address_changed above."""
    from services.geocoding import geocode_address
    from models.account import Account
    from models.contact_account import ContactAccount

    if not contact.address:
        return

    link = (db.query(ContactAccount)
              .filter(ContactAccount.contact_id == contact.id)
              .order_by(ContactAccount.is_primary.desc())
              .first())
    if link:
        acct = db.query(Account).filter(
            Account.id == link.account_id, Account.owner_id == owner_id).first()
        if acct and (contact.address, contact.city, contact.state) == (acct.address, acct.city, acct.state):
            return  # matches the account — inherited, not distinct

    coords = geocode_address(contact.address, contact.city, contact.state, contact.zip)
    if coords is None:
        return
    contact.lat, contact.lng = coords


def ensure_role(account, role):
    """Add `role` to account.roles if not already present.

    Reassigns the list (rather than mutating in place) so SQLAlchemy
    tracks the change to the ARRAY column.
    """
    if role not in account.roles:
        account.roles = account.roles + [role]
