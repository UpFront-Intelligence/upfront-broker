from sqlalchemy import Column, Integer, String, Float, Boolean, Date, Text, ForeignKey
from database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id              = Column(Integer, primary_key=True, index=True)
    property_id     = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False)
    tenant_name     = Column(String, nullable=False)
    sf              = Column(Integer, nullable=True)
    pct_of_building = Column(Float, nullable=True)
    lease_expiry    = Column(Date, nullable=True)
    is_available    = Column(Boolean, default=False)
    notes           = Column(Text, nullable=True)
    owner_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
