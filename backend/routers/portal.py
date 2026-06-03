from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models.shared import Portal, PortalView, Document
from models.deal import Deal
from models.property import Property
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

class PortalCreate(BaseModel):
    deal_id: int
    seller_emails: Optional[List[str]] = []
    buyer_emails: Optional[List[str]] = []
    pov: Optional[str] = None
    challenges: Optional[str] = None
    mutual_steps: Optional[str] = None
    show_timeline: Optional[bool] = True
    show_docs: Optional[bool] = True
    show_comps: Optional[bool] = False
    show_offers: Optional[bool] = False

@router.post("/")
def create_portal(
    data: PortalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    portal = Portal(**data.dict())
    db.add(portal)
    db.commit()
    db.refresh(portal)
    return {"token": portal.token, "url": f"/portal/{portal.token}"}

@router.get("/{deal_id}")
def get_portal_for_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    deal = db.query(Deal).filter(
        Deal.id == deal_id, Deal.owner_id == current_user.id
    ).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    portal = db.query(Portal).filter(Portal.deal_id == deal_id).first()
    if not portal:
        raise HTTPException(status_code=404, detail="No portal for this deal")
    return {"token": portal.token, "deal_id": portal.deal_id}


@router.get("/token/{token}")
def get_portal_by_token(token: str, email: str, db: Session = Depends(get_db)):
    portal = db.query(Portal).filter(Portal.token == token).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Portal not found")
    all_emails = (portal.seller_emails or []) + (portal.buyer_emails or [])
    email_lower = email.strip().lower()
    if email_lower not in [e.lower() for e in all_emails]:
        raise HTTPException(status_code=403, detail="Access denied")

    viewer_role = "seller" if email_lower in [e.lower() for e in (portal.seller_emails or [])] else "buyer"

    db.add(PortalView(portal_id=portal.id, email=email_lower, section="overview"))
    db.commit()

    deal = db.query(Deal).filter(Deal.id == portal.deal_id).first()
    prop = db.query(Property).filter(Property.id == deal.property_id).first() if deal else None
    docs = (
        db.query(Document).filter(Document.deal_id == deal.id).all()
        if deal and portal.show_docs else []
    )

    return {
        "token":         portal.token,
        "deal_id":       portal.deal_id,
        "pov":           portal.pov,
        "challenges":    portal.challenges,
        "mutual_steps":  portal.mutual_steps,
        "show_timeline": portal.show_timeline,
        "show_docs":     portal.show_docs,
        "show_comps":    portal.show_comps,
        "show_offers":   portal.show_offers,
        "viewer_role":   viewer_role,
        "viewer_email":  email_lower,
        "deal": {
            "name":            deal.name,
            "deal_type":       deal.deal_type,
            "stage":           deal.stage,
            "projected_close": str(deal.projected_close) if deal.projected_close else None,
        } if deal else None,
        "property": {
            "address":       prop.address,
            "city":          prop.city,
            "state":         prop.state,
            "property_type": prop.property_type,
            "sf_rentable":   prop.sf_rentable,
        } if prop else None,
        "documents": [
            {"id": d.id, "name": d.name, "doc_type": d.doc_type, "file_url": d.file_url}
            for d in docs
        ],
    }


@router.post("/token/{token}/view")
def log_section_view(token: str, email: str, section: str, db: Session = Depends(get_db)):
    portal = db.query(Portal).filter(Portal.token == token).first()
    if not portal:
        raise HTTPException(status_code=404, detail="Portal not found")
    all_emails = [e.lower() for e in (portal.seller_emails or []) + (portal.buyer_emails or [])]
    if email.lower() not in all_emails:
        raise HTTPException(status_code=403, detail="Access denied")
    db.add(PortalView(portal_id=portal.id, email=email.lower(), section=section))
    db.commit()
    return {"logged": True}

@router.get("/{deal_id}/views")
def portal_views(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    portal = db.query(Portal).filter(Portal.deal_id == deal_id).first()
    if not portal:
        raise HTTPException(status_code=404, detail="No portal for this deal")
    return db.query(PortalView).filter(PortalView.portal_id == portal.id).order_by(PortalView.viewed_at.desc()).all()
