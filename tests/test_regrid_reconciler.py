"""Pytest suite for the Regrid reconciler (backend/services/regrid.py +
backend/routers/regrid.py), run against the real DATABASE_URL.

Calls router functions directly as plain Python functions (passing db/
current_user explicitly) rather than through FastAPI's TestClient — these
endpoints are thin wrappers with no HTTP-specific behavior worth a second
test harness, and this avoids adding httpx as a new dependency just for
tests. See backend/requirements-dev.txt for the one new dependency this
suite does need (pytest itself — there was no test runner in this repo
before this file).

test_fixture_split_matches_expected_5_8_7 imports run_verification() from
scripts/test_regrid_reconciler.py rather than re-seeding the same five
accounts/properties a second time — see that file's docstring for the
fixture's score-band design.
"""
import io
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
sys.path.insert(0, REPO_ROOT)

from models.account import Account  # noqa: E402
from models.property import Property  # noqa: E402
from models.parcel_regrid import ParcelRegrid  # noqa: E402
from models.suggestion import Suggestion  # noqa: E402
from services.naming import normalize_name  # noqa: E402
from services import regrid as regrid_service  # noqa: E402
from routers import regrid as regrid_router  # noqa: E402
from routers import suggestions as suggestions_router  # noqa: E402

from scripts.test_regrid_reconciler import run_verification  # noqa: E402


def _csv(body: str) -> io.BytesIO:
    return io.BytesIO(body.encode("utf-8"))


def test_fixture_split_matches_expected_5_8_7():
    result = run_verification()
    assert result["ingest"]["rows_ingested"] == 20
    assert result["ingest"]["errors"] == []
    assert result["actual"] == {"auto_linked": 5, "suggested": 8, "no_match": 7}
    assert result["passed"] is True


def test_ingest_is_upsert_on_rerun(db, county):
    body = (
        "parcelnumb,owner,address,city,state,zip,county,geometry,extra_col\n"
        "P-1,Acme Holdings LLC,100 Main St,Detroit,MI,48201,Wayne,POINT(0 0),foo\n"
    )
    result1 = regrid_service.ingest_csv(db, county, _csv(body))
    assert result1 == {"rows_ingested": 1, "rows_updated": 0, "errors": []}

    body_v2 = body.replace("Acme Holdings LLC", "Acme Holdings II LLC")
    result2 = regrid_service.ingest_csv(db, county, _csv(body_v2))
    assert result2 == {"rows_ingested": 0, "rows_updated": 1, "errors": []}

    rows = db.query(ParcelRegrid).filter(ParcelRegrid.source_county == county).all()
    assert len(rows) == 1
    assert rows[0].owner_raw == "Acme Holdings II LLC"
    assert rows[0].raw_data == {"extra_col": "foo"}


def test_ingest_skips_rows_missing_parcel_id(db, county):
    body = (
        "parcelnumb,owner,address,city,state,zip,county,geometry\n"
        ",No Parcel Owner,200 Side St,Detroit,MI,48201,Wayne,POINT(0 0)\n"
        "P-2,Has Parcel Owner,300 Main St,Detroit,MI,48201,Wayne,POINT(0 0)\n"
    )
    result = regrid_service.ingest_csv(db, county, _csv(body))
    assert result["rows_ingested"] == 1
    assert len(result["errors"]) == 1
    assert "Row 2" in result["errors"][0]


def test_reconcile_is_owner_isolated(db, county, make_owner):
    """A reconcile call must only ever match against the calling owner's
    own accounts — never another owner's, even when another owner's
    account would have scored a perfect match."""
    owner_a = make_owner("iso-a")
    owner_b = make_owner("iso-b")
    db.add(Account(owner_id=owner_a.id, name="Totally Unrelated Co",
                   normalized_name=normalize_name("Totally Unrelated Co"), roles=["owner"]))
    matching_name = "Acme Capital Partners LLC"
    acct_b = Account(owner_id=owner_b.id, name=matching_name,
                      normalized_name=normalize_name(matching_name), roles=["owner"])
    db.add(acct_b)
    db.commit()

    body = (
        "parcelnumb,owner,address,city,state,zip,county,geometry\n"
        f"P-ISO-1,{matching_name},900 Test St,Detroit,MI,48201,Wayne,POINT(0 0)\n"
    )
    regrid_service.ingest_csv(db, county, _csv(body))

    result_a = regrid_service.reconcile(db, owner_a.id, county=county)
    assert result_a == {"processed": 1, "auto_linked": 0, "suggested": 0, "no_match": 1}

    leaked = db.query(Suggestion).filter(Suggestion.entity_id_a == acct_b.id).first()
    assert leaked is None


def _seed_suggested_match(db, owner, county, with_property_match=False):
    """Seeds one account ~78% matching one ingested parcel's owner name
    (verified against rapidfuzz directly — comfortably inside the 65-94
    'suggested' band) and runs reconcile. Returns (suggestion, account)."""
    account_name = "Bedrock Property Partners LLC"
    account = Account(owner_id=owner.id, name=account_name,
                       normalized_name=normalize_name(account_name), roles=["owner"])
    db.add(account)

    address = "500 Test Ave"
    if with_property_match:
        db.add(Property(owner_id=owner.id, name=address, address=address, city="Detroit", state="MI"))
    db.commit()

    parcel_owner = "Bedrock Property Group"  # ~78% match — not exact
    body = (
        "parcelnumb,owner,address,city,state,zip,county,geometry\n"
        f"P-SUGG-1,{parcel_owner},{address},Detroit,MI,48201,Wayne,POINT(0 0)\n"
    )
    regrid_service.ingest_csv(db, county, _csv(body))
    result = regrid_service.reconcile(db, owner.id, county=county)
    assert result["suggested"] == 1, f"fixture score-band assumption broken: {result}"

    suggestion = db.query(Suggestion).filter(
        Suggestion.owner_id == owner.id, Suggestion.suggestion_type == "regrid_owner_match").first()
    assert suggestion is not None
    return suggestion, account


def test_confirm_regrid_suggestion_applies_link(db, county, make_owner):
    owner = make_owner("confirm")
    suggestion, candidate_account = _seed_suggested_match(db, owner, county, with_property_match=True)

    result = regrid_router.confirm_suggestion(suggestion.id, db=db, current_user=owner)

    db.refresh(suggestion)
    parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == suggestion.evidence["parcel_regrid_id"]).first()
    prop = db.query(Property).filter(Property.id == result["matched_property_id"]).first()

    assert suggestion.status == "merged"
    assert parcel.reconciliation_status == "auto_linked"
    assert parcel.matched_account_id == candidate_account.id
    assert prop.recorded_owner_account_id == candidate_account.id
    assert "owner" in candidate_account.roles


def test_dismiss_regrid_suggestion_flips_parcel_to_no_match(db, county, make_owner):
    owner = make_owner("dismiss")
    suggestion, _ = _seed_suggested_match(db, owner, county)

    suggestions_router.dismiss_suggestion(suggestion.id, db=db, current_user=owner)

    db.refresh(suggestion)
    parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == suggestion.evidence["parcel_regrid_id"]).first()
    assert suggestion.status == "dismissed"
    assert parcel.reconciliation_status == "no_match"


def test_create_account_from_suggestion(db, county, make_owner):
    owner = make_owner("create-acct")
    suggestion, candidate_account = _seed_suggested_match(db, owner, county)

    result = regrid_router.create_account_from_suggestion(suggestion.id, db=db, current_user=owner)

    db.refresh(suggestion)
    new_account = db.query(Account).filter(Account.id == result["account_id"]).first()
    parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == suggestion.evidence["parcel_regrid_id"]).first()

    assert suggestion.status == "merged"
    assert new_account is not None
    assert new_account.id != candidate_account.id
    assert new_account.owner_id == owner.id
    assert parcel.matched_account_id == new_account.id
    assert parcel.reconciliation_status == "auto_linked"
