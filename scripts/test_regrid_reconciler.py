#!/usr/bin/env python3
"""One-shot verification of the Regrid ingest -> reconcile pipeline against
the synthetic fixture (tests/fixtures/regrid_sample_wayne.csv), run against
the real DATABASE_URL — same pattern as the other one-off scripts/ files
(see scripts/backfill_property_category.py). No pytest scaffolding needed.

Usage (from repo root):
    python scripts/test_regrid_reconciler.py

DATABASE_URL comes from the environment, or backend/.env via the same
load_dotenv() database.py already calls. This talks to a REAL database —
point it at a local/dev database, not production, before running.

Creates an isolated test owner + 5 accounts + 5 properties (matching the
fixture's design — see scripts/generate_regrid_fixture.py's docstring for
the exact score bands this is built against), runs ingest_csv() then
reconcile(), asserts the expected 5 auto_linked / 8 suggested / 7 no_match
split, then deletes everything it created (including the fixture's 20
parcels_regrid rows by their known parcel_id list) so re-runs are
repeatable. Self-heals leftover data from a previous crashed run.

tests/test_regrid_reconciler.py (pytest) imports run_verification() from
this file rather than re-implementing the same setup/teardown.
"""
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPTS_DIR)  # so `from generate_regrid_fixture import ...` resolves
                                  # regardless of whether this file is run directly or
                                  # imported as scripts.test_regrid_reconciler (pytest)

from generate_regrid_fixture import SEED_ACCOUNTS, SEED_PROPERTIES  # noqa: E402

FIXTURE_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "regrid_sample_wayne.csv")
TEST_COUNTY = "Wayne"
TEST_USER_EMAIL = "regrid-fixture-test@local.invalid"

# The fixture's own parcel_ids (scripts/generate_regrid_fixture.py) — cleanup
# targets exactly these so this script never touches real Wayne County data
# once that exists.
FIXTURE_PARCEL_IDS = [
    "82-001-001.000", "82-001-002.000", "82-001-003.000", "82-001-004.000", "82-001-005.000",
    "82-002-001.000", "82-002-002.000", "82-002-003.000", "82-002-004.000",
    "82-002-005.000", "82-002-006.000", "82-002-007.000", "82-002-008.000",
    "82-003-001.000", "82-003-002.000", "82-003-003.000", "82-003-004.000",
    "82-003-005.000", "82-003-006.000", "82-003-007.000",
]

EXPECTED = {"auto_linked": 5, "suggested": 8, "no_match": 7}


def _cleanup(db):
    """Deletes any data this script (or a previous crashed run) created.
    Safe to call before AND after the real run."""
    from models.user import User
    from models.account import Account
    from models.property import Property
    from models.suggestion import Suggestion
    from models.parcel_regrid import ParcelRegrid

    user = db.query(User).filter(User.email == TEST_USER_EMAIL).first()

    db.query(ParcelRegrid).filter(ParcelRegrid.parcel_id.in_(FIXTURE_PARCEL_IDS),
                                   ParcelRegrid.source_county == TEST_COUNTY).delete(synchronize_session=False)

    if user:
        db.query(Suggestion).filter(Suggestion.owner_id == user.id).delete(synchronize_session=False)
        db.query(Property).filter(Property.owner_id == user.id).delete(synchronize_session=False)
        db.query(Account).filter(Account.owner_id == user.id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db.commit()


def _seed(db):
    from models.user import User
    from models.account import Account
    from models.property import Property
    from services.naming import normalize_name

    user = User(email=TEST_USER_EMAIL, full_name="Regrid Fixture Test", is_active=True)
    db.add(user)
    db.flush()

    for name in SEED_ACCOUNTS:
        db.add(Account(owner_id=user.id, name=name, normalized_name=normalize_name(name), roles=["owner"]))

    for address in SEED_PROPERTIES:
        db.add(Property(owner_id=user.id, name=address, address=address, city="Detroit", state="MI"))

    db.commit()
    return user


def run_verification(db=None) -> dict:
    """Returns {"expected": {...}, "actual": {...}, "passed": bool,
    "ingest": {...}, "reconcile": {...}}. Manages its own db session (and
    closes it) if none is passed in."""
    from database import SessionLocal
    from services.regrid import ingest_csv, reconcile

    owns_session = db is None
    if owns_session:
        db = SessionLocal()

    try:
        _cleanup(db)  # self-heal any leftovers from a previous crashed run
        user = _seed(db)

        with open(FIXTURE_PATH, "rb") as f:
            ingest_result = ingest_csv(db, TEST_COUNTY, f)

        reconcile_result = reconcile(db, user.id, county=TEST_COUNTY)

        actual = {k: reconcile_result.get(k, 0) for k in EXPECTED}
        passed = actual == EXPECTED and ingest_result["rows_ingested"] == 20 and not ingest_result["errors"]

        return {
            "expected": EXPECTED,
            "actual": actual,
            "passed": passed,
            "ingest": ingest_result,
            "reconcile": reconcile_result,
        }
    finally:
        _cleanup(db)
        if owns_session:
            db.close()


def main():
    result = run_verification()

    print("=" * 60)
    print("Regrid reconciler verification — synthetic Wayne County fixture")
    print("=" * 60)
    print(f"Ingested:  {result['ingest']['rows_ingested']} new, "
          f"{result['ingest']['rows_updated']} updated, "
          f"{len(result['ingest']['errors'])} errors")
    print()
    print(f"{'':12s}{'expected':>10s}{'actual':>10s}")
    for key in ("auto_linked", "suggested", "no_match"):
        exp, act = result["expected"][key], result["actual"][key]
        flag = "OK" if exp == act else "MISMATCH"
        print(f"{key:12s}{exp:>10d}{act:>10d}   {flag}")
    print()
    if result["passed"]:
        print("PASSED — 5/8/7 split matched exactly.")
    else:
        print("FAILED — see mismatch(es) above.")
        if result["ingest"]["errors"]:
            print(f"Ingest errors: {result['ingest']['errors']}")
    print("=" * 60)

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
