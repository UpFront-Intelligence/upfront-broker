from sqlalchemy import Column, String
from database import Base


class AccountRole(Base):
    """Canonical account role vocabulary — global lookup, no owner_id."""
    __tablename__ = "account_roles"

    slug         = Column(String, primary_key=True)
    display_name = Column(String, nullable=False)
    category     = Column(String, nullable=False)
