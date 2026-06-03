from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
from models.shared import Document
from models.user import User
from auth_utils import get_current_user

router = APIRouter()

class DocumentCreate(BaseModel):
    name: str
    doc_type: Optional[str] = None
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    contact_id: Optional[int] = None
    property_id: Optional[int] = None
    deal_id: Optional[int] = None

class DocumentResponse(DocumentCreate):
    id: int
    class Config:
        from_attributes = True

@router.get("/", response_model=List[DocumentResponse])
def list_documents(
    deal_id: Optional[int] = None,
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Document).filter(Document.owner_id == current_user.id)
    if deal_id:
        q = q.filter(Document.deal_id == deal_id)
    if property_id:
        q = q.filter(Document.property_id == property_id)
    return q.all()

@router.post("/", response_model=DocumentResponse)
def create_document(
    data: DocumentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = Document(**data.dict(), owner_id=current_user.id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc

@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.owner_id == current_user.id
    ).first()
    db.delete(doc)
    db.commit()
    return {"deleted": True}
