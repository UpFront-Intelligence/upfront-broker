from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Account(Base):
    __tablename__ = "accounts"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Entity info
    name            = Column(String, nullable=False, index=True)
    normalized_name = Column(String, nullable=True)
    roles           = Column(ARRAY(String), nullable=False, server_default='{}', default=list)
    entity_type     = Column(String)  # LLC, Corp, Trust, Individual, REIT, Partnership
    ein             = Column(String)  # Tax ID
    website         = Column(String)
    phone           = Column(String)
    email           = Column(String)

    # Address
    address     = Column(String)
    city        = Column(String)
    state       = Column(String)
    zip         = Column(String)

    # Notes
    notes       = Column(Text)

    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner           = relationship("User",           back_populates="accounts")
    contact_links   = relationship("ContactAccount", back_populates="account")
    properties      = relationship("Property",       back_populates="account",
                                    foreign_keys="Property.account_id")
    deal_links      = relationship("DealContact",    back_populates="account")
