from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models.contact import Contact
from models.contact_phone import ContactPhone
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
    tenant_id: Optional[int] = None

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
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None

    class Config:
        from_attributes = True


class ContactPhoneCreate(BaseModel):
    label: Optional[str] = None
    number: str
    is_primary: Optional[bool] = False

class ContactPhoneUpdate(BaseModel):
    label: Optional[str] = None
    number: Optional[str] = None
    is_primary: Optional[bool] = None

class ContactPhoneResponse(BaseModel):
    id: int
    label: Optional[str]
    number: str
    is_primary: bool

    class Config:
        from_attributes = True


def _get_owned_contact(contact_id: int, db: Session, current_user: User) -> Contact:
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.owner_id == current_user.id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


def _resync_legacy_phone(db, contact, contact_id, current_user):
    """Mirror the contact's primary phone into contacts.phone for legacy reads."""
    primary = db.query(ContactPhone).filter(
        ContactPhone.contact_id == contact_id,
        ContactPhone.owner_id == current_user.id,
        ContactPhone.is_primary.is_(True)
    ).first()
    contact.phone = primary.number if primary else None


def _load_tenant_names(contacts, db) -> dict:
    """Batch-load tenant names for a list of Contact ORM objects."""
    ids = {c.tenant_id for c in contacts if c.tenant_id}
    if not ids:
        return {}
    from models.tenant import Tenant
    rows = db.query(Tenant.id, Tenant.name).filter(Tenant.id.in_(ids)).all()
    return {r.id: r.name for r in rows}


def _serialize_contact(c: Contact, tenant_names: dict = None) -> dict:
    return {
        "id": c.id, "first_name": c.first_name, "last_name": c.last_name,
        "email": c.email, "phone": c.phone, "mobile": c.mobile,
        "title": c.title, "photo_url": c.photo_url, "linkedin": c.linkedin,
        "contact_type": c.contact_type, "source": c.source,
        "tags": c.tags or [], "notes": c.notes,
        "tenant_id": c.tenant_id,
        "tenant_name": (tenant_names or {}).get(c.tenant_id) if c.tenant_id else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }

@router.get("/")
def list_contacts(
    search:       Optional[str] = None,
    contact_type: Optional[str] = None,   # comma-separated
    source:       Optional[str] = None,
    has_email:    Optional[bool] = None,
    has_phone:    Optional[bool] = None,
    has_account:  Optional[bool] = None,
    has_deal:     Optional[bool] = None,
    page:         Optional[int] = None,
    per_page:     int = 50,
    sort_by:      str = "last_name",
    sort_dir:     str = "asc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from models.deal import DealContact
    q = db.query(Contact).filter(Contact.owner_id == current_user.id)
    if search:
        q = q.filter((Contact.first_name.ilike(f"%{search}%")) |
                     (Contact.last_name.ilike(f"%{search}%")) |
                     (Contact.email.ilike(f"%{search}%")) |
                     (Contact.phone.ilike(f"%{search}%")))
    if contact_type:
        types = [t.strip() for t in contact_type.split(",") if t.strip()]
        if types: q = q.filter(Contact.contact_type.in_(types))
    if source:  q = q.filter(Contact.source.ilike(f"%{source}%"))
    if has_email is True:  q = q.filter(Contact.email.isnot(None))
    if has_email is False: q = q.filter(Contact.email.is_(None))
    if has_phone is True:  q = q.filter((Contact.phone.isnot(None)) | (Contact.mobile.isnot(None)))
    if has_phone is False: q = q.filter(Contact.phone.is_(None), Contact.mobile.is_(None))
    if has_account is not None:
        acct_cids = db.query(ContactAccount.contact_id)
        if has_account: q = q.filter(Contact.id.in_(acct_cids))
        else:           q = q.filter(Contact.id.notin_(acct_cids))
    if has_deal is not None:
        deal_cids = db.query(DealContact.contact_id).filter(DealContact.contact_id.isnot(None))
        if has_deal: q = q.filter(Contact.id.in_(deal_cids))
        else:        q = q.filter(Contact.id.notin_(deal_cids))

    sort_map = {"last_name": Contact.last_name, "first_name": Contact.first_name,
                "email": Contact.email, "created_at": Contact.created_at}
    col = sort_map.get(sort_by, Contact.last_name)
    q = q.order_by(col.desc() if sort_dir == "desc" else col.asc())

    if page is None:
        all_c = q.all()
        tnames = _load_tenant_names(all_c, db)
        return [_serialize_contact(c, tnames) for c in all_c]
    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    tnames = _load_tenant_names(items, db)
    return {"items": [_serialize_contact(c, tnames) for c in items],
            "total": total, "page": page,
            "per_page": per_page, "total_pages": max(1, (total + per_page - 1) // per_page)}

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


@router.get("/{contact_id}/phones", response_model=List[ContactPhoneResponse])
def list_contact_phones(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_owned_contact(contact_id, db, current_user)
    return (
        db.query(ContactPhone)
        .filter(ContactPhone.contact_id == contact_id, ContactPhone.owner_id == current_user.id)
        .order_by(ContactPhone.is_primary.desc(), ContactPhone.id.asc())
        .all()
    )


@router.post("/{contact_id}/phones", response_model=ContactPhoneResponse)
def create_contact_phone(
    contact_id: int,
    data: ContactPhoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = _get_owned_contact(contact_id, db, current_user)
    phone = ContactPhone(
        owner_id=current_user.id,
        contact_id=contact_id,
        label=data.label,
        number=data.number,
        is_primary=bool(data.is_primary),
    )
    db.add(phone)
    if phone.is_primary:
        db.flush()
        db.query(ContactPhone).filter(
            ContactPhone.contact_id == contact_id,
            ContactPhone.owner_id == current_user.id,
            ContactPhone.id != phone.id
        ).update({"is_primary": False})
        _resync_legacy_phone(db, contact, contact_id, current_user)
    db.commit()
    db.refresh(phone)
    return phone


@router.put("/{contact_id}/phones/{phone_id}", response_model=ContactPhoneResponse)
def update_contact_phone(
    contact_id: int,
    phone_id: int,
    data: ContactPhoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = _get_owned_contact(contact_id, db, current_user)
    phone = db.query(ContactPhone).filter(
        ContactPhone.id == phone_id,
        ContactPhone.contact_id == contact_id,
        ContactPhone.owner_id == current_user.id
    ).first()
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")

    fields = data.dict(exclude_unset=True)
    for key, val in fields.items():
        setattr(phone, key, val)

    if phone.is_primary:
        db.query(ContactPhone).filter(
            ContactPhone.contact_id == contact_id,
            ContactPhone.owner_id == current_user.id,
            ContactPhone.id != phone_id
        ).update({"is_primary": False})

    db.flush()
    if 'is_primary' in fields or 'number' in fields:
        _resync_legacy_phone(db, contact, contact_id, current_user)
    db.commit()
    db.refresh(phone)
    return phone


@router.delete("/{contact_id}/phones/{phone_id}")
def delete_contact_phone(
    contact_id: int,
    phone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    contact = _get_owned_contact(contact_id, db, current_user)
    phone = db.query(ContactPhone).filter(
        ContactPhone.id == phone_id,
        ContactPhone.contact_id == contact_id,
        ContactPhone.owner_id == current_user.id
    ).first()
    if not phone:
        raise HTTPException(status_code=404, detail="Phone not found")

    was_primary = phone.is_primary
    db.delete(phone)
    db.flush()
    if was_primary:
        _resync_legacy_phone(db, contact, contact_id, current_user)
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

    phones = (
        db.query(ContactPhone)
        .filter(ContactPhone.contact_id == contact_id, ContactPhone.owner_id == current_user.id)
        .order_by(ContactPhone.is_primary.desc(), ContactPhone.id.asc())
        .all()
    )

    c_dict = ContactResponse.model_validate(c).model_dump()
    if c.tenant_id:
        from models.tenant import Tenant
        t_row = db.query(Tenant.id, Tenant.name).filter(Tenant.id == c.tenant_id).first()
        if t_row:
            c_dict['tenant_name'] = t_row.name
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
        "phones":     [{"id": p.id, "label": p.label, "number": p.number,
                        "is_primary": p.is_primary} for p in phones],
    }
