from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
from database import get_db
from models.deal import Deal, DealContact
from models.contact import Contact
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

class DealContactResponse(BaseModel):
    deal_contact_id: int
    contact_id: Optional[int]
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    title: Optional[str]
    contact_type: Optional[str]
    role: Optional[str]


class DealCreate(BaseModel):
    name: str
    property_id: int
    deal_type: Optional[str] = None
    stage: Optional[str] = "Prospecting"
    list_price: Optional[float] = None
    sale_price: Optional[float] = None
    lease_rate: Optional[float] = None
    lease_sf: Optional[float] = None
    lease_term_months: Optional[int] = None
    commission_pct: Optional[float] = None
    our_split_pct: Optional[float] = 100.0
    co_broker: Optional[bool] = False
    co_broker_name: Optional[str] = None
    co_broker_firm: Optional[str] = None
    co_broker_split_pct: Optional[float] = None
    projected_close: Optional[date] = None
    list_date: Optional[date] = None
    notes: Optional[str] = None

class DealUpdate(DealCreate):
    name: Optional[str] = None
    property_id: Optional[int] = None

class DealResponse(BaseModel):
    id: int
    name: str
    property_id: int
    deal_type: Optional[str]
    stage: Optional[str]
    list_price: Optional[float]
    sale_price: Optional[float]
    commission_pct: Optional[float]
    commission_total: Optional[float]
    our_split_pct: Optional[float]
    our_commission: Optional[float]
    co_broker: Optional[bool]
    co_broker_name: Optional[str]
    co_broker_firm: Optional[str]
    co_broker_split_pct: Optional[float]
    projected_close: Optional[date]
    actual_close: Optional[date]
    list_date: Optional[date]
    days_on_market: Optional[int]
    stage: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True

def calculate_commission(deal: Deal):
    """Recalculate commission fields based on current deal data."""
    base = deal.sale_price or deal.list_price or 0
    if deal.deal_type in ["Lease - Landlord", "Lease - Tenant"] and deal.lease_rate and deal.lease_sf and deal.lease_term_months:
        base = deal.lease_rate * deal.lease_sf * (deal.lease_term_months / 12)
    if base and deal.commission_pct:
        deal.commission_total = round(base * (deal.commission_pct / 100), 2)
        deal.our_commission = round(deal.commission_total * ((deal.our_split_pct or 100) / 100), 2)
        if deal.co_broker and deal.co_broker_split_pct:
            deal.co_broker_split_pct = 100 - (deal.our_split_pct or 100)

@router.get("/", response_model=List[DealResponse])
def list_deals(
    stage: Optional[str] = None,
    deal_type: Optional[str] = None,
    contact_id: Optional[int] = None,
    account_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Deal).filter(Deal.owner_id == current_user.id)
    if stage:
        q = q.filter(Deal.stage == stage)
    if deal_type:
        q = q.filter(Deal.deal_type == deal_type)
    if contact_id:
        deal_ids = [r.deal_id for r in
                    db.query(DealContact.deal_id)
                    .filter(DealContact.contact_id == contact_id).all()]
        q = q.filter(Deal.id.in_(deal_ids))
    if account_id:
        deal_ids = [r.deal_id for r in
                    db.query(DealContact.deal_id)
                    .filter(DealContact.account_id == account_id).all()]
        q = q.filter(Deal.id.in_(deal_ids))
    return q.order_by(Deal.projected_close).all()

@router.post("/", response_model=DealResponse)
def create_deal(
    data: DealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deal = Deal(**data.dict(), owner_id=current_user.id)
    calculate_commission(deal)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal

@router.get("/pipeline-summary")
def pipeline_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deals = db.query(Deal).filter(Deal.owner_id == current_user.id).all()
    total_value = sum(d.our_commission or 0 for d in deals if d.stage != "Dead")
    return {
        "total_deals": len([d for d in deals if d.stage != "Dead"]),
        "by_stage": {
            "Prospecting":      len([d for d in deals if d.stage == "Prospecting"]),
            "Pitching":         len([d for d in deals if d.stage == "Pitching"]),
            "Active Listing":   len([d for d in deals if d.stage == "Active Listing"]),
            "Under Contract":   len([d for d in deals if d.stage == "Under Contract"]),
            "Closed":           len([d for d in deals if d.stage == "Closed"]),
        },
        "total_commission_value": total_value,
        "closed_commission_ytd": sum(d.our_commission or 0 for d in deals if d.stage == "Closed"),
    }

@router.get("/{deal_id}", response_model=DealResponse)
def get_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deal = db.query(Deal).filter(
        Deal.id == deal_id,
        Deal.owner_id == current_user.id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal

@router.put("/{deal_id}", response_model=DealResponse)
def update_deal(
    deal_id: int,
    data: DealUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deal = db.query(Deal).filter(
        Deal.id == deal_id,
        Deal.owner_id == current_user.id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    for key, val in data.dict(exclude_unset=True).items():
        setattr(deal, key, val)
    calculate_commission(deal)
    db.commit()
    db.refresh(deal)
    return deal

@router.get("/{deal_id}/contacts", response_model=List[DealContactResponse])
def get_deal_contacts(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deal = db.query(Deal).filter(
        Deal.id == deal_id, Deal.owner_id == current_user.id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    rows = (
        db.query(DealContact, Contact)
        .outerjoin(Contact, DealContact.contact_id == Contact.id)
        .filter(DealContact.deal_id == deal_id)
        .all()
    )
    return [
        DealContactResponse(
            deal_contact_id=dc.id,
            contact_id=c.id if c else None,
            first_name=c.first_name if c else None,
            last_name=c.last_name if c else None,
            email=c.email if c else None,
            phone=c.phone if c else None,
            title=c.title if c else None,
            contact_type=c.contact_type if c else None,
            role=dc.role,
        )
        for dc, c in rows
    ]


@router.delete("/{deal_id}")
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deal = db.query(Deal).filter(
        Deal.id == deal_id,
        Deal.owner_id == current_user.id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    db.delete(deal)
    db.commit()
    return {"deleted": True}
