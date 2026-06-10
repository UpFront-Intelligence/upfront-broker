from sqlalchemy import Column, Integer, String, Text, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

ENGAGEMENT_TYPES = [
    "listing_sale", "listing_lease", "tenant_rep", "buyer_rep",
    "bov", "consulting", "referral",
]

ENGAGEMENT_STAGES = ["pursuing", "proposed", "active", "closed", "lost", "expired"]


class Engagement(Base):
    __tablename__ = "engagements"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=False)

    type        = Column(String, nullable=False)
    stage       = Column(String, nullable=False, default="pursuing")

    signed_agreement = Column(Boolean, nullable=False, default=False)
    agreement_date   = Column(Date, nullable=True)

    client_account_id   = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    subject_property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)

    name        = Column(String, nullable=False)
    notes       = Column(Text)

    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Single FK each to accounts/properties, but explicit per the
    # AmbiguousForeignKeysError lesson on properties<->accounts.
    client_account   = relationship("Account",  foreign_keys=[client_account_id])
    subject_property = relationship("Property", foreign_keys=[subject_property_id])
