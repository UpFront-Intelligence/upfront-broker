"""Regrid county-CSV ingestion + owner/property reconciliation.

Two independent steps, deliberately not combined into one call (see
CLAUDE.md's PARCELS_REGRID section):

  ingest_csv()  — dumb, fast, idempotent CSV -> parcels_regrid UPSERT.
                  Never touches accounts/properties.
  reconcile()   — owner-scoped fuzzy matching of pending parcels_regrid
                  rows against an owner's accounts/properties.

Built against synthetic fixtures (tests/fixtures/regrid_sample_wayne.csv)
ahead of real Regrid CSVs landing — see the column-name confidence notes
on _PARCEL_ID_KEYS etc. below before trusting this against a real file.
"""
import csv
import io
import logging
from datetime import datetime, timezone
from typing import IO, Optional

from sqlalchemy.orm import Session
from rapidfuzz import fuzz

from models.account import Account
from models.property import Property
from models.parcel_regrid import ParcelRegrid
from models.suggestion import Suggestion
from services.naming import normalize_name, normalize_address
from services.accounts import owned_accounts_query, ensure_role

logger = logging.getLogger(__name__)

# Column-name candidates, in priority order. Confirmed against Regrid's
# public schema docs (support.regrid.com/parcel-data/schema) where noted;
# everything else is a best-effort guess pending the real county CSVs.
#
# ALL COLUMN NAMES CONFIRMED against mi_oakland.csv.gz (2026-06-29 audit).
# Keys are in priority order for _first_present(); confirmed-real names first.
#
#   parcelnumb     — CONFIRMED col 2. Value in ll_stable_id="parcelnumb" confirms
#                    this is the county's stable parcel identifier for Oakland.
#   parcelnumb_no_formatting, state_parcelnumb, account_number, tax_id — real
#                    fallback columns confirmed present (cols 3-6), used when
#                    parcelnumb itself is blank.
#   keypin         — ABSENT from real file entirely. Removed as a candidate.
#                    Was this app's own legacy `parcels` table PK name.
#   city / scity   — BOTH confirmed present (cols 74, 72). 'city' is lowercase;
#                    'scity' is uppercase. Prefer 'city'.
#   state2         — CONFIRMED col 76. No bare 'state' column exists.
#   szip5 / szip   — BOTH confirmed present (cols 78, 77). szip5 = clean 5-digit
#                    ("48009"); szip = ZIP+4 with hyphen ("48009-0902"). Prefer szip5.
#   county         — CONFIRMED col 75. 'county_name' is absent.
#   wkt            — CONFIRMED col 169 (last column). 'geometry'/'geom' absent.
_PARCEL_ID_KEYS = ('parcelnumb', 'parcelnumb_no_formatting', 'state_parcelnumb',
                   'account_number', 'tax_id')
_OWNER_KEYS     = ('owner',)
_ADDRESS_KEYS   = ('address',)
_CITY_KEYS      = ('city', 'scity')
_STATE_KEYS     = ('state2', 'state')
_ZIP_KEYS       = ('szip5', 'szip', 'zip')
_COUNTY_KEYS    = ('county', 'county_name')
_GEOMETRY_KEYS  = ('wkt', 'geometry', 'geom')

_ALL_CRITICAL_KEYS = frozenset(
    _PARCEL_ID_KEYS + _OWNER_KEYS + _ADDRESS_KEYS + _CITY_KEYS
    + _STATE_KEYS + _ZIP_KEYS + _COUNTY_KEYS + _GEOMETRY_KEYS
)

AUTO_LINK_THRESHOLD = 95
SUGGEST_THRESHOLD = 65
_MAX_COLLECTED_ERRORS = 100
_COMMIT_EVERY = 500


def _first_present(row: dict, keys) -> Optional[str]:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def ingest_csv(db: Session, source_county: str, fileobj: IO[bytes]) -> dict:
    """Streams a Regrid county CSV row-by-row into parcels_regrid.

    `fileobj` is a binary file handle (e.g. UploadFile.file) — wrapped in
    a text reader here rather than reading the whole upload into memory
    first, so multi-hundred-MB county files don't blow up memory.

    UPSERT on (parcel_id, source_county): re-running ingestion for the
    same county (e.g. Regrid's quarterly refresh) updates the raw columns
    in place. Reconciliation state (reconciliation_status, matched_*_id)
    is deliberately left untouched on update — ingestion never reopens or
    re-judges a row reconcile() has already resolved. If a parcel's owner
    genuinely changes hands between refreshes, that's not detected here;
    out of scope for this pass.
    """
    text_stream = io.TextIOWrapper(fileobj, encoding='utf-8-sig', newline='')
    reader = csv.DictReader(text_stream)
    if not reader.fieldnames:
        return {"rows_ingested": 0, "rows_updated": 0, "errors": ["CSV has no header row"]}

    field_map = {h: (h or '').strip().lower() for h in reader.fieldnames}

    rows_ingested = 0
    rows_updated = 0
    rows_seen_since_commit = 0
    errors = []
    skipped = 0

    for row_num, raw_row in enumerate(reader, start=2):  # row 1 = header
        row = {field_map.get(k, (k or '').strip().lower()): v
               for k, v in raw_row.items() if k is not None}

        parcel_id = _first_present(row, _PARCEL_ID_KEYS)
        if not parcel_id:
            skipped += 1
            if len(errors) < _MAX_COLLECTED_ERRORS:
                errors.append(f"Row {row_num}: missing parcel_id (parcelnumb/keypin both blank)")
            continue

        owner_raw = _first_present(row, _OWNER_KEYS)
        address   = _first_present(row, _ADDRESS_KEYS)
        city      = _first_present(row, _CITY_KEYS)
        state     = _first_present(row, _STATE_KEYS)
        zip_code  = _first_present(row, _ZIP_KEYS)
        county    = _first_present(row, _COUNTY_KEYS)
        geometry  = _first_present(row, _GEOMETRY_KEYS)
        raw_data  = {k: v for k, v in row.items() if k not in _ALL_CRITICAL_KEYS}

        existing = db.query(ParcelRegrid).filter(
            ParcelRegrid.parcel_id == parcel_id,
            ParcelRegrid.source_county == source_county,
        ).first()

        if existing:
            existing.owner_raw = owner_raw
            existing.owner_normalized = normalize_name(owner_raw) if owner_raw else None
            existing.address = address
            existing.city = city
            existing.state = state
            existing.zip = zip_code
            existing.county = county
            existing.geometry_wkt = geometry
            existing.raw_data = raw_data
            rows_updated += 1
        else:
            db.add(ParcelRegrid(
                parcel_id=parcel_id,
                owner_raw=owner_raw,
                owner_normalized=normalize_name(owner_raw) if owner_raw else None,
                address=address, city=city, state=state, zip=zip_code, county=county,
                geometry_wkt=geometry,
                raw_data=raw_data,
                source_county=source_county,
            ))
            rows_ingested += 1

        rows_seen_since_commit += 1
        if rows_seen_since_commit >= _COMMIT_EVERY:
            db.commit()
            rows_seen_since_commit = 0

    db.commit()

    if skipped > _MAX_COLLECTED_ERRORS:
        errors.append(f"...and {skipped - _MAX_COLLECTED_ERRORS} more rows skipped (truncated)")

    return {"rows_ingested": rows_ingested, "rows_updated": rows_updated, "errors": errors}


def _build_property_index(db: Session, owner_id: int) -> dict:
    properties = db.query(Property).filter(Property.owner_id == owner_id).all()
    return {normalize_address(p.address): p for p in properties if p.address}


def _best_account_match(parcel: ParcelRegrid, accounts: list) -> tuple:
    """rapidfuzz token_sort_ratio of the parcel's normalized owner name
    against every account in scope — same approach as the account-duplicate
    scanner (routers/accounts.py scan_duplicates), reused rather than
    parallel-implemented. O(n_accounts) per parcel; see reconcile()'s
    docstring for the scale caveat this inherits from that scanner."""
    best_account, best_score = None, 0
    parcel_norm = parcel.owner_normalized or ''
    for acct in accounts:
        score = fuzz.token_sort_ratio(parcel_norm, acct.normalized_name or '')
        if score > best_score:
            best_score, best_account = score, acct
    return best_account, best_score


def _parcel_evidence(parcel: ParcelRegrid) -> dict:
    return {
        "parcel_id": parcel.parcel_id,
        "owner_raw": parcel.owner_raw,
        "address": parcel.address,
        "city": parcel.city,
        "state": parcel.state,
        "zip": parcel.zip,
        "county": parcel.source_county,
    }


def _account_evidence(acct: Account) -> dict:
    return {
        "id": acct.id, "name": acct.name,
        "address": acct.address, "city": acct.city, "state": acct.state,
    }


def _apply_auto_link(db: Session, parcel: ParcelRegrid, account: Account, prop: Optional[Property]):
    parcel.matched_account_id = account.id
    parcel.reconciliation_status = "auto_linked"
    if prop is not None:
        parcel.matched_property_id = prop.id
        prop.recorded_owner_account_id = account.id
    ensure_role(account, "owner")


def _account_from_parcel_owner(owner_id: int, parcel: ParcelRegrid) -> Account:
    """Builds (not yet added/committed) a fresh Account from a parcels_regrid
    row's raw owner string. Shared by create_account_from_suggestion() (the
    reconcile()/Suggestions flow) and create_and_link_account_from_parcel_owner()
    below (the ad-hoc Public Record "Use this" owner-accept action,
    routers/finder.py) — one real implementation of account-from-owner-string,
    not two copies.

    Address is the OWNER's mailing address (raw_data's mailadd/mail_city/
    mail_state2/mail_zip — confirmed real, populated Regrid columns, not
    promoted to dedicated ParcelRegrid columns, so read from raw_data
    directly) when present, not the parcel's own site address
    (ParcelRegrid.address/city/state/zip) — a property's owner, especially
    an out-of-state LLC, very often has a different mailing address than
    the property it owns, and the Property record already stores the site
    address itself, so copying it onto the Account too would be redundant
    at best and misleading at worst. Falls back to the parcel's site
    address only when no mailing-address field is present at all, rather
    than leaving a newly created Account with no address whatsoever.
    Account's own columns are plain `address`/`city`/`state`/`zip` (checked
    directly against models/account.py) — no "mailing_" prefix on that
    side, so no renaming needed, just the right source fields.
    """
    raw_data = parcel.raw_data or {}
    mail_address = raw_data.get("mailadd") or None
    mail_city    = raw_data.get("mail_city") or None
    mail_state   = raw_data.get("mail_state2") or None
    mail_zip     = raw_data.get("mail_zip") or None
    has_mailing_address = any([mail_address, mail_city, mail_state, mail_zip])

    return Account(
        owner_id=owner_id,
        name=parcel.owner_raw or f"Unknown Owner — Parcel {parcel.parcel_id}",
        normalized_name=normalize_name(parcel.owner_raw or ''),
        address=mail_address if has_mailing_address else parcel.address,
        city=mail_city if has_mailing_address else parcel.city,
        state=mail_state if has_mailing_address else parcel.state,
        zip=mail_zip if has_mailing_address else parcel.zip,
        roles=["owner"],
    )


def reconcile(db: Session, owner_id: int, county: Optional[str] = None,
              auto_create_accounts: bool = False) -> dict:
    """Owner-scoped reconciliation pass over pending parcels_regrid rows.

    Moderate decision thresholds:
      owner_score >= 95 AND address matches an existing property -> auto-link
      owner_score >= 65 (and not auto-linked)                    -> suggested
      otherwise                                                   -> no_match
                                       (+ optional auto_create_accounts)

    O(pending_rows * owner_accounts) — same nested-loop tradeoff the
    account-duplicate scanner already accepts at this codebase's current
    scale (see that function's docstring). A full-county run (Wayne
    County alone is several hundred thousand parcels) against an owner
    with many accounts will be slow; blocking/batching is not built here,
    same "out of scope for this pass" call the duplicate scanner already
    made. Scope reconcile calls by county to keep each call bounded.

    matched_account_id/matched_property_id on parcels_regrid are single
    columns, not owner-scoped (the table itself has no owner_id — see
    CLAUDE.md). If this app ever has multiple owner_ids reconciling
    against the *same* county's data, the first owner to resolve a row
    flips its status away from 'pending' and no other owner's reconcile
    call will ever see that row again. Fine for a single-broker
    deployment; would need an owner-scoped junction table (like
    property_parties, not a single FK column) to support more than one.
    """
    query = db.query(ParcelRegrid).filter(ParcelRegrid.reconciliation_status == "pending")
    if county:
        query = query.filter(ParcelRegrid.source_county.ilike(county))
    pending = query.all()

    accounts = owned_accounts_query(db, owner_id).all()
    for acct in accounts:
        if not acct.normalized_name:
            acct.normalized_name = normalize_name(acct.name)

    property_by_addr = _build_property_index(db, owner_id)

    processed = auto_linked = suggested = no_match = accounts_created = 0

    for parcel in pending:
        best_account, best_score = _best_account_match(parcel, accounts)
        norm_addr = normalize_address(parcel.address) if parcel.address else ''
        matched_property = property_by_addr.get(norm_addr) if norm_addr else None

        if best_account is not None and best_score >= AUTO_LINK_THRESHOLD and matched_property is not None:
            _apply_auto_link(db, parcel, best_account, matched_property)
            auto_linked += 1

        elif best_account is not None and best_score >= SUGGEST_THRESHOLD:
            parcel.reconciliation_status = "suggested"
            db.add(Suggestion(
                owner_id=owner_id,
                suggestion_type="regrid_owner_match",
                entity_id_a=best_account.id,
                entity_id_b=None,
                score=round(best_score, 2),
                reasoning=f"{round(best_score)}% owner-name match against Regrid parcel {parcel.parcel_id}",
                evidence={
                    "parcel_regrid_id": parcel.id,
                    "parcel": _parcel_evidence(parcel),
                    "candidate_account": _account_evidence(best_account),
                    "address_matched_property_id": matched_property.id if matched_property else None,
                },
            ))
            suggested += 1

        else:
            parcel.reconciliation_status = "no_match"
            no_match += 1
            if auto_create_accounts:
                new_account = Account(
                    owner_id=owner_id,
                    name=parcel.owner_raw or f"Unknown Owner — Parcel {parcel.parcel_id}",
                    normalized_name=normalize_name(parcel.owner_raw or ''),
                    address=parcel.address, city=parcel.city, state=parcel.state, zip=parcel.zip,
                    roles=["owner"],
                )
                db.add(new_account)
                db.flush()
                parcel.matched_account_id = new_account.id
                if matched_property is not None:
                    parcel.matched_property_id = matched_property.id
                    matched_property.recorded_owner_account_id = new_account.id
                accounts_created += 1

        processed += 1

    db.commit()

    result = {"processed": processed, "auto_linked": auto_linked,
              "suggested": suggested, "no_match": no_match}
    if auto_create_accounts:
        result["accounts_created"] = accounts_created
    return result


def confirm_suggestion(db: Session, owner_id: int, suggestion: Suggestion) -> dict:
    """Applies a 'regrid_owner_match' suggestion's candidate account exactly
    like an auto-link would have, then resolves the suggestion. Caller
    (routers/regrid.py) has already validated suggestion.owner_id == owner_id
    and suggestion.suggestion_type == 'regrid_owner_match'."""
    parcel_id = (suggestion.evidence or {}).get("parcel_regrid_id")
    parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == parcel_id).first() if parcel_id else None
    if parcel is None:
        raise ValueError("Linked parcels_regrid row no longer exists")

    account = db.query(Account).filter(
        Account.id == suggestion.entity_id_a, Account.owner_id == owner_id).first()
    if account is None:
        raise ValueError("Candidate account no longer exists")

    matched_property = None
    prop_id = (suggestion.evidence or {}).get("address_matched_property_id")
    if prop_id:
        matched_property = db.query(Property).filter(
            Property.id == prop_id, Property.owner_id == owner_id).first()

    _apply_auto_link(db, parcel, account, matched_property)

    suggestion.status = "merged"
    suggestion.resolved_at = datetime.now(timezone.utc)
    db.commit()

    return {"matched_account_id": account.id,
            "matched_property_id": matched_property.id if matched_property else None}


def create_account_from_suggestion(db: Session, owner_id: int, suggestion: Suggestion) -> dict:
    """"Create as new account" action — the parcel's owner clearly isn't
    any existing account (or the broker just prefers a fresh one), so
    create one from the Regrid owner string instead of confirming the
    fuzzy candidate."""
    parcel_id = (suggestion.evidence or {}).get("parcel_regrid_id")
    parcel = db.query(ParcelRegrid).filter(ParcelRegrid.id == parcel_id).first() if parcel_id else None
    if parcel is None:
        raise ValueError("Linked parcels_regrid row no longer exists")

    new_account = _account_from_parcel_owner(owner_id, parcel)
    db.add(new_account)
    db.flush()

    matched_property = None
    prop_id = (suggestion.evidence or {}).get("address_matched_property_id")
    if prop_id:
        matched_property = db.query(Property).filter(
            Property.id == prop_id, Property.owner_id == owner_id).first()

    # Reuses _apply_auto_link() rather than re-setting matched_account_id/
    # reconciliation_status/recorded_owner_account_id by hand (as this
    # function did before) — also fixes a real gap this refactor surfaced:
    # the hand-rolled version never called ensure_role(), so an account
    # created this way could end up linked as recorded_owner_account_id
    # without ever getting the 'owner' role tag, unlike every other linking
    # path in this file.
    _apply_auto_link(db, parcel, new_account, matched_property)

    suggestion.status = "merged"
    suggestion.resolved_at = datetime.now(timezone.utc)
    db.commit()

    return {"account_id": new_account.id,
            "matched_property_id": matched_property.id if matched_property else None}


def create_and_link_account_from_parcel_owner(db: Session, owner_id: int,
                                               parcel: ParcelRegrid, prop: Property) -> dict:
    """Ad-hoc "Use this" owner-accept action from the property detail Public
    Record tab (routers/finder.py's accept_public_record_owner) — same
    account-creation + link mechanics as create_account_from_suggestion()
    above (_account_from_parcel_owner() + _apply_auto_link()), just
    triggered directly from an already address-matched (property, parcel)
    pair instead of a batch-reconcile Suggestion row.

    This is a deliberately different trigger path, not a duplicate one:
    reconcile()'s Suggestion rows only get created when the parcel's owner
    name scores >= SUGGEST_THRESHOLD (65) against an existing account.
    A property whose recorded owner has genuinely changed (e.g. "JMC
    Management, LLC" vs. Regrid's "LEGRA PROPERTIES LLC") scores nowhere
    near that threshold, lands in reconcile()'s no_match branch, and would
    never produce a Suggestion for a broker to act on — this function is
    the direct-correction path for exactly that case, called from the
    Public Record tab the moment a broker notices the mismatch themselves.

    Also fills prop.account_id ("current owner entity" — the field the
    Summary tab's "Owner" card and the Contacts tab actually read, a
    different field from recorded_owner_account_id) when it's currently
    null. Fill-blank-only, deliberately NOT a general sync between the two
    fields: account_id can legitimately diverge from the deed-of-record
    owner (e.g. a sale not yet reflected in county records), so an
    already-set account_id is never overwritten here. This only helps the
    specific case a property has no owner link at all yet — accepting the
    Public Record owner is, in that case, the only owner information the
    property has, so it makes sense for both fields to end up pointing at
    it rather than leaving account_id null and the Owner card/Contacts tab
    looking unpopulated right after a broker just confirmed the owner.
    """
    new_account = _account_from_parcel_owner(owner_id, parcel)
    db.add(new_account)
    db.flush()
    _apply_auto_link(db, parcel, new_account, prop)
    if prop.account_id is None:
        prop.account_id = new_account.id
    db.commit()
    return {"account_id": new_account.id, "account_name": new_account.name}
