from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
import csv, io
from database import get_db
from models.shared import Comp
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

# ── Column name aliases (see CRE_DATA_DICTIONARY.md) ──────────────────────
# Each entry: primary name first, then known variants.

_SALE_SIGNATURES  = {'Sale Price', 'Recorded Buyer', 'Sale Date'}
_LEASE_SIGNATURES = {'Tenant Name', 'Commencement Date', 'Transaction Size'}

_COL = {
    # Common
    'address':       ('Building Address', 'Property Address', 'Address'),
    'city':          ('City',),
    'state':         ('State',),
    'property_type': ('Property Type',),
    'year_built':    ('Year Built',),
    # Sale-specific
    'sf_bldg':       ('RBA', 'Building Size (SF)'),
    'sale_price':    ('Sale Price', 'Price'),
    'price_per_sf':  ('Price/SF', 'Sale Price/SF'),
    'cap_rate':      ('Cap Rate',),
    'sale_date':     ('Sale Date', 'Close Date'),
    'prop_name':     ('Property Name',),
    'buyer':         ('Recorded Buyer', 'Buyer'),
    'seller':        ('Recorded Seller', 'Seller'),
    'noi':           ('NOI at Sale', 'NOI'),
    'txn_type_sale': ('Transaction Type',),
    'parcel':        ('Parcel No.', 'Parcel Number', 'APN'),
    'bldg_class':    ('Building Class',),
    'submarket':     ('Submarket',),
    'dom':           ('Days On Market',),
    'verified_sale': ('Verified', 'Confirmed'),
    # Lease-specific
    'sf_leased':     ('Transaction Size', 'Transaction Size (SF)', 'Leased SF'),
    'eff_rent':      ('Effective Rent', 'Effective Rent/SF/Yr'),
    'commence':      ('Commencement Date', 'Lease Start Date'),
    'tenant':        ('Tenant Name',),
    'lease_type':    ('Lease Type',),
    'lease_term':    ('Lease Term', 'Lease Term (Months)'),
    'start_rent':    ('Starting Rent', 'Starting Rent/SF/Yr'),
    'asking_rent':   ('Asking Rent', 'Asking Rent/SF/Yr'),
    'free_rent':     ('Free Rent', 'Free Rent (Months)'),
    'ti':            ('TI Allowance', 'TI Allowance (TI/SF)', 'TI/SF'),
    'expire':        ('Expiration Date', 'Lease End Date'),
    'suite':         ('Suite', 'Suite/Floor', 'Floor'),
    'parent_co':     ('Parent Company',),
    'space_type':    ('Space Type',),
    'verified_lease':('Verified', 'Confirmed'),
}


def _get(row: dict, key: str) -> Optional[str]:
    """Return the first non-empty value matching any alias for key."""
    for col in _COL.get(key, ()):
        v = row.get(col, '').strip()
        if v:
            return v
    return None


def _detect(headers: set) -> str:
    if headers & _LEASE_SIGNATURES:
        return 'lease'
    if headers & _SALE_SIGNATURES:
        return 'sale'
    return 'unknown'


def _map_sale(row: dict, owner_id: int, property_id: Optional[int]) -> Comp:
    parts = []
    for label, key in [
        ('Property', 'prop_name'), ('Buyer', 'buyer'), ('Seller', 'seller'),
        ('NOI', 'noi'), ('Type', 'txn_type_sale'), ('Parcel', 'parcel'),
        ('Class', 'bldg_class'), ('Submarket', 'submarket'),
        ('DOM', 'dom'), ('Verified', 'verified_sale'),
    ]:
        v = _get(row, key)
        if v:
            parts.append(f'{label}: {v}')

    return Comp(
        owner_id=owner_id,
        property_id=property_id,
        address=_get(row, 'address') or '',
        city=_get(row, 'city') or '',
        state=_get(row, 'state') or '',
        property_type=_get(row, 'property_type') or '',
        sf=_float(_get(row, 'sf_bldg')),
        sale_price=_float(_get(row, 'sale_price')),
        price_per_sf=_float(_get(row, 'price_per_sf')),
        cap_rate=_float(_get(row, 'cap_rate')),
        sale_date=_date(_get(row, 'sale_date')),
        year_built=_int(_get(row, 'year_built')),
        source='CRE Import',
        notes='\n'.join(parts) or None,
    )


def _map_lease(row: dict, owner_id: int, property_id: Optional[int]) -> Comp:
    parts = []
    for label, key in [
        ('Property', 'prop_name'), ('Tenant', 'tenant'), ('Parent Co', 'parent_co'),
        ('Suite', 'suite'), ('Lease Type', 'lease_type'), ('Term', 'lease_term'),
        ('Starting Rent', 'start_rent'), ('Asking Rent', 'asking_rent'),
        ('Free Rent', 'free_rent'), ('TI', 'ti'), ('Expires', 'expire'),
        ('Class', 'bldg_class'), ('Submarket', 'submarket'),
        ('Verified', 'verified_lease'),
    ]:
        v = _get(row, key)
        if v:
            # append units for well-known numeric fields
            if key == 'lease_term':
                parts.append(f'Term: {v} mo')
            elif key in ('free_rent',):
                parts.append(f'Free Rent: {v} mo')
            elif key == 'ti':
                parts.append(f'TI: ${v}/SF')
            else:
                parts.append(f'{label}: {v}')

    prop_type = _get(row, 'property_type') or _get(row, 'space_type') or ''

    return Comp(
        owner_id=owner_id,
        property_id=property_id,
        address=_get(row, 'address') or '',
        city=_get(row, 'city') or '',
        state=_get(row, 'state') or '',
        property_type=prop_type,
        sf=_float(_get(row, 'sf_leased')),
        sale_price=None,
        price_per_sf=_float(_get(row, 'eff_rent')),
        cap_rate=None,
        sale_date=_date(_get(row, 'commence')),
        year_built=_int(_get(row, 'year_built')),
        source='CRE Import',
        notes='\n'.join(parts) or None,
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CompCreate(BaseModel):
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    property_type: Optional[str] = None
    sf: Optional[float] = None
    sale_price: Optional[float] = None
    price_per_sf: Optional[float] = None
    cap_rate: Optional[float] = None
    sale_date: Optional[date] = None
    year_built: Optional[int] = None
    source: Optional[str] = "Manual"
    notes: Optional[str] = None
    property_id: Optional[int] = None

class CompResponse(CompCreate):
    id: int
    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[CompResponse])
def list_comps(
    property_id: Optional[int] = None,
    property_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Comp).filter(Comp.owner_id == current_user.id)
    if property_id:
        q = q.filter(Comp.property_id == property_id)
    if property_type:
        q = q.filter(Comp.property_type == property_type)
    return q.order_by(Comp.sale_date.desc()).all()


@router.post("/", response_model=CompResponse)
def create_comp(
    data: CompCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    comp = Comp(**data.dict(), owner_id=current_user.id)
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return comp


@router.post("/upload-cre")
async def upload_cre_csv(
    file: UploadFile = File(...),
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    content = await file.read()
    text = content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers = set(reader.fieldnames)
    comp_type = _detect(headers)

    if comp_type == 'unknown':
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot detect export type. Expected sale comp columns "
                f"({', '.join(sorted(_SALE_SIGNATURES))}) or lease comp columns "
                f"({', '.join(sorted(_LEASE_SIGNATURES))})."
            )
        )

    mapper = _map_sale if comp_type == 'sale' else _map_lease
    imported, errors = 0, []

    for i, row in enumerate(reader, start=2):  # row 1 = headers
        try:
            comp = mapper(row, current_user.id, property_id)
            if not comp.address:
                continue  # skip blank rows
            db.add(comp)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i}: {e}")

    db.commit()
    return {
        "comp_type": comp_type,
        "imported": imported,
        "errors": errors,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _float(val: Optional[str]) -> Optional[float]:
    if not val:
        return None
    try:
        return float(val.replace('$', '').replace(',', '').replace('%', '').strip())
    except (ValueError, AttributeError):
        return None


def _int(val: Optional[str]) -> Optional[int]:
    if not val:
        return None
    try:
        return int(float(val.replace(',', '').strip()))
    except (ValueError, AttributeError):
        return None


def _date(val: Optional[str]) -> Optional[date]:
    if not val:
        return None
    from datetime import datetime
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%y', '%m-%d-%Y'):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            pass
    return None
