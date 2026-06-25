"""Passive cross-linking between Properties and national_locations.

Called at every property write site (create, update address, attach_parcel,
importers) — same discipline as geocoding and property_category. See
CLAUDE.md's NATIONAL_LOCATIONS section for the four documented write sites.

link_property_to_national_locations() is flush-only: it adds
PropertyNationalLocationLink rows to the current db session but does NOT
commit. The calling write-site's own db.commit() picks up the rows.
Non-fatal: if national_locations is empty (pre-ingest) or the lookup
fails for any reason, the property save succeeds regardless.
"""
from models.national_location import NationalLocation
from models.property_national_location_link import PropertyNationalLocationLink
from services.naming import normalize_address


def link_property_to_national_locations(db, prop) -> int:
    """Find national_locations at the same address as `prop` and add
    PropertyNationalLocationLink rows to the session (flush-only, no commit).

    Returns the number of new links added (0 if nothing matched or linked).
    Idempotent: skips pairs that already have a link row.
    """
    if not prop.id or not prop.address or not prop.city or not prop.state:
        return 0

    norm = normalize_address(prop.address)
    if not norm:
        return 0

    city  = prop.city.strip().lower()
    state = prop.state.strip().upper()

    # Fast index lookup on address_normalized (populated at ingest time).
    # If national_locations is empty (pre-ingest) this returns [] immediately.
    matches = (
        db.query(NationalLocation)
        .filter(
            NationalLocation.address_normalized == norm,
            NationalLocation.city.ilike(city),
            NationalLocation.state.ilike(state),
        )
        .all()
    )
    if not matches:
        return 0

    # Pre-fetch existing links for this property to skip duplicates.
    already_linked = {
        nl_id for (nl_id,) in
        db.query(PropertyNationalLocationLink.national_location_id)
          .filter(PropertyNationalLocationLink.property_id == prop.id)
          .all()
    }

    added = 0
    for nl in matches:
        if nl.id not in already_linked:
            db.add(PropertyNationalLocationLink(
                property_id=prop.id,
                national_location_id=nl.id,
                match_confidence=1.0,
            ))
            already_linked.add(nl.id)
            added += 1

    return added
