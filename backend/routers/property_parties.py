"""
Property Parties — manual UI for property_parties, the general party <->
property <-> role junction (see models/property_party.py). Previously
write-only from bulk import (the general importer's party fan-out and
import_properties_parties.py's column-mapping importer); this router is
the first place a broker can view, add, or remove a party directly on a
property, rather than only via a spreadsheet upload.

GET    /api/properties/party-roles                      — account_roles vocabulary
GET    /api/properties/{property_id}/parties             — list parties for a property
POST   /api/properties/{property_id}/parties             — add a party (account_id OR contact_id + role)
DELETE /api/properties/{property_id}/parties/{party_id}  — remove a party (hard delete)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models.property import Property
from models.property_party import PropertyParty
from models.account import Account
from models.contact import Contact
from models.account_role import AccountRole
from models.user import User
from auth_utils import get_current_user
from services.property_parties import add_property_party

router = APIRouter()


def _get_owned_property(db: Session, property_id: int, owner_id: int) -> Property:
    prop = db.query(Property).filter(
        Property.id == property_id, Property.owner_id == owner_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


def _resolve_parties(db: Session, rows):
    account_ids = [r.account_id for r in rows if r.account_id]
    contact_ids = [r.contact_id for r in rows if r.contact_id]
    accounts_by_id = ({a.id: a for a in db.query(Account)
                        .filter(Account.id.in_(account_ids)).all()}
                       if account_ids else {})
    contacts_by_id = ({c.id: c for c in db.query(Contact)
                        .filter(Contact.id.in_(contact_ids)).all()}
                       if contact_ids else {})
    roles_by_slug = {r.slug: r.display_name for r in db.query(AccountRole).all()}

    out = []
    for r in rows:
        a = accounts_by_id.get(r.account_id) if r.account_id else None
        c = contacts_by_id.get(r.contact_id) if r.contact_id else None
        out.append({
            "id": r.id,
            "role": r.role,
            # Falls back to the raw slug for older import-sourced rows whose
            # role string isn't (or is no longer) in the account_roles seed.
            "role_display_name": roles_by_slug.get(r.role, r.role),
            "source": r.source,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "account": ({"id": a.id, "name": a.name, "entity_type": a.entity_type}
                        if a else None),
            "contact": ({"id": c.id, "first_name": c.first_name,
                          "last_name": c.last_name, "title": c.title}
                        if c else None),
        })
    return out


@router.get("/party-roles")
def list_party_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full account_roles vocabulary — populates the Add Party role dropdown."""
    rows = db.query(AccountRole).order_by(AccountRole.category, AccountRole.display_name).all()
    return [{"slug": r.slug, "display_name": r.display_name, "category": r.category}
            for r in rows]


@router.get("/{property_id}/parties")
def list_property_parties(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_property(db, property_id, current_user.id)
    rows = (db.query(PropertyParty)
              .filter(PropertyParty.property_id == property_id)
              .order_by(PropertyParty.created_at).all())
    return _resolve_parties(db, rows)


class AddPropertyPartyRequest(BaseModel):
    account_id: Optional[int] = None
    contact_id: Optional[int] = None
    role: str
    note: Optional[str] = None


@router.post("/{property_id}/parties")
def create_property_party(
    property_id: int,
    data: AddPropertyPartyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_property(db, property_id, current_user.id)

    if bool(data.account_id) == bool(data.contact_id):
        raise HTTPException(status_code=400,
            detail="Provide exactly one of account_id or contact_id")

    # Owner-isolation on write: the client-supplied FK must belong to this owner.
    if data.account_id:
        acct = db.query(Account).filter(
            Account.id == data.account_id, Account.owner_id == current_user.id).first()
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")
    if data.contact_id:
        contact = db.query(Contact).filter(
            Contact.id == data.contact_id, Contact.owner_id == current_user.id).first()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

    role_row = db.query(AccountRole).filter(AccountRole.slug == data.role).first()
    if not role_row:
        raise HTTPException(status_code=400, detail=f"Unknown role '{data.role}'")

    pp = add_property_party(db, property_id, data.role,
                             account_id=data.account_id, contact_id=data.contact_id,
                             source="manual", note=data.note)
    if pp is None:
        raise HTTPException(status_code=409,
            detail="This party already has this role on this property")
    db.commit()
    return _resolve_parties(db, [pp])[0]


@router.delete("/{property_id}/parties/{party_id}", status_code=204)
def delete_property_party(
    property_id: int,
    party_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_property(db, property_id, current_user.id)
    pp = db.query(PropertyParty).filter(
        PropertyParty.id == party_id, PropertyParty.property_id == property_id).first()
    if not pp:
        raise HTTPException(status_code=404, detail="Party not found")
    db.delete(pp)
    db.commit()
