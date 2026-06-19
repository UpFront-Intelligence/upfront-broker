from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel, Field
from typing import Any, Optional

from database import get_db
from models.contact import Contact
from models.contact_account import ContactAccount
from models.account import Account
from models.property import Property
from models.property_party import PropertyParty
from models.property_tenant import PropertyTenant
from models.tenant import Tenant
from models.deal import Deal
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

VALID_RETURN_TYPES = {"contacts", "accounts", "properties", "tenants", "deals"}


# ── Request schema ────────────────────────────────────────────────

class QuerySpec(BaseModel):
    return_type: str = Field("contacts", alias="return")
    contact:         dict[str, Any] = Field(default_factory=dict)
    account:         dict[str, Any] = Field(default_factory=dict)
    property_filter: dict[str, Any] = Field(default_factory=dict, alias="property")
    tenant:          dict[str, Any] = Field(default_factory=dict)
    # Multi-select geography — applies to the property's own location for
    # Properties/Tenants/Deals, or the entity's own city/state for
    # Accounts/Contacts (neither has a county column, so county is ignored
    # for those two return types).
    geography:       dict[str, Any] = Field(default_factory=dict)
    ownership: str = "recorded"
    limit:     int = 200
    offset:    int = 0

    model_config = {"populate_by_name": True}


# ── Filter helpers ────────────────────────────────────────────────

def _contains(val: Any) -> str:
    return val["contains"] if isinstance(val, dict) and "contains" in val else str(val)


def _as_list(val: Any) -> list:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _apply_contact_filters(q, spec: QuerySpec):
    cf = spec.contact
    if "title" in cf:
        q = q.filter(Contact.title.ilike(f"%{_contains(cf['title'])}%"))
    if "name" in cf:
        full = (Contact.first_name + " " + Contact.last_name)
        q = q.filter(full.ilike(f"%{_contains(cf['name'])}%"))
    return q


def _apply_account_filters(q, spec: QuerySpec):
    af = spec.account
    if "name" in af:
        q = q.filter(Account.name.ilike(f"%{_contains(af['name'])}%"))
    if "roles" in af:
        for role in af["roles"]:
            q = q.filter(Account.roles.contains([role]))
    return q


def _apply_property_filters(q, spec: QuerySpec):
    pf = spec.property_filter
    if "property_type" in pf:
        q = q.filter(Property.property_type == pf["property_type"])
    if "county" in pf:
        q = q.filter(Property.county.ilike(f"%{_contains(pf['county'])}%"))
    if "city" in pf:
        q = q.filter(Property.city.ilike(f"%{_contains(pf['city'])}%"))
    if "sf_min" in pf:
        q = q.filter(Property.sf_rentable >= pf["sf_min"])
    if "sf_max" in pf:
        q = q.filter(Property.sf_rentable <= pf["sf_max"])
    if "price_min" in pf:
        q = q.filter(Property.asking_price >= pf["price_min"])
    if "price_max" in pf:
        q = q.filter(Property.asking_price <= pf["price_max"])
    return q


def _apply_tenant_filters(q, spec: QuerySpec):
    tf = spec.tenant
    if "name" in tf:
        q = q.filter(Tenant.name.ilike(f"%{_contains(tf['name'])}%"))
    return q


def _apply_geography_filter(q, spec: QuerySpec, ret: str):
    """Multi-select city/county/state. Properties/Tenants/Deals filter on
    the property's own location; Accounts/Contacts filter on the entity's
    own city/state (no county column there — silently ignored)."""
    geo = spec.geography
    if not geo:
        return q
    cities   = _as_list(geo.get("city"))
    counties = _as_list(geo.get("county"))
    states   = _as_list(geo.get("state"))

    if ret in ("properties", "tenants", "deals"):
        if cities:   q = q.filter(Property.city.in_(cities))
        if counties: q = q.filter(Property.county.in_(counties))
        if states:   q = q.filter(Property.state.in_(states))
    elif ret == "accounts":
        if cities: q = q.filter(Account.city.in_(cities))
        if states: q = q.filter(Account.state.in_(states))
    elif ret == "contacts":
        if cities: q = q.filter(Contact.city.in_(cities))
        if states: q = q.filter(Contact.state.in_(states))
    return q


def _ownership_col(ownership: str):
    """Map ownership mode to the Property FK that links to Account."""
    if ownership == "manager":
        return Property.manager_account_id   # stub: join works but no extra logic built
    return Property.recorded_owner_account_id   # default


# ── Pin-data helpers (property_parties — separate from the legacy
#    ownership-FK joins above, which only ever resolve one account) ──────

def _linked_properties_for_account(db, owner_id: int, account_id: int) -> list[dict]:
    rows = (db.query(Property.id, Property.lat, Property.lng, Property.address)
              .join(PropertyParty, PropertyParty.property_id == Property.id)
              .filter(PropertyParty.account_id == account_id, Property.owner_id == owner_id)
              .distinct()
              .all())
    return [{"id": r.id, "lat": r.lat, "lng": r.lng, "address": r.address} for r in rows]


def _linked_properties_for_contact(db, owner_id: int, contact_id: int) -> list[dict]:
    rows = (db.query(Property.id, Property.lat, Property.lng, Property.address)
              .join(PropertyParty, PropertyParty.property_id == Property.id)
              .filter(PropertyParty.contact_id == contact_id, Property.owner_id == owner_id)
              .distinct()
              .all())
    return [{"id": r.id, "lat": r.lat, "lng": r.lng, "address": r.address} for r in rows]


# ── Core query builder ────────────────────────────────────────────

def _run_query(spec: QuerySpec, owner_id: int, db: Session) -> dict:
    ret     = spec.return_type
    own_col = _ownership_col(spec.ownership)

    has_cf = bool(spec.contact)
    has_af = bool(spec.account)
    has_pf = bool(spec.property_filter)
    has_tf = bool(spec.tenant)

    # ── PROPERTIES ────────────────────────────────────────────────
    if ret == "properties":
        q = db.query(
            Property.id,
            Property.name,
            Property.address,
            Property.city,
            Property.state,
            Property.property_type,
            Property.county,
            Property.sf_rentable,
            Property.asking_price,
            Property.lat,
            Property.lng,
        ).filter(Property.owner_id == owner_id)

        if has_af or has_cf:
            q = q.join(
                Account,
                and_(Account.id == own_col, Account.owner_id == owner_id),
            )
        if has_cf:
            q = (q
                 .join(ContactAccount, ContactAccount.account_id == Account.id)
                 .join(Contact, and_(Contact.id == ContactAccount.contact_id,
                                     Contact.owner_id == owner_id)))
        if has_tf:
            q = (q
                 .join(PropertyTenant, and_(PropertyTenant.property_id == Property.id,
                                            PropertyTenant.owner_id == owner_id))
                 .join(Tenant, and_(Tenant.id == PropertyTenant.tenant_id,
                                    Tenant.owner_id == owner_id)))

        q = _apply_account_filters(q, spec)
        q = _apply_contact_filters(q, spec)
        q = _apply_property_filters(q, spec)
        q = _apply_tenant_filters(q, spec)
        q = _apply_geography_filter(q, spec, ret)

        total = q.with_entities(func.count(func.distinct(Property.id))).scalar() or 0
        rows  = q.distinct().offset(spec.offset).limit(spec.limit).all()
        items = [
            {
                "id": r.id,
                "type": "property",
                "display_name": r.name or r.address or f"Property #{r.id}",
                "address": r.address,
                "city": r.city,
                "state": r.state,
                "property_type": r.property_type,
                "county": r.county,
                "sf_rentable": r.sf_rentable,
                "asking_price": r.asking_price,
                "lat": r.lat,
                "lng": r.lng,
            }
            for r in rows
        ]

    # ── ACCOUNTS ──────────────────────────────────────────────────
    elif ret == "accounts":
        q = db.query(
            Account.id,
            Account.name,
            Account.entity_type,
            Account.roles,
            Account.city,
            Account.state,
            Account.lat,
            Account.lng,
        ).filter(Account.owner_id == owner_id)

        if has_cf:
            q = (q
                 .join(ContactAccount, ContactAccount.account_id == Account.id)
                 .join(Contact, and_(Contact.id == ContactAccount.contact_id,
                                     Contact.owner_id == owner_id)))
        if has_pf or has_tf:
            q = q.join(
                Property,
                and_(own_col == Account.id, Property.owner_id == owner_id),
            )
        if has_tf:
            q = (q
                 .join(PropertyTenant, and_(PropertyTenant.property_id == Property.id,
                                            PropertyTenant.owner_id == owner_id))
                 .join(Tenant, and_(Tenant.id == PropertyTenant.tenant_id,
                                    Tenant.owner_id == owner_id)))

        q = _apply_contact_filters(q, spec)
        q = _apply_account_filters(q, spec)
        q = _apply_property_filters(q, spec)
        q = _apply_tenant_filters(q, spec)
        q = _apply_geography_filter(q, spec, ret)

        total = q.with_entities(func.count(func.distinct(Account.id))).scalar() or 0
        rows  = q.distinct().offset(spec.offset).limit(spec.limit).all()
        items = [
            {
                "id": r.id,
                "type": "account",
                "display_name": r.name,
                "entity_type": r.entity_type,
                "roles": r.roles or [],
                "city": r.city,
                "state": r.state,
                "lat": r.lat,
                "lng": r.lng,
                "linked_properties": _linked_properties_for_account(db, owner_id, r.id),
            }
            for r in rows
        ]

    # ── CONTACTS ──────────────────────────────────────────────────
    elif ret == "contacts":
        q = db.query(
            Contact.id,
            Contact.first_name,
            Contact.last_name,
            Contact.email,
            Contact.title,
            Contact.city,
            Contact.state,
            Contact.lat,
            Contact.lng,
        ).filter(Contact.owner_id == owner_id)

        if has_af or has_pf or has_tf:
            q = (q
                 .join(ContactAccount, ContactAccount.contact_id == Contact.id)
                 .join(Account, and_(Account.id == ContactAccount.account_id,
                                     Account.owner_id == owner_id)))
        if has_pf or has_tf:
            q = q.join(
                Property,
                and_(own_col == Account.id, Property.owner_id == owner_id),
            )
        if has_tf:
            q = (q
                 .join(PropertyTenant, and_(PropertyTenant.property_id == Property.id,
                                            PropertyTenant.owner_id == owner_id))
                 .join(Tenant, and_(Tenant.id == PropertyTenant.tenant_id,
                                    Tenant.owner_id == owner_id)))

        q = _apply_contact_filters(q, spec)
        q = _apply_account_filters(q, spec)
        q = _apply_property_filters(q, spec)
        q = _apply_tenant_filters(q, spec)
        q = _apply_geography_filter(q, spec, ret)

        total = q.with_entities(func.count(func.distinct(Contact.id))).scalar() or 0
        rows  = q.distinct().offset(spec.offset).limit(spec.limit).all()
        items = [
            {
                "id": r.id,
                "type": "contact",
                "display_name": (
                    f"{r.first_name or ''} {r.last_name or ''}".strip()
                    or r.email
                    or f"Contact #{r.id}"
                ),
                "email": r.email,
                "title": r.title,
                "city": r.city,
                "state": r.state,
                "lat": r.lat,
                "lng": r.lng,
                "linked_properties": _linked_properties_for_contact(db, owner_id, r.id),
            }
            for r in rows
        ]

    # ── TENANTS ───────────────────────────────────────────────────
    # One row per occupied space (Tenant x Property via property_tenants) —
    # a chain tenant occupying 5 properties returns 5 rows, each with its
    # own direct lat/lng from that specific property (same shape as
    # Properties — no array needed since the row is already 1:1 with a
    # location, unlike Accounts/Contacts/Deals which can span many).
    elif ret == "tenants":
        q = (db.query(
                Tenant.id,
                Tenant.name,
                Tenant.industry,
                PropertyTenant.id.label("space_id"),
                Property.id.label("property_id"),
                Property.address,
                Property.city,
                Property.state,
                Property.lat,
                Property.lng,
            )
            .filter(Tenant.owner_id == owner_id)
            .join(PropertyTenant, and_(PropertyTenant.tenant_id == Tenant.id,
                                       PropertyTenant.owner_id == owner_id))
            .join(Property, and_(Property.id == PropertyTenant.property_id,
                                 Property.owner_id == owner_id)))

        if has_af or has_cf:
            q = q.join(
                Account,
                and_(Account.id == own_col, Account.owner_id == owner_id),
            )
        if has_cf:
            q = (q
                 .join(ContactAccount, ContactAccount.account_id == Account.id)
                 .join(Contact, and_(Contact.id == ContactAccount.contact_id,
                                     Contact.owner_id == owner_id)))

        q = _apply_account_filters(q, spec)
        q = _apply_contact_filters(q, spec)
        q = _apply_property_filters(q, spec)
        q = _apply_tenant_filters(q, spec)
        q = _apply_geography_filter(q, spec, ret)

        total = q.with_entities(func.count(func.distinct(PropertyTenant.id))).scalar() or 0
        rows  = q.distinct().offset(spec.offset).limit(spec.limit).all()
        items = [
            {
                "id": r.id,
                "type": "tenant",
                "space_id": r.space_id,
                "display_name": r.name,
                "industry": r.industry,
                "property_id": r.property_id,
                "address": r.address,
                "city": r.city,
                "state": r.state,
                "lat": r.lat,
                "lng": r.lng,
            }
            for r in rows
        ]

    # ── DEALS ─────────────────────────────────────────────────────
    # Deal links to exactly one Property via Deal.property_id (no
    # property_parties involved) — "linked_properties" is 0-or-1 entries,
    # kept as an array for shape-consistency with Accounts/Contacts. Deal
    # itself has no office location, so its own lat/lng is always null.
    elif ret == "deals":
        q = (db.query(
                Deal.id,
                Deal.name,
                Deal.stage,
                Deal.deal_type,
                Property.id.label("property_id"),
                Property.address,
                Property.city,
                Property.state,
                Property.county,
                Property.lat,
                Property.lng,
            )
            .filter(Deal.owner_id == owner_id)
            .join(Property, and_(Property.id == Deal.property_id,
                                 Property.owner_id == owner_id)))

        q = _apply_property_filters(q, spec)
        q = _apply_geography_filter(q, spec, ret)

        total = q.with_entities(func.count(func.distinct(Deal.id))).scalar() or 0
        rows  = q.distinct().offset(spec.offset).limit(spec.limit).all()
        items = [
            {
                "id": r.id,
                "type": "deal",
                "display_name": r.name,
                "stage": r.stage,
                "deal_type": r.deal_type,
                "lat": None,
                "lng": None,
                "linked_properties": [{
                    "id": r.property_id, "lat": r.lat, "lng": r.lng, "address": r.address,
                }] if r.property_id else [],
            }
            for r in rows
        ]

    else:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown return type '{ret}'. Valid values: {', '.join(sorted(VALID_RETURN_TYPES))}.",
        )

    return {
        "return_type": ret,
        "total": total,
        "offset": spec.offset,
        "limit": spec.limit,
        "items": items,
    }


# ── Geography typeahead — powers the chip multi-select in the Search page ──

_GEO_FIELD_SOURCE = {
    ("properties", "city"): Property.city, ("properties", "county"): Property.county,
    ("properties", "state"): Property.state,
    ("tenants", "city"): Property.city, ("tenants", "county"): Property.county,
    ("tenants", "state"): Property.state,
    ("deals", "city"): Property.city, ("deals", "county"): Property.county,
    ("deals", "state"): Property.state,
    ("accounts", "city"): Account.city, ("accounts", "state"): Account.state,
    ("contacts", "city"): Contact.city, ("contacts", "state"): Contact.state,
}


@router.get("/geo-options")
def geo_options(
    return_type: str = "properties",
    field:       str = "city",
    q:           str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct, owner-scoped values for one geography field — populates the
    typeahead behind the Search page's city/county/state chip picker."""
    col = _GEO_FIELD_SOURCE.get((return_type, field))
    if col is None:
        return []
    owner_col = {
        "properties": Property.owner_id, "tenants": Property.owner_id,
        "deals": Property.owner_id, "accounts": Account.owner_id,
        "contacts": Contact.owner_id,
    }[return_type]

    query = db.query(col).filter(owner_col == current_user.id, col.isnot(None), col != "")
    if q.strip():
        query = query.filter(col.ilike(f"%{q.strip()}%"))
    rows = query.distinct().order_by(col).limit(10).all()
    return [r[0] for r in rows]


# ── Endpoint ──────────────────────────────────────────────────────

@router.post("/")
def run_query(
    spec: QuerySpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if spec.return_type not in VALID_RETURN_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown return type '{spec.return_type}'. Valid values: {', '.join(sorted(VALID_RETURN_TYPES))}.",
        )
    return _run_query(spec, current_user.id, db)
