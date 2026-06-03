from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Boolean, Date, ARRAY, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime, timedelta, timezone
import secrets
from database import Base


class Activity(Base):
    __tablename__ = "activities"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"),       nullable=False)
    contact_id  = Column(Integer, ForeignKey("contacts.id"),    nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id"),  nullable=True)
    deal_id     = Column(Integer, ForeignKey("deals.id"),       nullable=True)

    activity_type   = Column(String)  # Call, Email, Meeting, Tour, Offer, LOI, Contract, Note
    subject         = Column(String)
    notes           = Column(Text)
    activity_date   = Column(DateTime(timezone=True))
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    owner       = relationship("User",     back_populates="activities")
    contact     = relationship("Contact",  back_populates="activities")
    property    = relationship("Property", back_populates="activities")
    deal        = relationship("Deal",     back_populates="activities")


class Document(Base):
    __tablename__ = "documents"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"),       nullable=False)
    contact_id  = Column(Integer, ForeignKey("contacts.id"),    nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id"),  nullable=True)
    deal_id     = Column(Integer, ForeignKey("deals.id"),       nullable=True)

    name        = Column(String, nullable=False)
    doc_type    = Column(String)  # LOI, PSA, Lease, BOV, Flyer, CoStar Export, Other
    file_url    = Column(String)
    file_size   = Column(Integer)   # bytes
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    contact     = relationship("Contact",  back_populates="documents")
    property    = relationship("Property", back_populates="documents")
    deal        = relationship("Deal",     back_populates="documents")


class Portal(Base):
    __tablename__ = "portals"

    id          = Column(Integer, primary_key=True, index=True)
    deal_id     = Column(Integer, ForeignKey("deals.id"), nullable=False, unique=True)

    token           = Column(String, unique=True, index=True, default=lambda: secrets.token_urlsafe(24))
    seller_emails   = Column(ARRAY(String), default=[])
    buyer_emails    = Column(ARRAY(String), default=[])

    # Content
    pov             = Column(Text)      # agent-editable point of value
    challenges      = Column(Text)      # bullet list
    mutual_steps    = Column(Text)      # JSON array of steps with completion flags

    # Toggles
    show_timeline   = Column(Boolean, default=True)
    show_docs       = Column(Boolean, default=True)
    show_comps      = Column(Boolean, default=False)
    show_offers     = Column(Boolean, default=False)

    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    deal    = relationship("Deal",        back_populates="portal")
    views   = relationship("PortalView",  back_populates="portal")


class PortalView(Base):
    __tablename__ = "portal_views"

    id          = Column(Integer, primary_key=True, index=True)
    portal_id   = Column(Integer, ForeignKey("portals.id"), nullable=False)
    email       = Column(String)
    section     = Column(String)    # overview, docs, timeline, comps, offers
    viewed_at   = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    portal  = relationship("Portal", back_populates="views")


class Comp(Base):
    __tablename__ = "comps"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"),       nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"),  nullable=True)

    # Comp data
    address         = Column(String)
    city            = Column(String)
    state           = Column(String)
    property_type   = Column(String)
    sf              = Column(Float)
    sale_price      = Column(Float)
    price_per_sf    = Column(Float)
    cap_rate        = Column(Float)
    sale_date       = Column(Date)
    year_built      = Column(Integer)
    source          = Column(String, default="Manual")  # CoStar Upload, Manual
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    property    = relationship("Property", back_populates="comps")


def _ninety_days():
    return datetime.now(timezone.utc) + timedelta(days=90)


class EnrichmentCache(Base):
    __tablename__ = "enrichment_cache"

    # Intentionally has no owner_id — shared cache for public-records data only.
    # Third-party sourced fields (ArcGIS, BS&A) are the same for every broker;
    # caching them per-user wastes space and burns API quota needlessly.
    # See CLAUDE.md § Data Privacy Architecture (Option A / Option B).

    id               = Column(Integer, primary_key=True, index=True)
    lookup_type      = Column(String,  nullable=False, index=True)   # "parcel_id", "address"
    lookup_key       = Column(String,  nullable=False, index=True)   # the value looked up
    source           = Column(String,  nullable=False)               # "Oakland_ArcGIS", "BSA_Wayne", …

    raw_response     = Column(JSON,           nullable=True)
    phone_numbers    = Column(ARRAY(String),  nullable=True, default=list)
    emails           = Column(ARRAY(String),  nullable=True, default=list)
    owner_name       = Column(String,         nullable=True)
    confidence_score = Column(Float,          nullable=True)         # 0.0 – 1.0

    fetched_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at       = Column(DateTime(timezone=True), nullable=False, default=_ninety_days)
    hit_count        = Column(Integer, nullable=False, default=0)
