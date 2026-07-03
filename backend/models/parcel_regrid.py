from sqlalchemy import Column, Integer, Text, DateTime, Date, Numeric, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class ParcelRegrid(Base):
    """One row per Regrid parcel, one CSV per Michigan county (source_county).

    Deliberately has NO owner_id — like ENRICHMENT_CACHE and the legacy
    Oakland-County PARCELS table, this is shared public-record reference
    data (the same parcel fact regardless of which broker looks it up),
    not a per-broker entity. Distinct from the legacy `parcels` table
    (Oakland-only, fixed columns, raw SQL) — this one is multi-county and
    keeps the full Regrid row via raw_data so unmapped columns are never
    lost. See CLAUDE.md's PARCELS_REGRID section for the reconciliation
    flow and the owner-scoping caveat on matched_account_id/matched_property_id.
    """
    __tablename__ = "parcels_regrid"

    id               = Column(Integer, primary_key=True, index=True)

    parcel_id        = Column(Text, nullable=False, index=True)
    owner_raw        = Column(Text, nullable=True)
    owner_normalized = Column(Text, nullable=True, index=True)

    address          = Column(Text, nullable=True)
    city             = Column(Text, nullable=True)
    state            = Column(Text, nullable=True)
    zip              = Column(Text, nullable=True)
    county           = Column(Text, nullable=True)

    geometry_wkt     = Column(Text, nullable=True)
    raw_data         = Column(JSON, nullable=True)

    ingested_at      = Column(DateTime(timezone=True), server_default=func.now())
    source_county    = Column(Text, nullable=False)

    reconciliation_status = Column(Text, nullable=False, default="pending", index=True)
    # pending | auto_linked | suggested | no_match

    matched_account_id  = Column(Integer, ForeignKey("accounts.id",   ondelete="SET NULL"), nullable=True)
    matched_property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)

    # ── Searchable fields (migration 97ff9ec4ed1c, 2026-07-03) ───────────────
    usecode        = Column(Text, nullable=True, index=True)
    usedesc        = Column(Text, nullable=True)
    assessed_value = Column(Numeric(14, 2), nullable=True, index=True)
    sale_price     = Column(Numeric(14, 2), nullable=True, index=True)
    sale_date      = Column(Date, nullable=True)
    lot_acres      = Column(Numeric(10, 5), nullable=True, index=True)
    zoning         = Column(Text, nullable=True)
    land_use       = Column(Text, nullable=True)
    centroid_lat   = Column(DOUBLE_PRECISION, nullable=True)
    centroid_lng   = Column(DOUBLE_PRECISION, nullable=True)

    __table_args__ = (
        UniqueConstraint("parcel_id", "source_county", name="uq_parcels_regrid_parcel_county"),
    )

    matched_account  = relationship("Account",  foreign_keys=[matched_account_id])
    matched_property = relationship("Property", foreign_keys=[matched_property_id])
