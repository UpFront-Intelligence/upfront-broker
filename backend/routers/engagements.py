from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from database import get_db
from models.account import Account
from models.property import Property
from models.engagement import Engagement, ENGAGEMENT_STAGES
from models.user import User
from auth_utils import get_current_user
from services.accounts import ensure_role

router = APIRouter()

# Engagement type -> role to add to the client account on create/update.
ENGAGEMENT_TYPE_ROLES = {
    'listing_sale': 'owner', 'listing_lease': 'owner', 'bov': 'owner',
    'buyer_rep': 'buyer', 'tenant_rep': 'tenant',
    'consulting': None, 'referral': None,
}


def _validate_links(db, client_account_id, subject_property_id, current_user):
    """Owner-isolation check for client_account_id / subject_property_id.

    Returns the resolved Account (or None) for ensure_role.
    """
    account = None
    if client_account_id is not None:
        account = db.query(Account).filter(
            Account.id == client_account_id, Account.owner_id == current_user.id
        ).first()
        if not account:
            raise HTTPException(status_code=404, detail=f"Account {client_account_id} not found")
    if subject_property_id is not None:
        prop = db.query(Property).filter(
            Property.id == subject_property_id, Property.owner_id == current_user.id
        ).first()
        if not prop:
            raise HTTPException(status_code=404, detail=f"Property {subject_property_id} not found")
    return account


class EngagementCreate(BaseModel):
    type: str
    stage: Optional[str] = "pursuing"
    signed_agreement: Optional[bool] = False
    agreement_date: Optional[date] = None
    client_account_id: Optional[int] = None
    subject_property_id: Optional[int] = None
    name: str
    notes: Optional[str] = None

class EngagementUpdate(EngagementCreate):
    type: Optional[str] = None
    name: Optional[str] = None

class EngagementResponse(EngagementCreate):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/")
def list_engagements(
    stage: Optional[str] = None,
    type: Optional[str] = None,
    group_by: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Engagement).filter(Engagement.owner_id == current_user.id)
    if stage:
        stages = [s.strip() for s in stage.split(",") if s.strip()]
        if stages: q = q.filter(Engagement.stage.in_(stages))
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if types: q = q.filter(Engagement.type.in_(types))
    items = q.order_by(Engagement.created_at.desc()).all()

    if group_by == "stage":
        grouped = {s: [] for s in ENGAGEMENT_STAGES}
        for e in items:
            grouped.setdefault(e.stage, []).append(EngagementResponse.model_validate(e))
        return grouped
    return items


@router.post("/", response_model=EngagementResponse)
def create_engagement(
    data: EngagementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = _validate_links(db, data.client_account_id, data.subject_property_id, current_user)
    eng = Engagement(**data.dict(), owner_id=current_user.id)
    db.add(eng)
    if account:
        role = ENGAGEMENT_TYPE_ROLES.get(data.type)
        if role:
            ensure_role(account, role)
    db.commit()
    db.refresh(eng)
    return eng


@router.get("/{engagement_id}", response_model=EngagementResponse)
def get_engagement(
    engagement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    eng = db.query(Engagement).filter(
        Engagement.id == engagement_id, Engagement.owner_id == current_user.id
    ).first()
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")
    return eng


@router.put("/{engagement_id}", response_model=EngagementResponse)
def update_engagement(
    engagement_id: int,
    data: EngagementUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    eng = db.query(Engagement).filter(
        Engagement.id == engagement_id, Engagement.owner_id == current_user.id
    ).first()
    if not eng:
        raise HTTPException(status_code=404, detail="Engagement not found")

    updated = data.dict(exclude_unset=True)
    client_account_id = updated.get('client_account_id', eng.client_account_id)
    subject_property_id = updated.get('subject_property_id', eng.subject_property_id)
    account = _validate_links(db, client_account_id, subject_property_id, current_user)

    for key, val in updated.items():
        setattr(eng, key, val)

    if account:
        eng_type = updated.get('type', eng.type)
        role = ENGAGEMENT_TYPE_ROLES.get(eng_type)
        if role:
            ensure_role(account, role)

    db.commit()
    db.refresh(eng)
    return eng
