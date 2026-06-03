from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Contact(Base):
    __tablename__ = "contacts"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Core identity
    first_name  = Column(String, nullable=False)
    last_name   = Column(String, nullable=False)
    email       = Column(String, index=True)
    phone       = Column(String)
    mobile      = Column(String)
    title       = Column(String)
    photo_url   = Column(String)
    linkedin    = Column(String)

    # Classification
    contact_type = Column(String)  # Owner, Buyer, Tenant, Attorney, Lender, Broker
    source       = Column(String)  # Referral, CoStar, Cold Call, etc.
    tags         = Column(ARRAY(String), default=[])

    # Notes
    notes       = Column(Text)

    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner               = relationship("User",            back_populates="contacts")
    account_links       = relationship("ContactAccount",  back_populates="contact")
    deal_links          = relationship("DealContact",     back_populates="contact")
    activities          = relationship("Activity",        back_populates="contact")
    documents           = relationship("Document",        back_populates="contact")
