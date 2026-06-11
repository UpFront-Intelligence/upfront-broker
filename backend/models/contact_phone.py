from sqlalchemy import Column, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class ContactPhone(Base):
    __tablename__ = "contact_phones"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    contact_id  = Column(Integer, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)

    label       = Column(Text)   # mobile | office | direct | fax | other
    number      = Column(Text, nullable=False)
    is_primary  = Column(Boolean, nullable=False, default=False)

    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Single FK pair to contacts, but explicit per the AmbiguousForeignKeysError
    # lesson learned on properties<->accounts.
    contact = relationship("Contact", back_populates="phones", foreign_keys=[contact_id])
