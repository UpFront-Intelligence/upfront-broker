import os
import sys
import uuid

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, REPO_ROOT)

from database import SessionLocal  # noqa: E402
from models.user import User  # noqa: E402
from models.account import Account  # noqa: E402
from models.property import Property  # noqa: E402
from models.parcel_regrid import ParcelRegrid  # noqa: E402
from models.suggestion import Suggestion  # noqa: E402


@pytest.fixture
def db():
    """Real session against DATABASE_URL — there is no test-DB indirection
    here (see CLAUDE.md's PARCELS_REGRID section / this repo's test-running
    convention: scripts run against the live external DATABASE_URL same as
    the one-off backfill scripts). Point DATABASE_URL at a local/dev
    database, not production, before running pytest."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def make_owner(db):
    """Factory fixture — db.add()'s a fresh, uniquely-named test User per
    call. Cascading-deletes every owner it created (suggestions,
    properties, accounts, then the user itself) at teardown, in FK-safe
    order (accounts.owner_id -> users.id has no ondelete, so accounts must
    go before the user)."""
    created = []

    def _make(tag="test"):
        email = f"regrid-pytest-{tag}-{uuid.uuid4().hex[:8]}@local.invalid"
        user = User(email=email, full_name=f"Regrid Pytest ({tag})", is_active=True)
        db.add(user)
        db.flush()
        created.append(user)
        return user

    yield _make

    for user in created:
        db.query(Suggestion).filter(Suggestion.owner_id == user.id).delete(synchronize_session=False)
        db.query(Property).filter(Property.owner_id == user.id).delete(synchronize_session=False)
        db.query(Account).filter(Account.owner_id == user.id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def county(db):
    """A throwaway, uniquely-named source_county — deletes every
    parcels_regrid row filed under it at teardown. parcels_regrid has no
    owner_id (see CLAUDE.md), so isolation between test runs comes from
    giving each test its own county name rather than its own owner."""
    name = f"PytestCounty-{uuid.uuid4().hex[:8]}"
    yield name
    db.query(ParcelRegrid).filter(ParcelRegrid.source_county == name).delete(synchronize_session=False)
    db.commit()
