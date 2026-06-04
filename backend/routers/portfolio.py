"""
Portfolio Intelligence Search — cross-silo queries across properties,
accounts, contacts, and public parcel data.

GET /api/portfolio/search?query_type=...&...params...
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.property import Property
from models.account import Account
from models.contact import Contact
from models.contact_account import ContactAccount
from models.deal import Deal
from auth_utils import get_current_user

router = APIRouter()


@router.get("/search")
def portfolio_search(
    query_type:     str = Query(...),
    # Q1 — accounts by property type
    property_type:  Optional[str] = Query(None),
    # Q2/Q5 — filter by owner location
    owner_state:    Optional[str] = Query(None),
    owner_city:     Optional[str] = Query(None),
    owner_zip:      Optional[str] = Query(None),
    # Q3 — portfolio size
    min_properties: Optional[int] = Query(None, ge=1),
    # Q4 — tenant search
    tenant:         Optional[str] = Query(None),
    # Q6 — owner name search
    owner_name:     Optional[str] = Query(None),
    db:             Session = Depends(get_db),
    current_user:   User    = Depends(get_current_user),
):
    uid = current_user.id

    # ── Q1: Accounts that own a given property type ───────────────────────────
    if query_type == "accounts_by_property_type":
        if not property_type:
            raise HTTPException(400, "property_type is required")
        rows = (
            db.query(
                Account.id, Account.name, Account.entity_type,
                Account.city, Account.state, Account.phone, Account.email,
                func.count(Property.id).label("property_count"),
                func.coalesce(func.sum(Property.sf_rentable), 0).label("total_sf"),
                func.coalesce(func.sum(Property.assessed_value), 0).label("total_assessed"),
            )
            .join(Property, Property.account_id == Account.id)
            .filter(Account.owner_id == uid, Property.owner_id == uid)
            .filter(Property.property_type == property_type)
            .group_by(Account.id, Account.name, Account.entity_type,
                      Account.city, Account.state, Account.phone, Account.email)
            .order_by(func.count(Property.id).desc())
            .limit(200)
            .all()
        )
        return {"query_type": query_type, "results": [
            {"id": r.id, "name": r.name, "entity_type": r.entity_type,
             "city": r.city, "state": r.state, "phone": r.phone, "email": r.email,
             "property_count": r.property_count,
             "total_sf": float(r.total_sf or 0),
             "total_assessed": float(r.total_assessed or 0)}
            for r in rows
        ]}

    # ── Q2: Properties owned by entities in a location ────────────────────────
    if query_type == "properties_by_owner_location":
        if not owner_state and not owner_city and not owner_zip:
            raise HTTPException(400, "Provide owner_state, owner_city, or owner_zip")
        q = (
            db.query(Property, Account)
            .join(Account, Property.account_id == Account.id)
            .filter(Property.owner_id == uid, Account.owner_id == uid)
        )
        if owner_state: q = q.filter(Account.state.ilike(owner_state))
        if owner_city:  q = q.filter(Account.city.ilike(f"%{owner_city}%"))
        if owner_zip:   q = q.filter(Account.zip.ilike(f"{owner_zip}%"))
        rows = q.order_by(Account.name, Property.address).limit(200).all()
        return {"query_type": query_type, "results": [
            {"property_id": p.id, "address": p.address, "city": p.city, "state": p.state,
             "property_type": p.property_type, "sf_rentable": p.sf_rentable,
             "asking_price": p.asking_price, "status": p.status,
             "owner": a.name, "owner_type": a.entity_type,
             "owner_city": a.city, "owner_state": a.state}
            for p, a in rows
        ]}

    # ── Q3: Accounts ranked by portfolio size ─────────────────────────────────
    if query_type == "portfolio_size":
        threshold = min_properties or 1
        rows = (
            db.query(
                Account.id, Account.name, Account.entity_type,
                Account.city, Account.state,
                func.count(Property.id).label("property_count"),
                func.coalesce(func.sum(Property.sf_rentable), 0).label("total_sf"),
                func.coalesce(func.sum(Property.asking_price), 0).label("total_value"),
            )
            .join(Property, Property.account_id == Account.id)
            .filter(Account.owner_id == uid, Property.owner_id == uid)
            .group_by(Account.id, Account.name, Account.entity_type,
                      Account.city, Account.state)
            .having(func.count(Property.id) >= threshold)
            .order_by(func.count(Property.id).desc())
            .limit(200)
            .all()
        )
        return {"query_type": query_type, "results": [
            {"id": r.id, "name": r.name, "entity_type": r.entity_type,
             "city": r.city, "state": r.state,
             "property_count": r.property_count,
             "total_sf": float(r.total_sf or 0),
             "total_value": float(r.total_value or 0)}
            for r in rows
        ]}

    # ── Q4: Tenant location search ─────────────────────────────────────────────
    if query_type == "tenant_search":
        if not tenant:
            raise HTTPException(400, "tenant is required")
        props = (
            db.query(Property)
            .filter(Property.owner_id == uid)
            .filter(Property.tenant.ilike(f"%{tenant}%"))
            .order_by(Property.city, Property.address)
            .limit(200)
            .all()
        )
        return {"query_type": query_type, "results": [
            {"id": p.id, "address": p.address, "city": p.city, "state": p.state,
             "property_type": p.property_type, "tenant": p.tenant,
             "sf_rentable": p.sf_rentable, "status": p.status}
            for p in props
        ]}

    # ── Q5: Owner pattern — LLC clustering by mailing address ─────────────────
    if query_type == "owner_pattern":
        if not owner_city and not owner_zip and not owner_state:
            raise HTTPException(400, "Provide owner_city, owner_zip, or owner_state")
        q = (
            db.query(
                Account.id, Account.name, Account.entity_type,
                Account.address, Account.city, Account.state, Account.zip,
                func.count(Property.id).label("property_count"),
            )
            .join(Property, Property.account_id == Account.id)
            .filter(Account.owner_id == uid, Property.owner_id == uid)
        )
        if owner_city:  q = q.filter(Account.city.ilike(f"%{owner_city}%"))
        if owner_zip:   q = q.filter(Account.zip.ilike(f"{owner_zip}%"))
        if owner_state: q = q.filter(Account.state.ilike(owner_state))
        rows = (
            q.group_by(Account.id, Account.name, Account.entity_type,
                       Account.address, Account.city, Account.state, Account.zip)
            .order_by(func.count(Property.id).desc())
            .limit(200)
            .all()
        )
        return {"query_type": query_type, "results": [
            {"id": r.id, "name": r.name, "entity_type": r.entity_type,
             "mailing_address": r.address, "city": r.city,
             "state": r.state, "zip": r.zip,
             "property_count": r.property_count}
            for r in rows
        ]}

    # ── Q6: Owner name search — surfaces all properties by an entity ──────────
    if query_type == "owner_search":
        if not owner_name:
            raise HTTPException(400, "owner_name is required")
        rows = (
            db.query(Property, Account)
            .outerjoin(Account, Property.account_id == Account.id)
            .filter(Property.owner_id == uid)
            .filter(Account.name.ilike(f"%{owner_name}%"))
            .order_by(Property.address)
            .limit(200)
            .all()
        )
        return {"query_type": query_type, "results": [
            {"id": p.id, "address": p.address, "city": p.city, "state": p.state,
             "property_type": p.property_type, "status": p.status,
             "sf_rentable": p.sf_rentable, "asking_price": p.asking_price,
             "owner": a.name if a else None, "owner_type": a.entity_type if a else None}
            for p, a in rows
        ]}

    raise HTTPException(400, f"Unknown query_type: {query_type}")
