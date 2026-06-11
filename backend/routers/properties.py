from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Tuple
from datetime import date
import urllib.request, urllib.parse, json
from database import get_db
from models.account import Account
from models.property import Property
from models.user import User
from auth_utils import get_current_user
from services.accounts import ensure_role


# Oakland County CLASSCODE -> this app's CRE property_type (PROP_TYPES on
# property.html). Distinct from finder._classcode_to_type, which returns
# generic Michigan tax-classification labels (e.g. "Commercial") that don't
# match the CRE-specific types this app's UI understands.
_PARCEL_CLASSCODE_PROPERTY_TYPE = {
    201: "Office",       # Commercial
    202: "Office",       # Commercial Condo
    203: "Office",       # Commercial Other
    207: "Land",         # Commercial Vacant
    301: "Industrial",
    302: "Industrial",   # Industrial Condo
    403: "Multifamily",  # Residential Apartment
    407: "Land",         # Residential Vacant Land
}


def _parcel_classcode_to_property_type(code) -> Optional[str]:
    try:
        return _PARCEL_CLASSCODE_PROPERTY_TYPE.get(int(str(code).strip()))
    except (TypeError, ValueError):
        return None


def _geocode(address: str, city: str, state: str) -> Tuple[Optional[float], Optional[float]]:
    try:
        q = ', '.join(filter(None, [address, city, state, 'USA']))
        params = urllib.parse.urlencode({'q': q, 'format': 'json', 'limit': 1, 'countrycodes': 'us'})
        req = urllib.request.Request(
            f'https://nominatim.openstreetmap.org/search?{params}',
            headers={'User-Agent': 'UpFrontBroker/1.0 (credetroit@gmail.com)'},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            results = json.loads(resp.read())
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    except Exception:
        pass
    return None, None

router = APIRouter()

# Account-link fields on Property -> the role ensure_role() should add to
# that account once linked. tax_bill_account_id is a clue only — no role.
ACCOUNT_LINK_ROLES = {
    'recorded_owner_account_id': 'owner',
    'manager_account_id': 'property_manager',
    'tax_bill_account_id': None,
}


def _validate_account_links(db, link_values, current_user):
    """Resolve {field: account_id} to {field: Account} for non-null ids.

    Owner-isolation check: the referenced account must belong to the
    current broker, or the whole request is rejected.
    """
    accounts = {}
    for field, account_id in link_values.items():
        if account_id is None:
            continue
        acct = db.query(Account).filter(
            Account.id == account_id, Account.owner_id == current_user.id
        ).first()
        if not acct:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
        accounts[field] = acct
    return accounts


def _apply_account_link_roles(accounts):
    for field, acct in accounts.items():
        role = ACCOUNT_LINK_ROLES.get(field)
        if role:
            ensure_role(acct, role)


class PropertyCreate(BaseModel):
    name: Optional[str] = None
    building_name: Optional[str] = None
    park_name: Optional[str] = None
    address: str
    city: str
    state: str
    zip: Optional[str] = None
    county: Optional[str] = None
    property_type: Optional[str] = None
    subtype: Optional[str] = None
    status: Optional[str] = "Active"
    year_built: Optional[int] = None
    sf_rentable: Optional[float] = None
    sf_land: Optional[float] = None
    units: Optional[int] = None
    stories: Optional[int] = None
    zoning: Optional[str] = None
    parking_ratio: Optional[float] = None
    occupancy_pct: Optional[float] = None
    asking_price: Optional[float] = None
    asking_price_per_sf: Optional[float] = None
    assessed_value: Optional[float] = None
    tax_amount: Optional[float] = None
    tax_year: Optional[int] = None
    cap_rate: Optional[float] = None
    noi: Optional[float] = None
    parcel_id: Optional[str] = None
    legal_desc: Optional[str] = None
    tenant: Optional[str] = None
    last_sale_price: Optional[float] = None
    last_sale_date: Optional[date] = None
    notes: Optional[str] = None
    account_id: Optional[int] = None
    recorded_owner_account_id: Optional[int] = None
    manager_account_id: Optional[int] = None
    tax_bill_account_id: Optional[int] = None
    lat: Optional[float] = None
    lng: Optional[float] = None

class PropertyUpdate(PropertyCreate):
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None

class PropertyResponse(PropertyCreate):
    id: int

    class Config:
        from_attributes = True

class AttachParcelRequest(BaseModel):
    keypin: str

@router.get("/")
def list_properties(
    search: Optional[str] = None,
    # multi-value (comma-separated)
    property_type: Optional[str] = None,
    status:        Optional[str] = None,
    # location
    city:    Optional[str] = None,
    county:  Optional[str] = None,
    zip:     Optional[str] = None,
    state:   Optional[str] = None,
    subtype: Optional[str] = None,
    # size
    min_sf:  Optional[float] = None,  max_sf:  Optional[float] = None,
    min_land_sf: Optional[float] = None, max_land_sf: Optional[float] = None,
    min_units: Optional[int] = None,   max_units: Optional[int] = None,
    min_stories: Optional[int] = None, max_stories: Optional[int] = None,
    min_year: Optional[int] = None,    max_year: Optional[int] = None,
    # price / financial
    min_price: Optional[float] = None, max_price: Optional[float] = None,
    min_cap_rate: Optional[float] = None, max_cap_rate: Optional[float] = None,
    min_occupancy: Optional[float] = None, max_occupancy: Optional[float] = None,
    min_assessed: Optional[float] = None,  max_assessed: Optional[float] = None,
    min_tax: Optional[float] = None,       max_tax: Optional[float] = None,
    tax_year: Optional[int] = None,
    min_noi: Optional[float] = None,       max_noi: Optional[float] = None,
    min_last_sale: Optional[float] = None, max_last_sale: Optional[float] = None,
    last_sale_from: Optional[str] = None,  last_sale_to: Optional[str] = None,
    # other
    owner_name: Optional[str] = None,
    tenant:     Optional[str] = None,
    parcel_id:  Optional[str] = None,
    zoning:     Optional[str] = None,
    has_owner: Optional[bool] = None,
    has_deal:  Optional[bool] = None,
    added_from: Optional[str] = None, added_to: Optional[str] = None,
    # legacy
    account_id: Optional[int] = None,
    # pagination (activates paginated response when set)
    page:     Optional[int] = None,
    per_page: int = 50,
    sort_by:  str = "address",
    sort_dir: str = "asc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.deal import Deal
    from models.account import Account as Acct
    from datetime import datetime as dt
    q = db.query(Property).filter(Property.owner_id == current_user.id)

    if search:
        q = q.filter((Property.address.ilike(f"%{search}%")) |
                     (Property.name.ilike(f"%{search}%")) |
                     (Property.city.ilike(f"%{search}%")) |
                     (Property.parcel_id.ilike(f"%{search}%")))
    if property_type:
        types = [t.strip() for t in property_type.split(",") if t.strip()]
        if types: q = q.filter(Property.property_type.in_(types))
    if status:
        stats = [s.strip() for s in status.split(",") if s.strip()]
        if stats: q = q.filter(Property.status.in_(stats))
    if city:      q = q.filter(Property.city.ilike(f"%{city}%"))
    if county:    q = q.filter(Property.county.ilike(f"%{county}%"))
    if zip:       q = q.filter(Property.zip.ilike(f"{zip}%"))
    if state:     q = q.filter(Property.state.ilike(state))
    if subtype:   q = q.filter(Property.subtype.ilike(f"%{subtype}%"))
    if account_id: q = q.filter(Property.account_id == account_id)
    if min_sf:    q = q.filter(Property.sf_rentable >= min_sf)
    if max_sf:    q = q.filter(Property.sf_rentable <= max_sf)
    if min_land_sf: q = q.filter(Property.sf_land >= min_land_sf)
    if max_land_sf: q = q.filter(Property.sf_land <= max_land_sf)
    if min_units: q = q.filter(Property.units >= min_units)
    if max_units: q = q.filter(Property.units <= max_units)
    if min_stories: q = q.filter(Property.stories >= min_stories)
    if max_stories: q = q.filter(Property.stories <= max_stories)
    if min_year:  q = q.filter(Property.year_built >= min_year)
    if max_year:  q = q.filter(Property.year_built <= max_year)
    if min_price: q = q.filter(Property.asking_price >= min_price)
    if max_price: q = q.filter(Property.asking_price <= max_price)
    if min_cap_rate: q = q.filter(Property.cap_rate >= min_cap_rate)
    if max_cap_rate: q = q.filter(Property.cap_rate <= max_cap_rate)
    if min_occupancy: q = q.filter(Property.occupancy_pct >= min_occupancy)
    if max_occupancy: q = q.filter(Property.occupancy_pct <= max_occupancy)
    if min_assessed: q = q.filter(Property.assessed_value >= min_assessed)
    if max_assessed: q = q.filter(Property.assessed_value <= max_assessed)
    if min_tax:   q = q.filter(Property.tax_amount >= min_tax)
    if max_tax:   q = q.filter(Property.tax_amount <= max_tax)
    if tax_year:  q = q.filter(Property.tax_year == tax_year)
    if min_noi:   q = q.filter(Property.noi >= min_noi)
    if max_noi:   q = q.filter(Property.noi <= max_noi)
    if min_last_sale: q = q.filter(Property.last_sale_price >= min_last_sale)
    if max_last_sale: q = q.filter(Property.last_sale_price <= max_last_sale)
    if last_sale_from:
        try: q = q.filter(Property.last_sale_date >= dt.fromisoformat(last_sale_from).date())
        except: pass
    if last_sale_to:
        try: q = q.filter(Property.last_sale_date <= dt.fromisoformat(last_sale_to).date())
        except: pass
    if tenant:    q = q.filter(Property.tenant.ilike(f"%{tenant}%"))
    if parcel_id: q = q.filter(Property.parcel_id.ilike(f"%{parcel_id}%"))
    if zoning:    q = q.filter(Property.zoning.ilike(f"%{zoning}%"))
    if owner_name:
        q = q.join(Acct, Property.account_id == Acct.id, isouter=True).filter(
            Acct.name.ilike(f"%{owner_name}%"))
    if has_owner is True:  q = q.filter(Property.account_id.isnot(None))
    if has_owner is False: q = q.filter(Property.account_id.is_(None))
    if has_deal is not None:
        dpids = db.query(Deal.property_id).filter(Deal.owner_id == current_user.id)
        if has_deal: q = q.filter(Property.id.in_(dpids))
        else:        q = q.filter(Property.id.notin_(dpids))
    if added_from:
        try: q = q.filter(Property.created_at >= dt.fromisoformat(added_from))
        except: pass
    if added_to:
        try: q = q.filter(Property.created_at <= dt.fromisoformat(added_to))
        except: pass

    # Sort
    sort_map = {"address": Property.address, "city": Property.city,
                "asking_price": Property.asking_price, "sf_rentable": Property.sf_rentable,
                "year_built": Property.year_built, "created_at": Property.created_at}
    col = sort_map.get(sort_by, Property.address)
    q = q.order_by(col.desc() if sort_dir == "desc" else col.asc())

    if page is None:
        return q.all()
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return {"items": items, "total": total, "page": page,
            "per_page": per_page, "total_pages": max(1, (total + per_page - 1) // per_page)}

@router.post("/", response_model=PropertyResponse)
def create_property(
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    accounts = _validate_account_links(
        db, {f: getattr(data, f) for f in ACCOUNT_LINK_ROLES}, current_user)
    prop = Property(**data.dict(), owner_id=current_user.id)
    db.add(prop)
    _apply_account_link_roles(accounts)
    db.commit()
    db.refresh(prop)
    if not prop.lat and prop.address:
        lat, lng = _geocode(prop.address, prop.city, prop.state)
        if lat is not None:
            prop.lat, prop.lng = lat, lng
            db.commit()
            db.refresh(prop)
    return prop

@router.get("/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop

@router.put("/{property_id}", response_model=PropertyResponse)
def update_property(
    property_id: int,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    updated = data.dict(exclude_unset=True)
    accounts = _validate_account_links(
        db, {f: updated[f] for f in ACCOUNT_LINK_ROLES if f in updated}, current_user)
    for key, val in updated.items():
        setattr(prop, key, val)
    _apply_account_link_roles(accounts)
    db.commit()
    db.refresh(prop)
    if updated.keys() & {'address', 'city', 'state'} and prop.address:
        lat, lng = _geocode(prop.address, prop.city, prop.state)
        if lat is not None:
            prop.lat, prop.lng = lat, lng
            db.commit()
            db.refresh(prop)
    return prop

@router.post("/{property_id}/attach-parcel", response_model=PropertyResponse)
def attach_parcel(
    property_id: int,
    data: AttachParcelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Pull public-record fields from the local parcels table onto a property.

    Owner-isolated on the property; the parcels table itself is shared
    reference data (Option A) with no owner_id scoping.
    """
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    row = db.execute(
        text("SELECT keypin, siteaddress, sitecity, sitezip5, classcode,"
             " assessedvalue, living_area_sqft FROM parcels WHERE keypin = :k"),
        {"k": data.keypin},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Parcel not found")

    prop.parcel_id = row.keypin or data.keypin
    if row.assessedvalue is not None:
        prop.assessed_value = float(row.assessedvalue)
    if row.living_area_sqft is not None:
        prop.sf_rentable = float(row.living_area_sqft)
    if row.classcode:
        mapped_type = _parcel_classcode_to_property_type(row.classcode)
        if mapped_type:
            prop.property_type = mapped_type
    if not prop.address and row.siteaddress:
        prop.address = row.siteaddress
    if not prop.city and row.sitecity:
        prop.city = row.sitecity.title()
    if not prop.zip and row.sitezip5:
        prop.zip = row.sitezip5

    db.commit()
    db.refresh(prop)
    return prop

@router.get("/{property_id}/full")
def get_property_full(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.contact import Contact
    from models.contact_account import ContactAccount
    from models.deal import Deal, DealContact
    from models.shared import Activity, Document
    prop = db.query(Property).filter(
        Property.id == property_id, Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(404, "Property not found")

    # Batch-load any linked accounts (current owner entity + recorded owner)
    linked_ids = [aid for aid in (prop.account_id, prop.recorded_owner_account_id) if aid]
    accounts_by_id = {}
    if linked_ids:
        for a in db.query(Account).filter(Account.id.in_(linked_ids),
                                           Account.owner_id == current_user.id).all():
            accounts_by_id[a.id] = a

    acct = None
    if prop.account_id and prop.account_id in accounts_by_id:
        a = accounts_by_id[prop.account_id]
        acct = {"id": a.id, "name": a.name, "entity_type": a.entity_type,
                "city": a.city, "state": a.state}

    recorded_owner_account = None
    if prop.recorded_owner_account_id and prop.recorded_owner_account_id in accounts_by_id:
        a = accounts_by_id[prop.recorded_owner_account_id]
        recorded_owner_account = {"id": a.id, "name": a.name}

    contacts = []
    if prop.account_id:
        for ca, c in (db.query(ContactAccount, Contact)
                        .join(Contact, ContactAccount.contact_id == Contact.id)
                        .filter(ContactAccount.account_id == prop.account_id,
                                Contact.owner_id == current_user.id).all()):
            contacts.append({"id": c.id, "first_name": c.first_name,
                              "last_name": c.last_name, "title": c.title,
                              "role": ca.role, "is_primary": ca.is_primary})

    deals = [{"id": d.id, "name": d.name, "stage": d.stage, "deal_type": d.deal_type,
               "our_commission": d.our_commission,
               "projected_close": str(d.projected_close) if d.projected_close else None}
             for d in db.query(Deal).filter(Deal.property_id == property_id,
                                            Deal.owner_id == current_user.id).all()]

    acts = db.query(Activity).filter(Activity.property_id == property_id,
                                     Activity.owner_id == current_user.id
                                     ).order_by(Activity.activity_date.desc()).limit(20).all()
    docs = db.query(Document).filter(Document.property_id == property_id,
                                     Document.owner_id == current_user.id).all()

    prop_d = PropertyResponse.model_validate(prop).model_dump()
    # Serialize date fields
    for k, v in prop_d.items():
        if hasattr(v, 'isoformat'):
            prop_d[k] = v.isoformat()

    return {
        "property":   prop_d,
        "account":    acct,
        "recorded_owner_account": recorded_owner_account,
        "contacts":   contacts,
        "deals":      deals,
        "activities": [{"id": a.id, "activity_type": a.activity_type, "subject": a.subject,
                        "notes": a.notes,
                        "activity_date": str(a.activity_date) if a.activity_date else None,
                        "created_at": str(a.created_at)} for a in acts],
        "documents":  [{"id": d.id, "name": d.name, "doc_type": d.doc_type,
                        "file_url": d.file_url} for d in docs],
    }


@router.delete("/{property_id}")
def delete_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    db.delete(prop)
    db.commit()
    return {"deleted": True}
