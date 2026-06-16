from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel, Field
from typing import Any

from database import get_db
from models.contact import Contact
from models.contact_account import ContactAccount
from models.account import Account
from models.property import Property
from models.property_tenant import PropertyTenant
from models.tenant import Tenant
from models.user import User
from auth_utils import get_current_user

router = APIRouter()


# ── Request schema ────────────────────────────────────────────────

class QuerySpec(BaseModel):
    return_type: str = Field("contacts", alias="return")
    contact:         dict[str, Any] = Field(default_factory=dict)
    account:         dict[str, Any] = Field(default_factory=dict)
    property_filter: dict[str, Any] = Field(default_factory=dict, alias="property")
    tenant:          dict[str, Any] = Field(default_factory=dict)
    ownership: str = "recorded"
    limit:     int = 200
    offset:    int = 0

    model_config = {"populate_by_name": True}


# ── Filter helpers ────────────────────────────────────────────────

def _contains(val: Any) -> str:
    return val["contains"] if isinstance(val, dict) and "contains" in val else str(val)


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
    return q


def _apply_tenant_filters(q, spec: QuerySpec):
    tf = spec.tenant
    if "name" in tf:
        q = q.filter(Tenant.name.ilike(f"%{_contains(tf['name'])}%"))
    return q


def _ownership_col(ownership: str):
    """Map ownership mode to the Property FK that links to Account."""
    if ownership == "manager":
        return Property.manager_account_id   # stub: join works but no extra logic built
    return Property.recorded_owner_account_id   # default


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
            }
            for r in rows
        ]

    else:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown return type '{ret}'. Valid values: contacts, accounts, properties.",
        )

    return {
        "return_type": ret,
        "total": total,
        "offset": spec.offset,
        "limit": spec.limit,
        "items": items,
    }


# ── Endpoint ──────────────────────────────────────────────────────

@router.post("/")
def run_query(
    spec: QuerySpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _run_query(spec, current_user.id, db)
