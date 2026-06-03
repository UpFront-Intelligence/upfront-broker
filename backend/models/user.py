from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    email           = Column(String, unique=True, index=True, nullable=False)
    google_id       = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=True)   # nullable — Google OAuth users have none
    full_name       = Column(String)
    company         = Column(String)
    phone           = Column(String)
    photo_url       = Column(String)
    license_number  = Column(String)
    territory       = Column(String)
    is_active       = Column(Boolean, default=True)
    is_admin        = Column(Boolean, default=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    contacts    = relationship("Contact",  back_populates="owner")
    accounts    = relationship("Account",  back_populates="owner")
    properties  = relationship("Property", back_populates="owner")
    deals       = relationship("Deal",     back_populates="owner")
    activities  = relationship("Activity", back_populates="owner")
