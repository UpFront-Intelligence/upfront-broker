"""
Tenants router — /api/tenants

Route ordering matters: /fuzzy and /spaces/* must appear before /{tenant_id}
so FastAPI doesn't swallow them as integer path params.
"""
import re
import xml.etree.ElementTree as ET
from datetime import date as DateType
from typing import Optional
from urllib.parse import quote

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models.account import Account
from models.contact import Contact
from models.contact_account import ContactAccount
from models.property import Property
from models.property_tenant import PropertyTenant
from models.tenant import Tenant
from models.user import User

router = APIRouter()

# ── Name normalisation ────────────────────────────────────────────────────────

_STRIP = {
    'llc', 'corp', 'corporation', 'co', 'inc', 'incorporated', 'ltd', 'limited',
    'coffee', 'restaurant', 'cafe', 'company', 'the', 'group', 'holdings',
    'enterprises', 'bar', 'grill', 'kitchen', 'bistro', 'eatery', 'diner',
    'and', 'of', 'at', 'by',
}


def _normalize(name: str) -> str:
    if not name:
        return ''
    n = name.lower().strip()
    n = re.sub(r"[^\w\s]", ' ', n)
    words = [w for w in n.split() if w not in _STRIP]
    return ' '.join(words) if words else n.strip()


# ── Serialisers ───────────────────────────────────────────────────────────────

def _t(t: Tenant) -> dict:
    return {
        "id":              t.id,
        "name":            t.name,
        "normalized_name": t.normalized_name,
        "industry":        t.industry,
        "website":         t.website,
        "hq_address":      t.hq_address,
        "hq_city":         t.hq_city,
        "hq_state":        t.hq_state,
        "hq_zip":          t.hq_zip,
        "notes":           t.notes,
        "created_at":      t.created_at.isoformat() if t.created_at else None,
        "owner_id":        t.owner_id,
    }


def _pt(pt: PropertyTenant, tenant_name: str = None) -> dict:
    return {
        "id":              pt.id,
        "property_id":     pt.property_id,
        "tenant_id":       pt.tenant_id,
        "tenant_name":     tenant_name,
        "sf":              pt.sf,
        "pct_of_building": pt.pct_of_building,
        "rent_per_sf":     pt.rent_per_sf,
        "lease_type":      pt.lease_type,
        "lease_start":     pt.lease_start.isoformat()  if pt.lease_start  else None,
        "lease_expiry":    pt.lease_expiry.isoformat() if pt.lease_expiry else None,
        "is_available":    pt.is_available,
        "notes":           pt.notes,
        "owner_id":        pt.owner_id,
    }


# ── Pydantic models ───────────────────────────────────────────────────────────

INDUSTRIES = ['Food & Beverage', 'Financial', 'Retail', 'Medical',
              'Office', 'Industrial', 'Service', 'Other']

LEASE_TYPES = ['NNN', 'Gross', 'Modified Gross', 'Full Service']


class TenantIn(BaseModel):
    name:       str
    industry:   Optional[str] = None
    website:    Optional[str] = None
    hq_address: Optional[str] = None
    hq_city:    Optional[str] = None
    hq_state:   Optional[str] = None
    hq_zip:     Optional[str] = None
    notes:      Optional[str] = None


class TenantPatch(BaseModel):
    name:       Optional[str] = None
    industry:   Optional[str] = None
    website:    Optional[str] = None
    hq_address: Optional[str] = None
    hq_city:    Optional[str] = None
    hq_state:   Optional[str] = None
    hq_zip:     Optional[str] = None
    notes:      Optional[str] = None


class SpaceIn(BaseModel):
    property_id:     int
    tenant_id:       Optional[int]      = None
    tenant_name:     Optional[str]      = None   # used when creating a new tenant inline
    tenant_industry: Optional[str]      = None
    sf:              Optional[int]      = None
    pct_of_building: Optional[float]   = None
    rent_per_sf:     Optional[float]   = None
    lease_type:      Optional[str]     = None
    lease_start:     Optional[DateType] = None
    lease_expiry:    Optional[DateType] = None
    is_available:    bool              = False
    notes:           Optional[str]     = None


class SpacePatch(BaseModel):
    sf:              Optional[int]      = None
    pct_of_building: Optional[float]   = None
    rent_per_sf:     Optional[float]   = None
    lease_type:      Optional[str]     = None
    lease_start:     Optional[DateType] = None
    lease_expiry:    Optional[DateType] = None
    is_available:    Optional[bool]    = None
    notes:           Optional[str]     = None


# ─────────────────────────────────────────────────────────────────────────────
# Routes that must appear BEFORE /{tenant_id} to avoid path-param capture
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/fuzzy")
def fuzzy_match(
    name:         str     = Query(..., min_length=1),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Return existing tenants with normalized names similar to `name`."""
    norm = _normalize(name)
    if len(norm) < 2:
        return []
    tenants = db.query(Tenant).filter(Tenant.owner_id == current_user.id).all()
    hits = []
    for t in tenants:
        score = fuzz.partial_ratio(norm, t.normalized_name or '')
        if score >= 55:
            hits.append({"id": t.id, "name": t.name, "industry": t.industry, "score": score})
    hits.sort(key=lambda x: -x['score'])
    return hits[:6]


@router.get("/spaces")
def list_spaces(
    property_id:  int     = Query(...),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """List all property_tenant records for one property, with tenant names."""
    rows = (
        db.query(PropertyTenant, Tenant.name)
        .join(Tenant, PropertyTenant.tenant_id == Tenant.id)
        .filter(
            PropertyTenant.property_id == property_id,
            PropertyTenant.owner_id    == current_user.id,
        )
        .all()
    )
    return [_pt(pt, tname) for pt, tname in rows]


@router.post("/spaces", status_code=201)
def create_space(
    body:         SpaceIn,
    db:           Session  = Depends(get_db),
    current_user: User     = Depends(get_current_user),
):
    """Create a property_tenant space. If tenant_id is omitted, auto-create a new Tenant."""
    tid = body.tenant_id
    if not tid:
        if not body.tenant_name:
            raise HTTPException(400, "tenant_id or tenant_name required")
        t = Tenant(
            owner_id        = current_user.id,
            name            = body.tenant_name.strip(),
            normalized_name = _normalize(body.tenant_name),
            industry        = body.tenant_industry,
        )
        db.add(t)
        db.flush()
        tid = t.id

    pt = PropertyTenant(
        owner_id        = current_user.id,
        property_id     = body.property_id,
        tenant_id       = tid,
        sf              = body.sf,
        pct_of_building = body.pct_of_building,
        rent_per_sf     = body.rent_per_sf,
        lease_type      = body.lease_type,
        lease_start     = body.lease_start,
        lease_expiry    = body.lease_expiry,
        is_available    = body.is_available,
        notes           = body.notes,
    )
    db.add(pt)
    db.commit()
    db.refresh(pt)
    tname = db.query(Tenant.name).filter(Tenant.id == tid).scalar()
    return _pt(pt, tname)


@router.put("/spaces/{space_id}")
def update_space(
    space_id:     int,
    body:         SpacePatch,
    db:           Session    = Depends(get_db),
    current_user: User       = Depends(get_current_user),
):
    pt = db.query(PropertyTenant).filter(
        PropertyTenant.id       == space_id,
        PropertyTenant.owner_id == current_user.id,
    ).first()
    if not pt:
        raise HTTPException(404, "Space not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(pt, k, v)
    db.commit()
    db.refresh(pt)
    tname = db.query(Tenant.name).filter(Tenant.id == pt.tenant_id).scalar()
    return _pt(pt, tname)


@router.delete("/spaces/{space_id}")
def delete_space(
    space_id:     int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    pt = db.query(PropertyTenant).filter(
        PropertyTenant.id       == space_id,
        PropertyTenant.owner_id == current_user.id,
    ).first()
    if not pt:
        raise HTTPException(404, "Space not found")
    db.delete(pt)
    db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Tenant entity CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
def list_tenants(
    q:            Optional[str] = Query(None),
    industry:     Optional[str] = Query(None),
    db:           Session       = Depends(get_db),
    current_user: User          = Depends(get_current_user),
):
    qs = db.query(Tenant).filter(Tenant.owner_id == current_user.id)
    if q:
        qs = qs.filter(Tenant.name.ilike(f"%{q}%"))
    if industry:
        qs = qs.filter(Tenant.industry == industry)
    tenants = qs.order_by(Tenant.name).all()

    result = []
    for t in tenants:
        d = _t(t)
        spaces = db.query(PropertyTenant).filter(
            PropertyTenant.tenant_id == t.id,
            PropertyTenant.owner_id  == current_user.id,
        ).all()
        d['property_count'] = len({s.property_id for s in spaces})
        d['total_sf']       = sum(s.sf or 0 for s in spaces)
        result.append(d)
    return result


@router.post("/", status_code=201)
def create_tenant(
    body:         TenantIn,
    db:           Session   = Depends(get_db),
    current_user: User      = Depends(get_current_user),
):
    t = Tenant(
        owner_id        = current_user.id,
        name            = body.name.strip(),
        normalized_name = _normalize(body.name),
        industry        = body.industry,
        website         = body.website,
        hq_address      = body.hq_address,
        hq_city         = body.hq_city,
        hq_state        = body.hq_state,
        hq_zip          = body.hq_zip,
        notes           = body.notes,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _t(t)


@router.get("/{tenant_id}")
def get_tenant(
    tenant_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    t = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.owner_id == current_user.id
    ).first()
    if not t:
        raise HTTPException(404, "Tenant not found")

    d = _t(t)

    # Spaces with property details
    rows = (
        db.query(PropertyTenant, Property)
        .join(Property, PropertyTenant.property_id == Property.id)
        .filter(
            PropertyTenant.tenant_id  == tenant_id,
            PropertyTenant.owner_id   == current_user.id,
        )
        .all()
    )
    spaces = []
    for pt, prop in rows:
        s = _pt(pt, t.name)
        s['property_name']    = prop.name or prop.address
        s['property_address'] = prop.address
        s['property_city']    = prop.city
        s['property_state']   = prop.state
        s['property_type']    = prop.property_type
        s['property_sf']      = prop.sf_rentable
        spaces.append(s)
    d['spaces'] = spaces

    # Total SF across all spaces
    d['total_sf']       = sum(s['sf'] or 0 for s in spaces)
    d['property_count'] = len({s['property_id'] for s in spaces})

    return d


@router.put("/{tenant_id}")
def update_tenant(
    tenant_id:    int,
    body:         TenantPatch,
    db:           Session     = Depends(get_db),
    current_user: User        = Depends(get_current_user),
):
    t = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.owner_id == current_user.id
    ).first()
    if not t:
        raise HTTPException(404, "Tenant not found")
    updates = body.model_dump(exclude_unset=True)
    if 'name' in updates:
        updates['normalized_name'] = _normalize(updates['name'])
    for k, v in updates.items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return _t(t)


@router.delete("/{tenant_id}")
def delete_tenant(
    tenant_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    t = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.owner_id == current_user.id
    ).first()
    if not t:
        raise HTTPException(404, "Tenant not found")
    db.delete(t)
    db.commit()
    return {"ok": True}


def _contacts_with_accounts(contacts: list, db: Session, owner_id: int) -> list:
    """Serialize contact list with primary account name — one batch query."""
    if not contacts:
        return []
    cids = [c.id for c in contacts]
    rows = (
        db.query(
            ContactAccount.contact_id,
            Account.id.label('acct_id'),
            Account.name.label('acct_name'),
            ContactAccount.is_primary,
        )
        .join(Account, ContactAccount.account_id == Account.id)
        .filter(ContactAccount.contact_id.in_(cids), Account.owner_id == owner_id)
        .order_by(ContactAccount.is_primary.desc())
        .all()
    )
    acct_map: dict = {}
    for r in rows:
        if r.contact_id not in acct_map:
            acct_map[r.contact_id] = (r.acct_id, r.acct_name)
    result = []
    for c in contacts:
        acct = acct_map.get(c.id)
        result.append({
            "id":           c.id,
            "first_name":   c.first_name,
            "last_name":    c.last_name,
            "title":        c.title,
            "email":        c.email,
            "phone":        c.phone or c.mobile,
            "tenant_id":    c.tenant_id,
            "account_id":   acct[0] if acct else None,
            "account_name": acct[1] if acct else None,
        })
    return result


@router.get("/{tenant_id}/contacts")
def get_tenant_contacts(
    tenant_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Combined contacts: direct tenant_id FK + fuzzy account-name match."""
    t = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.owner_id == current_user.id
    ).first()
    if not t:
        raise HTTPException(404, "Tenant not found")

    seen: set = set()
    contacts: list = []

    # 1. Direct FK: contacts where contact.tenant_id = this tenant
    direct = (
        db.query(Contact)
        .filter(Contact.tenant_id == tenant_id, Contact.owner_id == current_user.id)
        .all()
    )
    for c in direct:
        if c.id not in seen:
            seen.add(c.id)
            contacts.append(c)

    # 2. Contacts linked via accounts whose name fuzzy-matches this tenant
    norm = t.normalized_name or _normalize(t.name)
    all_accts = db.query(Account).filter(Account.owner_id == current_user.id).all()
    matched_ids = [
        a.id for a in all_accts
        if fuzz.partial_ratio(_normalize(a.name), norm) >= 55
    ]
    if matched_ids:
        fuzzy_contacts = (
            db.query(Contact)
            .join(ContactAccount, ContactAccount.contact_id == Contact.id)
            .filter(
                ContactAccount.account_id.in_(matched_ids),
                Contact.owner_id == current_user.id,
            )
            .all()
        )
        for c in fuzzy_contacts:
            if c.id not in seen:
                seen.add(c.id)
                contacts.append(c)

    return _contacts_with_accounts(contacts, db, current_user.id)


@router.get("/{tenant_id}/news")
def get_tenant_news(
    tenant_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Fetch recent news via Google News RSS — no API key required."""
    t = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.owner_id == current_user.id
    ).first()
    if not t:
        raise HTTPException(404, "Tenant not found")

    query = f'"{t.name}"'
    url   = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = http_requests.get(
            url, timeout=8,
            headers={"User-Agent": "UpFrontBroker/1.0 (credetroit@gmail.com)"},
        )
        resp.raise_for_status()
        root  = ET.fromstring(resp.content)
        items = []
        for item in root.findall('.//item')[:10]:
            raw_title = item.findtext('title', '')
            title     = raw_title.split(' - ')[0].strip()
            link      = item.findtext('link', '')
            date      = item.findtext('pubDate', '')
            source    = item.findtext('source', '')
            if title and link:
                items.append({
                    'headline': title,
                    'url':      link,
                    'date':     date,
                    'source':   source,
                })
        return items
    except Exception:
        return []
