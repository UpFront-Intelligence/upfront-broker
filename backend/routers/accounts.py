from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from rapidfuzz import fuzz
from database import get_db
from models.account import Account
from models.contact_account import ContactAccount
from models.contact import Contact
from models.user import User
from auth_utils import get_current_user
from services.accounts import owned_accounts_query, geocode_account_if_address_changed
from services.naming import normalize_name

router = APIRouter()

DUPLICATE_SCAN_THRESHOLD = 65

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
    lat: Optional[float]
    lng: Optional[float]
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
    q = owned_accounts_query(db, current_user.id)
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
    db.flush()
    geocode_account_if_address_changed(db, account, current_user.id)
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
    rows = (owned_accounts_query(db, current_user.id)
              .filter(Account.name.ilike(f"%{q}%"))
              .with_entities(Account.id, Account.name)
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
    old_addr_key = (account.address, account.city, account.state)
    for key, val in data.dict(exclude_unset=True).items():
        setattr(account, key, val)
    if (account.address, account.city, account.state) != old_addr_key:
        geocode_account_if_address_changed(db, account, current_user.id)
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
    from models.property_party import PropertyParty
    from models.deal import Deal, DealContact
    from models.shared import Activity
    from models.account_role import AccountRole
    from models.engagement import Engagement
    a = db.query(Account).filter(
        Account.id == account_id, Account.owner_id == current_user.id
    ).first()
    if not a:
        raise HTTPException(404, "Account not found")

    from routers.query import _linked_properties_for_account
    property_parties_count = db.query(PropertyParty).filter(
        PropertyParty.account_id == account_id).count()
    linked_properties = _linked_properties_for_account(db, current_user.id, account_id)

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

    role_rows = {r.slug: r for r in db.query(AccountRole)
                  .filter(AccountRole.slug.in_(a.roles or [])).all()}
    roles_resolved = [
        {"slug": slug, "display_name": role_rows[slug].display_name, "category": role_rows[slug].category}
        for slug in (a.roles or []) if slug in role_rows
    ]

    owned_properties = [{"id": p.id, "name": p.name, "address": p.address}
        for p in db.query(Property).filter(Property.recorded_owner_account_id == account_id,
                                           Property.owner_id == current_user.id).all()]

    managed_properties = [{"id": p.id, "name": p.name, "address": p.address}
        for p in db.query(Property).filter(Property.manager_account_id == account_id,
                                           Property.owner_id == current_user.id).all()]

    engagements = [{"id": e.id, "name": e.name, "type": e.type, "stage": e.stage}
        for e in db.query(Engagement).filter(Engagement.client_account_id == account_id,
                                             Engagement.owner_id == current_user.id).all()]

    a_dict = AccountResponse.model_validate(a).model_dump()
    return {
        "account":    a_dict,
        "contacts":   contacts,
        "properties": props,
        "deals":      deals,
        "roles_resolved":      roles_resolved,
        "owned_properties":    owned_properties,
        "managed_properties":  managed_properties,
        "engagements":         engagements,
        "property_parties_count": property_parties_count,
        "linked_properties":   linked_properties,
    }


# ── Duplicate scanner + merge ─────────────────────────────────────────────────

class MergeRequest(BaseModel):
    survivor_id: int
    duplicate_id: int


@router.post("/scan-duplicates")
def scan_duplicates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pairwise rapidfuzz comparison over this owner's (non-merged) accounts.

    O(n^2) — fine at current sandbox scale. Will need blocking (e.g.
    first-letter or soundex bucketing of normalized_name) before this
    scales past a few thousand accounts. Not built now — out of scope
    for this pass.
    """
    from models.suggestion import Suggestion

    accounts = owned_accounts_query(db, current_user.id).all()
    for acct in accounts:
        if not acct.normalized_name:
            acct.normalized_name = normalize_name(acct.name)

    seen_pairs = {
        (s.entity_id_a, s.entity_id_b)
        for s in db.query(Suggestion.entity_id_a, Suggestion.entity_id_b).filter(
            Suggestion.owner_id == current_user.id,
            Suggestion.suggestion_type == "account_duplicate").all()
    }

    pairs_found, created = 0, 0
    for i in range(len(accounts)):
        for j in range(i + 1, len(accounts)):
            a, b = accounts[i], accounts[j]
            score = fuzz.token_sort_ratio(a.normalized_name or "", b.normalized_name or "")
            if score < DUPLICATE_SCAN_THRESHOLD:
                continue
            pairs_found += 1
            id_a, id_b = sorted((a.id, b.id))
            if (id_a, id_b) in seen_pairs:
                continue
            acct_a, acct_b = (a, b) if a.id == id_a else (b, a)
            db.add(Suggestion(
                owner_id=current_user.id,
                suggestion_type="account_duplicate",
                entity_id_a=id_a, entity_id_b=id_b,
                score=round(score, 2),
                reasoning=f"{round(score)}% name match",
                evidence={
                    "name_a": acct_a.name, "address_a": acct_a.address,
                    "name_b": acct_b.name, "address_b": acct_b.address,
                },
            ))
            seen_pairs.add((id_a, id_b))
            created += 1

    db.commit()
    return {"pairs_found": pairs_found, "new_suggestions_created": created}


@router.post("/merge")
def merge_accounts(
    data: MergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-points every FK that references accounts.id from duplicate_id to
    survivor_id, unions roles, fills blank scalar fields on the survivor,
    and soft-merges the duplicate (merged_into_id) rather than deleting it —
    audit trail, and a safety net for any reference this missed."""
    from models.property import Property
    from models.property_party import PropertyParty
    from models.marketing_list import MarketingListMember
    from models.deal import Deal, DealContact
    from models.engagement import Engagement
    from models.suggestion import Suggestion

    if data.survivor_id == data.duplicate_id:
        raise HTTPException(400, "survivor_id and duplicate_id must differ")

    survivor = db.query(Account).filter(
        Account.id == data.survivor_id, Account.owner_id == current_user.id).first()
    duplicate = db.query(Account).filter(
        Account.id == data.duplicate_id, Account.owner_id == current_user.id).first()
    if not survivor or not duplicate:
        raise HTTPException(404, "Account not found")
    if survivor.merged_into_id is not None or duplicate.merged_into_id is not None:
        raise HTTPException(400, "One of these accounts has already been merged")

    links_repointed = {"properties": 0, "property_parties": 0, "contacts": 0,
                        "marketing_lists": 0, "engagements": 0, "deal_contacts": 0}

    # properties — 4 separate FK columns onto accounts
    for col in ("account_id", "recorded_owner_account_id", "manager_account_id", "tax_bill_account_id"):
        rows = db.query(Property).filter(
            getattr(Property, col) == duplicate.id, Property.owner_id == current_user.id).all()
        for p in rows:
            setattr(p, col, survivor.id)
        links_repointed["properties"] += len(rows)

    # property_parties — duplicate-safe against the (property_id, account_id, role) unique index
    for pp in (db.query(PropertyParty)
                 .join(Property, PropertyParty.property_id == Property.id)
                 .filter(PropertyParty.account_id == duplicate.id,
                         Property.owner_id == current_user.id).all()):
        clash = db.query(PropertyParty).filter(
            PropertyParty.property_id == pp.property_id,
            PropertyParty.account_id == survivor.id,
            PropertyParty.role == pp.role).first()
        db.delete(pp) if clash else setattr(pp, "account_id", survivor.id)
        links_repointed["property_parties"] += 1

    # contact_accounts — no owner_id column; account_id is already owner-validated above
    for ca in db.query(ContactAccount).filter(ContactAccount.account_id == duplicate.id).all():
        clash = db.query(ContactAccount).filter(
            ContactAccount.account_id == survivor.id,
            ContactAccount.contact_id == ca.contact_id).first()
        db.delete(ca) if clash else setattr(ca, "account_id", survivor.id)
        links_repointed["contacts"] += 1

    # marketing_list_members — duplicate-safe, one row per (list, account)
    for m in db.query(MarketingListMember).filter(MarketingListMember.account_id == duplicate.id).all():
        clash = db.query(MarketingListMember).filter(
            MarketingListMember.list_id == m.list_id,
            MarketingListMember.account_id == survivor.id).first()
        db.delete(m) if clash else setattr(m, "account_id", survivor.id)
        links_repointed["marketing_lists"] += 1

    # engagements
    for e in db.query(Engagement).filter(
            Engagement.client_account_id == duplicate.id, Engagement.owner_id == current_user.id).all():
        e.client_account_id = survivor.id
        links_repointed["engagements"] += 1

    # deal_contacts — no owner_id column either; scope via the parent Deal
    for dc in (db.query(DealContact)
                 .join(Deal, DealContact.deal_id == Deal.id)
                 .filter(DealContact.account_id == duplicate.id, Deal.owner_id == current_user.id).all()):
        dc.account_id = survivor.id
        links_repointed["deal_contacts"] += 1

    survivor.roles = sorted(set(survivor.roles or []) | set(duplicate.roles or []))

    fields_filled = []
    for field in ("address", "city", "state", "zip", "phone", "email",
                  "website", "notes", "ein", "entity_type"):
        if not getattr(survivor, field) and getattr(duplicate, field):
            setattr(survivor, field, getattr(duplicate, field))
            fields_filled.append(field)

    duplicate.merged_into_id = survivor.id

    id_a, id_b = sorted((survivor.id, duplicate.id))
    sugg = db.query(Suggestion).filter(
        Suggestion.entity_id_a == id_a, Suggestion.entity_id_b == id_b).first()
    if sugg:
        sugg.status = "merged"
        sugg.resolved_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "survivor_id":     survivor.id,
        "duplicate_id":    duplicate.id,
        "fields_filled":   fields_filled,
        "links_repointed": links_repointed,
    }
