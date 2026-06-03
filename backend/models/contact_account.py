from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class ContactAccount(Base):
    __tablename__ = "contact_accounts"

    id          = Column(Integer, primary_key=True, index=True)
    contact_id  = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    role        = Column(String)    # Owner, Partner, Signatory, Manager, Trustee
    is_primary  = Column(Boolean, default=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    contact = relationship("Contact", back_populates="account_links")
    account = relationship("Account", back_populates="contact_links")
