from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class MarketingList(Base):
    __tablename__ = "marketing_lists"

    id          = Column(Integer, primary_key=True, index=True)
    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    members = relationship(
        "MarketingListMember",
        back_populates="marketing_list",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )


class MarketingListMember(Base):
    __tablename__ = "marketing_list_members"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(account_id, contact_id) = 1",
            name="chk_mlm_exactly_one_entity",
        ),
    )

    id         = Column(Integer, primary_key=True, index=True)
    list_id    = Column(Integer, ForeignKey("marketing_lists.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id",        ondelete="SET NULL"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id",        ondelete="SET NULL"), nullable=True)
    source     = Column(Text, nullable=False, default="manual")
    note       = Column(Text, nullable=True)
    added_at   = Column(DateTime(timezone=True), server_default=func.now())

    marketing_list = relationship("MarketingList", back_populates="members")

    # Explicit foreign_keys= to avoid AmbiguousForeignKeysError on any future
    # multi-FK relationship between these tables.
    account = relationship("Account", foreign_keys=[account_id])
    contact = relationship("Contact", foreign_keys=[contact_id])
