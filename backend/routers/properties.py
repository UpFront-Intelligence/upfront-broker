from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Tuple
from datetime import date
import urllib.request, urllib.parse, json
from database import get_db
from models.property import Property
from models.user import User
from auth_utils import get_current_user


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

class PropertyCreate(BaseModel):
    name: Optional[str] = None
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

@router.get("/", response_model=List[PropertyResponse])
def list_properties(
    search: Optional[str] = None,
    property_type: Optional[str] = None,
    status: Optional[str] = None,
    account_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Property).filter(Property.owner_id == current_user.id)
    if search:
        q = q.filter(
            (Property.address.ilike(f"%{search}%")) |
            (Property.name.ilike(f"%{search}%")) |
            (Property.city.ilike(f"%{search}%"))
        )
    if property_type:
        q = q.filter(Property.property_type == property_type)
    if status:
        q = q.filter(Property.status == status)
    if account_id:
        q = q.filter(Property.account_id == account_id)
    return q.order_by(Property.address).all()

@router.post("/", response_model=PropertyResponse)
def create_property(
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prop = Property(**data.dict(), owner_id=current_user.id)
    db.add(prop)
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
    for key, val in updated.items():
        setattr(prop, key, val)
    db.commit()
    db.refresh(prop)
    if updated.keys() & {'address', 'city', 'state'} and prop.address:
        lat, lng = _geocode(prop.address, prop.city, prop.state)
        if lat is not None:
            prop.lat, prop.lng = lat, lng
            db.commit()
            db.refresh(prop)
    return prop

@router.get("/{property_id}/full")
def get_property_full(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.account import Account
    from models.contact import Contact
    from models.contact_account import ContactAccount
    from models.deal import Deal, DealContact
    from models.shared import Activity, Document
    prop = db.query(Property).filter(
        Property.id == property_id, Property.owner_id == current_user.id
    ).first()
    if not prop:
        raise HTTPException(404, "Property not found")

    acct = None
    if prop.account_id:
        a = db.query(Account).filter(Account.id == prop.account_id,
                                     Account.owner_id == current_user.id).first()
        if a:
            acct = {"id": a.id, "name": a.name, "entity_type": a.entity_type,
                    "city": a.city, "state": a.state}

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
