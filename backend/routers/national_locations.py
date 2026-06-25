"""National locations — Overture Maps Places reference data for Michigan.

POST /api/national-locations/link-to-my-properties

Finds national_locations rows that correspond to properties the calling
broker owns by exact-normalized-address match, then writes
property_national_location_links rows so the Search/Map view can show
'In your book' badges.

Owner-scoping: the national_locations table itself has no owner_id
(shared reference data). Scoping happens through the junction —
a link row is only created when the linked property belongs to the
calling broker (properties.owner_id == current_user.id).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from collections import defaultdict

from database import get_db
from models.user import User
from models.property import Property
from models.national_location import NationalLocation
from models.property_national_location_link import PropertyNationalLocationLink
from auth_utils import get_current_user
from services.naming import normalize_address

router = APIRouter()


@router.post("/link-to-my-properties")
def link_to_my_properties(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fuzzy-matches national_locations rows against the broker's properties
    by exact normalized address + city + state, then upserts links.

    Strategy: for each unique (city, state) combination in the broker's
    properties, load the national_locations rows in that city and do
    Python-side address normalization equality checks. Cheaper than a
    cross-join on the full table, and address normalization via normalize_address()
    isn't reproducible in Postgres without a custom function.

    Match confidence is 1.0 for exact normalized address matches. Future
    versions could add PostGIS proximity matching for imprecise addresses.

    Returns: {properties_checked, locations_checked, links_created, links_already_existed}
    """
    properties = (db.query(Property)
                    .filter(Property.owner_id == current_user.id,
                            Property.address.isnot(None))
                    .all())

    if not properties:
        return {"properties_checked": 0, "locations_checked": 0,
                "links_created": 0, "links_already_existed": 0}

    # Group properties by (city, state) — each group queries a small slice
    # of national_locations.
    by_city_state = defaultdict(list)
    for p in properties:
        city  = (p.city  or "").strip().lower()
        state = (p.state or "").strip().upper()
        if city and state:
            by_city_state[(city, state)].append(p)

    # Pre-fetch existing links for this broker to avoid duplicate inserts
    existing = {
        (r.property_id, r.national_location_id)
        for r in (db.query(PropertyNationalLocationLink)
                    .join(Property, Property.id == PropertyNationalLocationLink.property_id)
                    .filter(Property.owner_id == current_user.id)
                    .all())
    }

    locations_checked = links_created = links_already_existed = 0

    for (city, state), props in by_city_state.items():
        # Build a normalized-address → property dict for this city
        prop_by_norm_addr = {}
        for p in props:
            norm = normalize_address(p.address)
            if norm:
                prop_by_norm_addr[norm] = p

        # Load national_locations in this city+state
        nl_rows = (db.query(NationalLocation)
                     .filter(NationalLocation.city.ilike(city),
                             NationalLocation.state.ilike(state))
                     .all())
        locations_checked += len(nl_rows)

        for nl in nl_rows:
            if not nl.address:
                continue
            norm = normalize_address(nl.address)
            matched_prop = prop_by_norm_addr.get(norm)
            if matched_prop is None:
                continue

            pair = (matched_prop.id, nl.id)
            if pair in existing:
                links_already_existed += 1
                continue

            db.add(PropertyNationalLocationLink(
                property_id=matched_prop.id,
                national_location_id=nl.id,
                match_confidence=1.0,
            ))
            existing.add(pair)
            links_created += 1

    if links_created:
        db.commit()

    return {
        "properties_checked":    len(properties),
        "locations_checked":     locations_checked,
        "links_created":         links_created,
        "links_already_existed": links_already_existed,
    }
