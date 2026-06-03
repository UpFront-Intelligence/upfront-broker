from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from database import get_db
from models.shared import Activity
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

class ActivityCreate(BaseModel):
    activity_type: str
    subject: Optional[str] = None
    notes: Optional[str] = None
    activity_date: Optional[datetime] = None
    contact_id: Optional[int] = None
    property_id: Optional[int] = None
    deal_id: Optional[int] = None

class ActivityResponse(ActivityCreate):
    id: int
    class Config:
        from_attributes = True

@router.get("/", response_model=List[ActivityResponse])
def list_activities(
    deal_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Activity).filter(Activity.owner_id == current_user.id)
    if deal_id:
        q = q.filter(Activity.deal_id == deal_id)
    if contact_id:
        q = q.filter(Activity.contact_id == contact_id)
    if property_id:
        q = q.filter(Activity.property_id == property_id)
    return q.order_by(Activity.activity_date.desc()).all()

@router.post("/", response_model=ActivityResponse)
def create_activity(
    data: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    activity = Activity(**data.dict(), owner_id=current_user.id)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity

@router.delete("/{activity_id}")
def delete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    activity = db.query(Activity).filter(
        Activity.id == activity_id,
        Activity.owner_id == current_user.id
    ).first()
    db.delete(activity)
    db.commit()
    return {"deleted": True}
