from models.property_party import PropertyParty


def get_properties_for_party(db, owner_id, account_id=None, contact_id=None):
    """Reverse property_parties lookup: every property this account or
    contact is a party on (exactly one of account_id/contact_id given),
    scoped to owner_id via a join on Property (property_parties itself
    has no owner_id — see PROPERTY_PARTIES in CLAUDE.md).

    A property appears once even if the same party holds more than one
    role on it (role is part of property_parties' uniqueness key, not a
    single-value column — e.g. leasing_broker AND tenant_rep on the same
    property is a legal pair of rows) — each row's `roles` list carries
    every distinct role slug, resolved to account_roles' display_name/
    category the same way routers/property_parties.py's _resolve_parties()
    already does for the property-side card, reused here rather than
    duplicated.
    """
    from models.property import Property
    from models.account_role import AccountRole

    q = (db.query(PropertyParty, Property)
           .join(Property, PropertyParty.property_id == Property.id)
           .filter(Property.owner_id == owner_id))
    q = (q.filter(PropertyParty.account_id == account_id) if account_id is not None
         else q.filter(PropertyParty.contact_id == contact_id))

    roles_by_slug = {r.slug: r for r in db.query(AccountRole).all()}
    by_property = {}
    for pp, p in q.all():
        entry = by_property.setdefault(p.id, {
            "property_id": p.id, "name": p.name, "address": p.address,
            "city": p.city, "state": p.state, "property_type": p.property_type,
            "status": p.status, "lat": p.lat, "lng": p.lng, "roles": [],
        })
        if pp.role not in {r["slug"] for r in entry["roles"]}:
            role_row = roles_by_slug.get(pp.role)
            entry["roles"].append({
                "slug": pp.role,
                "display_name": role_row.display_name if role_row else pp.role,
                "category": role_row.category if role_row else None,
            })
    return list(by_property.values())


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
