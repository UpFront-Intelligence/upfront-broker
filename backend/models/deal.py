from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Boolean, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Deal(Base):
    __tablename__ = "deals"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"),       nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"),  nullable=False)

    # Identity
    name        = Column(String, nullable=False)
    deal_type   = Column(String)  # Listing, Buyer Rep, Lease - Landlord, Lease - Tenant

    # Stage
    stage       = Column(String, default="Prospecting")
    # Prospecting → Pitching → Active Listing → Under Contract → Closed → Dead

    # Financials
    list_price          = Column(Float)
    sale_price          = Column(Float)
    lease_rate          = Column(Float)     # per SF/year
    lease_sf            = Column(Float)
    lease_term_months   = Column(Integer)

    # Commission
    commission_pct      = Column(Float)
    commission_total    = Column(Float)     # calculated
    our_split_pct       = Column(Float, default=100.0)
    our_commission      = Column(Float)     # calculated

    # Co-broker
    co_broker           = Column(Boolean, default=False)
    co_broker_name      = Column(String)
    co_broker_firm      = Column(String)
    co_broker_split_pct = Column(Float)

    # Timeline
    projected_close     = Column(Date)
    actual_close        = Column(Date)
    list_date           = Column(Date)
    days_on_market      = Column(Integer)

    # Portal
    portal_enabled      = Column(Boolean, default=False)

    # Notes
    notes               = Column(Text)

    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner       = relationship("User",     back_populates="deals")
    property    = relationship("Property", back_populates="deals")
    contacts    = relationship("DealContact", back_populates="deal")
    activities  = relationship("Activity", back_populates="deal")
    documents   = relationship("Document", back_populates="deal")
    portal      = relationship("Portal",   back_populates="deal", uselist=False)


class DealContact(Base):
    __tablename__ = "deal_contacts"

    id          = Column(Integer, primary_key=True, index=True)
    deal_id     = Column(Integer, ForeignKey("deals.id"),    nullable=False)
    contact_id  = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    role        = Column(String)  # Seller, Buyer, Attorney, Lender, Guarantor, Co-Broker
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    deal    = relationship("Deal",    back_populates="contacts")
    contact = relationship("Contact", back_populates="deal_links")
    account = relationship("Account", back_populates="deal_links")
