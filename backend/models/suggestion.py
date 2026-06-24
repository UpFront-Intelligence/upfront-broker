from sqlalchemy import Column, Integer, Text, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from database import Base


class Suggestion(Base):
    """General "hint" substrate (lightbulb-icon pattern) — system-generated,
    human-reviewed suggestions. First producer: account-duplicate detection
    (both entity_id_a/b populated, both accounts.id). Second producer:
    Regrid owner-match reconciliation (routers/regrid.py) — only
    entity_id_a is used (the candidate matched account); entity_id_b is
    nullable because the other side of that comparison is a parcels_regrid
    row, not an accounts.id, so it lives in evidence JSON instead."""
    __tablename__ = "suggestions"

    id              = Column(Integer, primary_key=True, index=True)
    owner_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    suggestion_type = Column(Text, nullable=False, default="account_duplicate")

    entity_id_a     = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    entity_id_b     = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)

    score           = Column(Numeric(5, 2), nullable=False)
    reasoning       = Column(Text, nullable=True)
    evidence        = Column(JSON, nullable=True)

    status          = Column(Text, nullable=False, default="new")  # new | dismissed | merged
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at     = Column(DateTime(timezone=True), nullable=True)
