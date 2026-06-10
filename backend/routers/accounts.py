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

@router.get("/")
def list_accounts(
    search:         Optional[str] = None,
    entity_type:    Optional[str] = None,   # comma-separated
    city:           Optional[str] = None,
    state:          Optional[str] = None,
    has_properties: Optional[bool] = None,
    has_deal:       Optional[bool] = None,
    page:           Optional[int] = None,
    per_page:       int = 50,
    sort_by:        str = "name",
    sort_dir:       str = "asc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.property import Property
    from models.deal import DealContact
    q = db.query(Account).filter(Account.owner_id == current_user.id)
    if search:  q = q.filter(Account.name.ilike(f"%{search}%"))
    if entity_type:
        types = [t.strip() for t in entity_type.split(",") if t.strip()]
        if types: q = q.filter(Account.entity_type.in_(types))
    if city:    q = q.filter(Account.city.ilike(f"%{city}%"))
    if state:   q = q.filter(Account.state.ilike(state))
    if has_properties is not None:
        prop_aids = db.query(Property.account_id).filter(
            Property.account_id.isnot(None), Property.owner_id == current_user.id)
        if has_properties: q = q.filter(Account.id.in_(prop_aids))
        else:              q = q.filter(Account.id.notin_(prop_aids))
    if has_deal is not None:
        deal_aids = db.query(DealContact.account_id).filter(DealContact.account_id.isnot(None))
        if has_deal: q = q.filter(Account.id.in_(deal_aids))
        else:        q = q.filter(Account.id.notin_(deal_aids))

    sort_map = {"name": Account.name, "entity_type": Account.entity_type,
                "city": Account.city, "created_at": Account.created_at}
    col = sort_map.get(sort_by, Account.name)
    q = q.order_by(col.desc() if sort_dir == "desc" else col.asc())

    if page is None:
        return q.all()
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    return {"items": items, "total": total, "page": page,
            "per_page": per_page, "total_pages": max(1, (total + per_page - 1) // per_page)}

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

@router.get("/search")
def search_accounts(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight typeahead — owner-scoped name search."""
    q = q.strip()
    if len(q) < 2:
        return []
    rows = (db.query(Account.id, Account.name)
              .filter(Account.owner_id == current_user.id, Account.name.ilike(f"%{q}%"))
              .order_by(Account.name)
              .limit(8)
              .all())
    return [{"id": r.id, "name": r.name} for r in rows]


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


@router.get("/{account_id}/full")
def get_account_full(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.property import Property
    from models.deal import Deal, DealContact
    from models.shared import Activity
    a = db.query(Account).filter(
        Account.id == account_id, Account.owner_id == current_user.id
    ).first()
    if not a:
        raise HTTPException(404, "Account not found")

    contacts = []
    for ca, c in (db.query(ContactAccount, Contact)
                    .join(Contact, ContactAccount.contact_id == Contact.id)
                    .filter(ContactAccount.account_id == account_id,
                            Contact.owner_id == current_user.id).all()):
        contacts.append({"id": c.id, "first_name": c.first_name, "last_name": c.last_name,
                          "title": c.title, "email": c.email,
                          "role": ca.role, "is_primary": ca.is_primary})

    props = [{"id": p.id, "name": p.name, "address": p.address, "city": p.city,
               "state": p.state, "property_type": p.property_type, "status": p.status}
             for p in db.query(Property).filter(Property.account_id == account_id,
                                                Property.owner_id == current_user.id).all()]

    deal_ids = [r.deal_id for r in db.query(DealContact.deal_id)
                .filter(DealContact.account_id == account_id).all()]
    deals = [{"id": d.id, "name": d.name, "stage": d.stage, "deal_type": d.deal_type,
               "our_commission": d.our_commission}
             for d in db.query(Deal).filter(Deal.id.in_(deal_ids),
                                            Deal.owner_id == current_user.id).all()]

    a_dict = AccountResponse.model_validate(a).model_dump()
    return {
        "account":    a_dict,
        "contacts":   contacts,
        "properties": props,
        "deals":      deals,
    }
