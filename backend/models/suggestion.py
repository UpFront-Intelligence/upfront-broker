from sqlalchemy import Column, Integer, Text, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from database import Base


class Suggestion(Base):
    """General "hint" substrate (lightbulb-icon pattern) — system-generated,
    human-reviewed suggestions. First producer: account-duplicate detection.
    entity_id_a/b are typed to accounts.id for this pass; a future producer
    comparing other entity types needs its own columns or table."""
    __tablename__ = "suggestions"

    id              = Column(Integer, primary_key=True, index=True)
    owner_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    suggestion_type = Column(Text, nullable=False, default="account_duplicate")

    entity_id_a     = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    entity_id_b     = Column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)

    score           = Column(Numeric(5, 2), nullable=False)
    reasoning       = Column(Text, nullable=True)
    evidence        = Column(JSON, nullable=True)

    status          = Column(Text, nullable=False, default="new")  # new | dismissed | merged
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at     = Column(DateTime(timezone=True), nullable=True)
