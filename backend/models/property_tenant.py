from sqlalchemy import Column, Integer, Float, Boolean, Date, Text, String, ForeignKey
from database import Base


class PropertyTenant(Base):
    __tablename__ = "property_tenants"

    id              = Column(Integer, primary_key=True, index=True)
    owner_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id     = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    tenant_id       = Column(Integer, ForeignKey("tenants.id",    ondelete="CASCADE"), nullable=False)
    sf              = Column(Integer, nullable=True)
    pct_of_building = Column(Float,   nullable=True)
    rent_per_sf     = Column(Float,   nullable=True)
    lease_type      = Column(String,  nullable=True)
    lease_start     = Column(Date,    nullable=True)
    lease_expiry    = Column(Date,    nullable=True)
    is_available    = Column(Boolean, default=False)
    notes           = Column(Text,    nullable=True)
