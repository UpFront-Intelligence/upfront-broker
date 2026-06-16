from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from database import get_db
from models.marketing_list import MarketingList, MarketingListMember
from models.account import Account
from models.contact import Contact
from models.user import User
from auth_utils import get_current_user

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────

class ListCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ListUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class MemberAdd(BaseModel):
    account_id: Optional[int] = None
    contact_id: Optional[int] = None
    source: Optional[str] = "manual"
    note: Optional[str] = None

class BulkAdd(BaseModel):
    account_ids: Optional[list[int]] = []
    contact_ids: Optional[list[int]] = []
    source: Optional[str] = "manual"


# ── Owner-isolation helpers ───────────────────────────────────────

def _get_list(db: Session, list_id: int, owner_id: int) -> MarketingList:
    ml = db.query(MarketingList).filter(
        MarketingList.id == list_id,
        MarketingList.owner_id == owner_id,
    ).first()
    if not ml:
        raise HTTPException(status_code=404, detail="Marketing list not found")
    return ml


def _validate_entity(db: Session, account_id, contact_id, owner_id):
    """Exactly one entity, and it must belong to this owner."""
    if (account_id is None) == (contact_id is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one of account_id or contact_id",
        )
    if account_id is not None:
        acct = db.query(Account).filter(
            Account.id == account_id, Account.owner_id == owner_id
        ).first()
        if not acct:
            raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    if contact_id is not None:
        ct = db.query(Contact).filter(
            Contact.id == contact_id, Contact.owner_id == owner_id
        ).first()
        if not ct:
            raise HTTPException(status_code=404, detail=f"Contact {contact_id} not found")


def _member_display(m: MarketingListMember) -> dict:
    if m.account_id and m.account:
        return {
            "id": m.id,
            "type": "account",
            "entity_id": m.account_id,
            "display_name": m.account.name,
            "note": m.note,
            "source": m.source,
            "added_at": m.added_at,
        }
    if m.contact_id and m.contact:
        c = m.contact
        name = f"{c.first_name or ''} {c.last_name or ''}".strip() or c.email or f"Contact #{c.id}"
        return {
            "id": m.id,
            "type": "contact",
            "entity_id": m.contact_id,
            "display_name": name,
            "note": m.note,
            "source": m.source,
            "added_at": m.added_at,
        }
    return {"id": m.id, "type": "unknown", "entity_id": None, "display_name": "—",
            "note": m.note, "source": m.source, "added_at": m.added_at}


# ── Routes ────────────────────────────────────────────────────────

@router.get("/")
def list_marketing_lists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(
            MarketingList,
            func.count(MarketingListMember.id).label("member_count"),
        )
        .outerjoin(MarketingListMember, MarketingListMember.list_id == MarketingList.id)
        .filter(MarketingList.owner_id == current_user.id)
        .group_by(MarketingList.id)
        .order_by(MarketingList.created_at.desc())
        .all()
    )
    return [
        {
            "id": ml.id,
            "name": ml.name,
            "description": ml.description,
            "member_count": count,
            "created_at": ml.created_at,
            "updated_at": ml.updated_at,
        }
        for ml, count in rows
    ]


@router.post("/", status_code=201)
def create_marketing_list(
    data: ListCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(MarketingList).filter(
        MarketingList.owner_id == current_user.id,
        MarketingList.name == data.name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A list named '{data.name}' already exists")

    ml = MarketingList(
        owner_id=current_user.id,
        name=data.name,
        description=data.description,
    )
    db.add(ml)
    db.commit()
    db.refresh(ml)
    return {"id": ml.id, "name": ml.name, "description": ml.description,
            "member_count": 0, "created_at": ml.created_at, "updated_at": ml.updated_at}


@router.get("/{list_id}")
def get_marketing_list(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ml = _get_list(db, list_id, current_user.id)
    members = (
        db.query(MarketingListMember)
        .filter(MarketingListMember.list_id == list_id)
        .order_by(MarketingListMember.added_at.desc())
        .all()
    )
    return {
        "id": ml.id,
        "name": ml.name,
        "description": ml.description,
        "created_at": ml.created_at,
        "updated_at": ml.updated_at,
        "members": [_member_display(m) for m in members],
    }


@router.patch("/{list_id}")
def update_marketing_list(
    list_id: int,
    data: ListUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ml = _get_list(db, list_id, current_user.id)
    updates = data.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] != ml.name:
        conflict = db.query(MarketingList).filter(
            MarketingList.owner_id == current_user.id,
            MarketingList.name == updates["name"],
            MarketingList.id != list_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"A list named '{updates['name']}' already exists")
    for k, v in updates.items():
        setattr(ml, k, v)
    ml.updated_at = func.now()
    db.commit()
    db.refresh(ml)
    return {"id": ml.id, "name": ml.name, "description": ml.description,
            "created_at": ml.created_at, "updated_at": ml.updated_at}


@router.delete("/{list_id}", status_code=204)
def delete_marketing_list(
    list_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ml = _get_list(db, list_id, current_user.id)
    db.delete(ml)
    db.commit()


@router.post("/{list_id}/members", status_code=201)
def add_member(
    list_id: int,
    data: MemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_list(db, list_id, current_user.id)
    _validate_entity(db, data.account_id, data.contact_id, current_user.id)

    # Duplicate-safe: return existing member rather than erroring
    existing = db.query(MarketingListMember).filter(
        MarketingListMember.list_id == list_id,
        MarketingListMember.account_id == data.account_id,
        MarketingListMember.contact_id == data.contact_id,
    ).first()
    if existing:
        return {**_member_display(existing), "already_existed": True}

    m = MarketingListMember(
        list_id=list_id,
        account_id=data.account_id,
        contact_id=data.contact_id,
        source=data.source or "manual",
        note=data.note,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {**_member_display(m), "already_existed": False}


@router.post("/{list_id}/members/bulk")
def bulk_add_members(
    list_id: int,
    data: BulkAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_list(db, list_id, current_user.id)
    source = data.source or "manual"
    added = 0
    skipped = 0

    for acct_id in (data.account_ids or []):
        # Owner-isolation check
        acct = db.query(Account).filter(
            Account.id == acct_id, Account.owner_id == current_user.id
        ).first()
        if not acct:
            skipped += 1
            continue
        dup = db.query(MarketingListMember).filter(
            MarketingListMember.list_id == list_id,
            MarketingListMember.account_id == acct_id,
        ).first()
        if dup:
            skipped += 1
            continue
        db.add(MarketingListMember(list_id=list_id, account_id=acct_id, source=source))
        added += 1

    for ct_id in (data.contact_ids or []):
        ct = db.query(Contact).filter(
            Contact.id == ct_id, Contact.owner_id == current_user.id
        ).first()
        if not ct:
            skipped += 1
            continue
        dup = db.query(MarketingListMember).filter(
            MarketingListMember.list_id == list_id,
            MarketingListMember.contact_id == ct_id,
        ).first()
        if dup:
            skipped += 1
            continue
        db.add(MarketingListMember(list_id=list_id, contact_id=ct_id, source=source))
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped}


@router.delete("/{list_id}/members/{member_id}", status_code=204)
def remove_member(
    list_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Owner-scope: verify via the list
    _get_list(db, list_id, current_user.id)
    m = db.query(MarketingListMember).filter(
        MarketingListMember.id == member_id,
        MarketingListMember.list_id == list_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(m)
    db.commit()
