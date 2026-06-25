from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class PropertyNationalLocationLink(Base):
    """Links a broker's property to a NationalLocation row.

    Owner-scoping lives here via the Property FK (properties.owner_id
    gates visibility — a link is only visible to the broker who owns
    the referenced property). The NationalLocation itself has no
    owner_id (it's shared); this junction is how broker-specific
    'In your book' state is tracked.

    Created by POST /api/national-locations/link-to-my-properties,
    which fuzzy-matches address against the calling broker's properties.
    """
    __tablename__ = "property_national_location_links"

    id                   = Column(Integer, primary_key=True, index=True)
    property_id          = Column(Integer, ForeignKey("properties.id",         ondelete="CASCADE"), nullable=False)
    national_location_id = Column(Integer, ForeignKey("national_locations.id", ondelete="CASCADE"), nullable=False)
    match_confidence     = Column(Numeric(4, 3), nullable=True)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    property          = relationship("Property",          foreign_keys=[property_id])
    national_location = relationship("NationalLocation",  foreign_keys=[national_location_id])

    __table_args__ = (
        UniqueConstraint("property_id", "national_location_id", name="uq_pnll_property_location"),
    )
