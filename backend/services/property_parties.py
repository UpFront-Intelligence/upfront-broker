from models.property_party import PropertyParty


def add_property_party(db, property_id, role, account_id=None, contact_id=None,
                        source="import", note=None):
    """Duplicate-safe insert into property_parties.

    Skips (returns None) if a row already exists for (property_id,
    account_id, role) or (property_id, contact_id, role) — backed by the
    partial unique indexes from migration 3e42ae66cedd, so this check is a
    friendly pre-empt, not the only thing preventing a duplicate.
    Returns the created PropertyParty on success (flushed, not committed —
    caller commits).
    """
    q = db.query(PropertyParty).filter(
        PropertyParty.property_id == property_id, PropertyParty.role == role)
    q = (q.filter(PropertyParty.account_id == account_id) if account_id is not None
         else q.filter(PropertyParty.contact_id == contact_id))
    if q.first():
        return None
    pp = PropertyParty(property_id=property_id, account_id=account_id,
                        contact_id=contact_id, role=role, source=source, note=note)
    db.add(pp)
    db.flush()
    return pp
