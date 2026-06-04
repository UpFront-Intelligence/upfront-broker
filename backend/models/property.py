from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, ARRAY, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

PROPERTY_TYPES = [
    "Office", "Industrial", "Retail", "Land", "Multifamily",
    "STNL", "Self Storage", "Hospitality", "Medical"
]

class Property(Base):
    __tablename__ = "properties"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"),    nullable=False)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # current owner entity

    # Identity
    name        = Column(String)
    address     = Column(String, nullable=False)
    city        = Column(String, nullable=False)
    state       = Column(String, nullable=False)
    zip         = Column(String)
    county      = Column(String)

    # Classification
    property_type   = Column(String)   # Office, Industrial, Retail, etc.
    subtype         = Column(String)   # e.g. "Flex", "Strip Center", "Garden"
    status          = Column(String, default="Active")  # Active, Off Market, Sold, Leased

    # Physical
    year_built      = Column(Integer)
    sf_rentable     = Column(Float)
    sf_land         = Column(Float)
    units           = Column(Integer)   # multifamily
    stories         = Column(Integer)
    zoning          = Column(String)
    parking_ratio   = Column(Float)
    occupancy_pct   = Column(Float)

    # Financial
    asking_price        = Column(Float)
    asking_price_per_sf = Column(Float)
    assessed_value      = Column(Float)
    tax_amount          = Column(Float)
    tax_year            = Column(Integer)
    cap_rate            = Column(Float)
    noi                 = Column(Float)

    # Public records
    parcel_id       = Column(String, index=True)
    legal_desc      = Column(Text)

    # Media
    photo_urls      = Column(ARRAY(String), default=[])

    # Geocoordinates (auto-set by Nominatim on save)
    lat             = Column(Float, nullable=True)
    lng             = Column(Float, nullable=True)

    # Sale history
    last_sale_price = Column(Float, nullable=True)
    last_sale_date  = Column(Date, nullable=True)

    # Tenant
    tenant          = Column(String, nullable=True)

    # Notes
    notes           = Column(Text)

    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner       = relationship("User",     back_populates="properties")
    account     = relationship("Account",  back_populates="properties")
    deals       = relationship("Deal",     back_populates="property")
    activities  = relationship("Activity", back_populates="property")
    documents   = relationship("Document", back_populates="property")
    comps       = relationship("Comp",     back_populates="property")
