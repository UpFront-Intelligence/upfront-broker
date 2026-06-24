"""Regrid county-CSV reconciler — see CLAUDE.md's PARCELS_REGRID section
for the table design, decision thresholds, and synthetic-data caveats.

POST /api/regrid/ingest                          — multipart CSV + county, UPSERT into parcels_regrid
POST /api/regrid/reconcile                        — owner-scoped fuzzy match against accounts/properties
POST /api/regrid/suggestions/{id}/confirm         — apply a regrid_owner_match suggestion's candidate
POST /api/regrid/suggestions/{id}/create-account  — create a fresh account from the parcel instead
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from database import get_db
from models.user import User
from models.suggestion import Suggestion
from auth_utils import get_current_user
from services import regrid as regrid_service

router = APIRouter()


class ReconcileRequest(BaseModel):
    county: Optional[str] = None
    auto_create_accounts: bool = False


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    county: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Streams the upload row-by-row (file.file, not file.read()) so a
    multi-hundred-MB county CSV never has to fit entirely in memory."""
    result = regrid_service.ingest_csv(db, county, file.file)
    return result


@router.post("/reconcile")
def reconcile(
    data: ReconcileRequest = ReconcileRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return regrid_service.reconcile(
        db, current_user.id, county=data.county, auto_create_accounts=data.auto_create_accounts)


def _load_regrid_suggestion(db: Session, suggestion_id: int, current_user: User) -> Suggestion:
    s = db.query(Suggestion).filter(
        Suggestion.id == suggestion_id, Suggestion.owner_id == current_user.id).first()
    if not s:
        raise HTTPException(404, "Suggestion not found")
    if s.suggestion_type != "regrid_owner_match":
        raise HTTPException(400, "Not a Regrid owner-match suggestion")
    if s.status != "new":
        raise HTTPException(400, f"Suggestion already resolved (status={s.status})")
    return s


@router.post("/suggestions/{suggestion_id}/confirm")
def confirm_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = _load_regrid_suggestion(db, suggestion_id, current_user)
    try:
        return regrid_service.confirm_suggestion(db, current_user.id, s)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/suggestions/{suggestion_id}/create-account")
def create_account_from_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    s = _load_regrid_suggestion(db, suggestion_id, current_user)
    try:
        return regrid_service.create_account_from_suggestion(db, current_user.id, s)
    except ValueError as e:
        raise HTTPException(400, str(e))
