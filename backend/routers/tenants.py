from typing import Optional
from datetime import date as DateType

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.tenant import Tenant
from models.user import User
from auth_utils import get_current_user

router = APIRouter()


def _resp(t: Tenant) -> dict:
    return {
        "id":              t.id,
        "property_id":     t.property_id,
        "tenant_name":     t.tenant_name,
        "sf":              t.sf,
        "pct_of_building": t.pct_of_building,
        "lease_expiry":    t.lease_expiry.isoformat() if t.lease_expiry else None,
        "is_available":    t.is_available,
        "notes":           t.notes,
        "owner_id":        t.owner_id,
    }


class TenantCreate(BaseModel):
    property_id:     int
    tenant_name:     str
    sf:              Optional[int]       = None
    pct_of_building: Optional[float]    = None
    lease_expiry:    Optional[DateType] = None
    is_available:    bool               = False
    notes:           Optional[str]      = None


class TenantUpdate(BaseModel):
    tenant_name:     Optional[str]      = None
    sf:              Optional[int]      = None
    pct_of_building: Optional[float]   = None
    lease_expiry:    Optional[DateType] = None
    is_available:    Optional[bool]     = None
    notes:           Optional[str]      = None


@router.get("/")
def list_tenants(
    property_id:  Optional[int] = Query(None),
    tenant_name:  Optional[str] = Query(None),
    db:           Session       = Depends(get_db),
    current_user: User          = Depends(get_current_user),
):
    q = db.query(Tenant).filter(Tenant.owner_id == current_user.id)
    if property_id:
        q = q.filter(Tenant.property_id == property_id)
    if tenant_name:
        q = q.filter(Tenant.tenant_name.ilike(f"%{tenant_name}%"))
    return [_resp(t) for t in q.order_by(Tenant.tenant_name).all()]


@router.post("/", status_code=201)
def create_tenant(
    body:         TenantCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    t = Tenant(**body.model_dump(), owner_id=current_user.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    return _resp(t)


@router.put("/{tenant_id}")
def update_tenant(
    tenant_id:    int,
    body:         TenantUpdate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    t = db.query(Tenant).filter(
        Tenant.id == tenant_id, Tenant.owner_id == current_user.id
    ).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return _resp(t)


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
        raise HTTPException(status_code=404, detail="Tenant not found")
    db.delete(t)
    db.commit()
    return {"ok": True}
