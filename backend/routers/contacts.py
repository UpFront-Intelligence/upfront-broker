from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models.contact import Contact
from models.contact_account import ContactAccount
from models.account import Account
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

class ContactCreate(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    title: Optional[str] = None
    photo_url: Optional[str] = None
    linkedin: Optional[str] = None
    contact_type: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = []
    notes: Optional[str] = None

class ContactUpdate(ContactCreate):
    first_name: Optional[str] = None
    last_name: Optional[str] = None

class AccountLinkResponse(BaseModel):
    id: int
    name: str
    entity_type: Optional[str]
    city: Optional[str]
    state: Optional[str]
    role: Optional[str]
    is_primary: bool

class ContactResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str]
    phone: Optional[str]
    mobile: Optional[str]
    title: Optional[str]
    photo_url: Optional[str]
    linkedin: Optional[str]
    contact_type: Optional[str]
    source: Optional[str]
    tags: Optional[List[str]]
    notes: Optional[str]

    class Config:
        from_attributes = True

@router.get("/", response_model=List[ContactResponse])
def list_contacts(
    search: Optional[str] = None,
    contact_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Contact).filter(Contact.owner_id == current_user.id)
    if search:
        q = q.filter(
            (Contact.first_name.ilike(f"%{search}%")) |
            (Contact.last_name.ilike(f"%{search}%")) |
            (Contact.email.ilike(f"%{search}%")) |
            (Contact.company.ilike(f"%{search}%") if hasattr(Contact, 'company') else False)
        )
    if contact_type:
        q = q.filter(Contact.contact_type == contact_type)
    return q.order_by(Contact.last_name).all()

@router.post("/", response_model=ContactResponse)
def create_contact(
    data: ContactCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = Contact(**data.dict(), owner_id=current_user.id)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact

@router.get("/{contact_id}", response_model=ContactResponse)
def get_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.owner_id == current_user.id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact

@router.put("/{contact_id}", response_model=ContactResponse)
def update_contact(
    contact_id: int,
    data: ContactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.owner_id == current_user.id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    for key, val in data.dict(exclude_unset=True).items():
        setattr(contact, key, val)
    db.commit()
    db.refresh(contact)
    return contact

@router.get("/{contact_id}/accounts", response_model=List[AccountLinkResponse])
def get_contact_accounts(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.owner_id == current_user.id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    rows = (
        db.query(ContactAccount, Account)
        .join(Account, ContactAccount.account_id == Account.id)
        .filter(ContactAccount.contact_id == contact_id,
                Account.owner_id == current_user.id)
        .all()
    )
    return [
        AccountLinkResponse(
            id=acct.id, name=acct.name, entity_type=acct.entity_type,
            city=acct.city, state=acct.state,
            role=link.role, is_primary=bool(link.is_primary),
        )
        for link, acct in rows
    ]


@router.delete("/{contact_id}")
def delete_contact(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = db.query(Contact).filter(
        Contact.id == contact_id,
        Contact.owner_id == current_user.id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    return {"deleted": True}


@router.get("/{contact_id}/full")
def get_contact_full(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.deal import Deal, DealContact
    from models.shared import Activity, Document
    c = db.query(Contact).filter(
        Contact.id == contact_id, Contact.owner_id == current_user.id
    ).first()
    if not c:
        raise HTTPException(404, "Contact not found")

    accounts = []
    for ca, a in (db.query(ContactAccount, Account)
                    .join(Account, ContactAccount.account_id == Account.id)
                    .filter(ContactAccount.contact_id == contact_id,
                            Account.owner_id == current_user.id).all()):
        accounts.append({"id": a.id, "name": a.name, "entity_type": a.entity_type,
                          "role": ca.role, "is_primary": ca.is_primary})

    deal_ids = [r.deal_id for r in db.query(DealContact.deal_id)
                .filter(DealContact.contact_id == contact_id).all()]
    deals = [{"id": d.id, "name": d.name, "stage": d.stage, "deal_type": d.deal_type,
               "our_commission": d.our_commission}
             for d in db.query(Deal).filter(Deal.id.in_(deal_ids),
                                            Deal.owner_id == current_user.id).all()]

    acts = db.query(Activity).filter(Activity.contact_id == contact_id,
                                     Activity.owner_id == current_user.id
                                     ).order_by(Activity.activity_date.desc()).limit(20).all()
    docs = db.query(Document).filter(Document.contact_id == contact_id,
                                     Document.owner_id == current_user.id).all()

    c_dict = ContactResponse.model_validate(c).model_dump()
    return {
        "contact":    c_dict,
        "accounts":   accounts,
        "deals":      deals,
        "activities": [{"id": a.id, "activity_type": a.activity_type, "subject": a.subject,
                        "notes": a.notes,
                        "activity_date": str(a.activity_date) if a.activity_date else None,
                        "created_at": str(a.created_at)} for a in acts],
        "documents":  [{"id": d.id, "name": d.name, "doc_type": d.doc_type,
                        "file_url": d.file_url} for d in docs],
    }
