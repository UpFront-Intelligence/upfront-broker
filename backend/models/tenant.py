from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id              = Column(Integer, primary_key=True, index=True)
    owner_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    name            = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, default='')
    industry        = Column(String, nullable=True)
    website         = Column(String, nullable=True)
    hq_address      = Column(String, nullable=True)
    hq_city         = Column(String, nullable=True)
    hq_state        = Column(String, nullable=True)
    hq_zip          = Column(String, nullable=True)
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
