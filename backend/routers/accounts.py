from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models.account import Account
from models.contact_account import ContactAccount
from models.contact import Contact
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

class AccountCreate(BaseModel):
    name: str
    entity_type: Optional[str] = None
    ein: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    notes: Optional[str] = None

class AccountUpdate(AccountCreate):
    name: Optional[str] = None

class ContactLinkResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str]
    phone: Optional[str]
    title: Optional[str]
    contact_type: Optional[str]
    role: Optional[str]
    is_primary: bool

class AccountResponse(BaseModel):
    id: int
    name: str
    entity_type: Optional[str]
    ein: Optional[str]
    website: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True

@router.get("/", response_model=List[AccountResponse])
def list_accounts(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Account).filter(Account.owner_id == current_user.id)
    if search:
        q = q.filter(Account.name.ilike(f"%{search}%"))
    return q.order_by(Account.name).all()

@router.post("/", response_model=AccountResponse)
def create_account(
    data: AccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = Account(**data.dict(), owner_id=current_user.id)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account

@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.owner_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account

@router.put("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int,
    data: AccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.owner_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    for key, val in data.dict(exclude_unset=True).items():
        setattr(account, key, val)
    db.commit()
    db.refresh(account)
    return account

@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.owner_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"deleted": True}

@router.get("/{account_id}/contacts", response_model=List[ContactLinkResponse])
def get_account_contacts(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    account = db.query(Account).filter(
        Account.id == account_id,
        Account.owner_id == current_user.id
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    rows = (
        db.query(ContactAccount, Contact)
        .join(Contact, ContactAccount.contact_id == Contact.id)
        .filter(ContactAccount.account_id == account_id,
                Contact.owner_id == current_user.id)
        .all()
    )
    return [
        ContactLinkResponse(
            id=c.id, first_name=c.first_name, last_name=c.last_name,
            email=c.email, phone=c.phone, title=c.title,
            contact_type=c.contact_type,
            role=link.role, is_primary=bool(link.is_primary),
        )
        for link, c in rows
    ]


@router.post("/{account_id}/contacts")
def link_contact(
    account_id: int,
    contact_id: int,
    role: str = "Owner",
    is_primary: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    link = ContactAccount(
        account_id=account_id,
        contact_id=contact_id,
        role=role,
        is_primary=is_primary
    )
    db.add(link)
    db.commit()
    return {"linked": True}
