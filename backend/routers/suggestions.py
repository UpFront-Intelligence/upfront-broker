"""
General "hint" substrate (lightbulb-icon pattern) — owner-scoped, generic
across suggestion_type. account_duplicate is the first producer (see
routers/accounts.py POST /scan-duplicates); regrid_owner_match is the
second (see routers/regrid.py POST /reconcile) — both read/write this
same table. dismiss() has a small suggestion_type-specific side effect
for regrid_owner_match (see below); confirm/create-account for that type
live in routers/regrid.py instead since they're materially different
business logic, not a fit for this generic router.

GET  /api/suggestions             — list, filterable by status/type
POST /api/suggestions/{id}/dismiss
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models.suggestion import Suggestion
from models.user import User
from auth_utils import get_current_user

router = APIRouter()


@router.get("/")
def list_suggestions(
    status: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Suggestion).filter(Suggestion.owner_id == current_user.id)
    if status:
        q = q.filter(Suggestion.status == status)
    if suggestion_type:
        q = q.filter(Suggestion.suggestion_type == suggestion_type)
    rows = q.order_by(Suggestion.score.desc()).all()
    return [{
        "id": s.id, "suggestion_type": s.suggestion_type,
        "entity_id_a": s.entity_id_a, "entity_id_b": s.entity_id_b,
        "score": float(s.score), "reasoning": s.reasoning, "evidence": s.evidence,
        "status": s.status, "created_at": s.created_at, "resolved_at": s.resolved_at,
    } for s in rows]


@router.post("/{suggestion_id}/dismiss")
def dismiss_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = db.query(Suggestion).filter(
        Suggestion.id == suggestion_id, Suggestion.owner_id == current_user.id).first()
    if not s:
        raise HTTPException(404, "Suggestion not found")
    s.status = "dismissed"
    s.resolved_at = datetime.now(timezone.utc)

    # regrid_owner_match is the one producer so far whose suggestion maps
    # back to a row in another table that itself tracks resolution state
    # (parcels_regrid.reconciliation_status) — flip it to no_match so a
    # future reconcile() call doesn't see it as still 'suggested' forever.
    if s.suggestion_type == "regrid_owner_match":
        from models.parcel_regrid import ParcelRegrid
        parcel_id = (s.evidence or {}).get("parcel_regrid_id")
        if parcel_id:
            parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == parcel_id).first()
            if parcel:
                parcel.reconciliation_status = "no_match"

    db.commit()
    return {"id": s.id, "status": s.status}
