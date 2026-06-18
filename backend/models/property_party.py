from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class PropertyParty(Base):
    """Every party linked to a property gets an explicit row with a role —
    leasing_broker / owner / sale_broker / tenant_rep / manager / tax_bill.
    A party is either an Account or a Contact; at least one must be set."""
    __tablename__ = "property_parties"

    id          = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    account_id  = Column(Integer, ForeignKey("accounts.id",   ondelete="CASCADE"), nullable=True)
    contact_id  = Column(Integer, ForeignKey("contacts.id",   ondelete="CASCADE"), nullable=True)

    role        = Column(Text, nullable=False)
    source      = Column(Text, nullable=False, default="import")
    note        = Column(Text, nullable=True)

    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Explicit foreign_keys= on every relationship — properties<->accounts has
    # ambiguous-FK history in this codebase, so pin defensively here too even
    # though each of these FK columns is currently the only one of its kind.
    property = relationship("Property", foreign_keys=[property_id])
    account  = relationship("Account",  foreign_keys=[account_id])
    contact  = relationship("Contact",  foreign_keys=[contact_id])
