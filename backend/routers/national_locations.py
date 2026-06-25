"""National locations — Overture Maps Places reference data for Michigan.

POST /api/national-locations/link-to-my-properties
GET  /api/national-locations/in-bbox           — bbox viewport query for the map layer
POST /api/national-locations/{id}/lookup-owner — match address against parcels_regrid
POST /api/national-locations/{id}/create-account-from-parcel
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from collections import defaultdict

from database import get_db
from models.user import User
from models.account import Account
from models.property import Property
from models.national_location import NationalLocation
from models.parcel_regrid import ParcelRegrid
from models.property_national_location_link import PropertyNationalLocationLink
from auth_utils import get_current_user
from services.naming import normalize_address, normalize_name

router = APIRouter()


# ── Shared viewport query — called on every map moveend ──────────────────────

@router.get("/in-bbox")
def in_bbox(
    south: float,
    west:  float,
    north: float,
    east:  float,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns national_locations within a lat/lng bounding box for the
    map layer overlay. Auth required (consistent with rest of app) even
    though this table has no owner_id — the data itself isn't private."""
    rows = (
        db.query(
            NationalLocation.id,
            NationalLocation.brand_primary,
            NationalLocation.name_primary,
            NationalLocation.category_top,
            NationalLocation.address,
            NationalLocation.city,
            NationalLocation.lat,
            NationalLocation.lng,
        )
        .filter(
            NationalLocation.lat >= south,
            NationalLocation.lat <= north,
            NationalLocation.lng >= west,
            NationalLocation.lng <= east,
        )
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id":            r.id,
                "brand_primary": r.brand_primary,
                "name_primary":  r.name_primary,
                "category_top":  r.category_top,
                "address":       r.address,
                "city":          r.city,
                "lat":           float(r.lat) if r.lat is not None else None,
                "lng":           float(r.lng) if r.lng is not None else None,
            }
            for r in rows
        ]
    }


# ── Property linking ─────────────────────────────────────────────────────────

@router.post("/link-to-my-properties")  # admin/backfill utility — no UI button
def link_to_my_properties(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exact normalized-address match between national_locations and the
    broker's properties. Writes property_national_location_links rows."""
    properties = (db.query(Property)
                    .filter(Property.owner_id == current_user.id,
                            Property.address.isnot(None))
                    .all())
    if not properties:
        return {"properties_checked": 0, "locations_checked": 0,
                "links_created": 0, "links_already_existed": 0}

    by_city_state = defaultdict(list)
    for p in properties:
        city  = (p.city  or "").strip().lower()
        state = (p.state or "").strip().upper()
        if city and state:
            by_city_state[(city, state)].append(p)

    existing = {
        (r.property_id, r.national_location_id)
        for r in (db.query(PropertyNationalLocationLink)
                    .join(Property, Property.id == PropertyNationalLocationLink.property_id)
                    .filter(Property.owner_id == current_user.id)
                    .all())
    }

    locations_checked = links_created = links_already_existed = 0

    for (city, state), props in by_city_state.items():
        prop_by_norm_addr = {normalize_address(p.address): p for p in props if p.address}
        nl_rows = (db.query(NationalLocation)
                     .filter(NationalLocation.city.ilike(city),
                             NationalLocation.state.ilike(state))
                     .all())
        locations_checked += len(nl_rows)
        for nl in nl_rows:
            if not nl.address:
                continue
            matched_prop = prop_by_norm_addr.get(normalize_address(nl.address))
            if not matched_prop:
                continue
            pair = (matched_prop.id, nl.id)
            if pair in existing:
                links_already_existed += 1
                continue
            db.add(PropertyNationalLocationLink(
                property_id=matched_prop.id, national_location_id=nl.id, match_confidence=1.0,
            ))
            existing.add(pair)
            links_created += 1

    if links_created:
        db.commit()

    return {"properties_checked": len(properties), "locations_checked": locations_checked,
            "links_created": links_created, "links_already_existed": links_already_existed}


# ── Parcel owner lookup ──────────────────────────────────────────────────────

@router.post("/{location_id}/lookup-owner")
def lookup_owner(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cross-reference a national_location against the parcels_regrid table
    by normalized address. Three possible outcomes:

      found=False:  no parcel in parcels_regrid matches this address
                    (county not yet ingested, or address too dissimilar)
      found=True, account_id set:  the parcel has been reconciled to one
                    of THIS broker's accounts — show "already in your book"
      found=True, account_id=None: parcel found, owner_raw available but
                    not yet linked — offer "Add as account"
    """
    nl = db.query(NationalLocation).filter(NationalLocation.id == location_id).first()
    if not nl or not nl.address:
        raise HTTPException(404, "Location not found or has no address")

    norm_nl_addr = normalize_address(nl.address)
    nl_city  = (nl.city  or "").strip().lower()
    nl_state = (nl.state or "MI").strip().upper()

    # Load parcel candidates scoped to the same city+state to keep the
    # Python-side normalization loop bounded.
    candidates = (
        db.query(ParcelRegrid)
        .filter(
            ParcelRegrid.state.ilike(nl_state),
            ParcelRegrid.city.ilike(nl_city) if nl_city else True,
        )
        .all()
    )

    matched_parcel = None
    for parcel in candidates:
        if not parcel.address:
            continue
        if normalize_address(parcel.address) == norm_nl_addr:
            matched_parcel = parcel
            break

    if not matched_parcel:
        return {
            "found": False,
            "message": "No public record found for this address. "
                       "Parcel data for this county may not be ingested yet.",
        }

    # If the parcel has a matched_account_id, verify it belongs to this broker.
    if matched_parcel.matched_account_id:
        acct = db.query(Account).filter(
            Account.id == matched_parcel.matched_account_id,
            Account.owner_id == current_user.id,
        ).first()
        if acct:
            return {
                "found": True,
                "account_id":   acct.id,
                "account_name": acct.name,
                "message":      "Owner already in your book",
            }
        # Parcel matched to a different broker's account — treat as unmatched
        # for this broker (don't expose another owner's account data).

    return {
        "found":           True,
        "account_id":      None,
        "parcel_regrid_id": matched_parcel.id,
        "owner_raw":        matched_parcel.owner_raw,
        "parcel_address":   matched_parcel.address,
        "parcel_id":        matched_parcel.parcel_id,
        "message":          "Owner of record found — not yet in your book",
    }


class CreateAccountBody(BaseModel):
    parcel_regrid_id: int


@router.post("/{location_id}/create-account-from-parcel")
def create_account_from_parcel(
    location_id: int,
    body: CreateAccountBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates an Account from a parcels_regrid row and links it to the
    national_location. Sets parcels_regrid.matched_account_id so future
    lookup_owner calls return 'already in your book' for this broker."""
    nl = db.query(NationalLocation).filter(NationalLocation.id == location_id).first()
    if not nl:
        raise HTTPException(404, "Location not found")

    parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == body.parcel_regrid_id).first()
    if not parcel:
        raise HTTPException(404, "Parcel not found")

    new_account = Account(
        owner_id=current_user.id,
        name=parcel.owner_raw or f"Unknown Owner — {parcel.parcel_id}",
        normalized_name=normalize_name(parcel.owner_raw or ""),
        address=parcel.address,
        city=parcel.city,
        state=parcel.state,
        zip=parcel.zip,
        roles=["owner"],
    )
    db.add(new_account)
    db.flush()

    parcel.matched_account_id = new_account.id
    parcel.reconciliation_status = "auto_linked"

    db.commit()
    return {"account_id": new_account.id, "account_name": new_account.name}
