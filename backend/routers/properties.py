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
