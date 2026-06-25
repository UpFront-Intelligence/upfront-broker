from sqlalchemy import Column, Integer, Text, Numeric, DateTime, JSON, Index, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class NationalLocation(Base):
    """One row per Overture Maps Places location ingested for Michigan.

    No owner_id — shared reference data, same reasoning as parcels_regrid
    and ENRICHMENT_CACHE: the same Starbucks at 123 Main St is the same
    regardless of which broker looks it up. Owner-scoping happens only in
    the property_national_location_links junction (which links a location
    to a specific broker's property).

    Re-ingestion on quarterly Overture releases UPSERTs by overture_id —
    see scripts/ingest_overture_michigan.py.
    """
    __tablename__ = "national_locations"

    id               = Column(Integer, primary_key=True, index=True)

    overture_id      = Column(Text, nullable=False, unique=True, index=True)
    brand_primary    = Column(Text, nullable=True)
    brand_normalized = Column(Text, nullable=True, index=True)
    name_primary     = Column(Text, nullable=True)
    category_primary = Column(Text, nullable=True)
    category_top     = Column(Text, nullable=True, index=True)

    address          = Column(Text, nullable=True)
    city             = Column(Text, nullable=True)
    state            = Column(Text, nullable=True)
    zip              = Column(Text, nullable=True)

    lat              = Column(Numeric(9, 6), nullable=True)
    lng              = Column(Numeric(9, 6), nullable=True)

    websites         = Column(JSON, nullable=True)
    phones           = Column(JSON, nullable=True)
    confidence       = Column(Numeric(4, 3), nullable=True)
    raw_data         = Column(JSON, nullable=True)

    release_version  = Column(Text, nullable=True)
    ingested_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_national_locations_state_city", "state", "city"),
        Index("ix_national_locations_lat_lng",    "lat",   "lng"),
    )
