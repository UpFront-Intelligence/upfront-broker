#!/usr/bin/env python3
"""Oakland County Regrid pilot: ingest + data quality check + CRM reconcile.

Usage:
    PROD_DATABASE_URL="postgresql://..." python3 scripts/ingest_regrid_oakland.py

Reads PROD_DATABASE_URL from environment only — never hardcoded.
Does NOT print the connection string.

Three steps, all instrumented:
  1. Ingest mi_oakland.csv.gz into parcels_regrid (stream-decompress, batch UPSERT)
  2. Data quality: JOIN parcels_regrid vs old parcels table — is the parcel ID
     format the same? What % overlap?
  3. CRM reconciler: match Regrid owners against broker accounts/properties.
"""
import csv
import gzip
import io
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPTS_DIR)

import psycopg2
import psycopg2.extras

GZ_PATH       = "/Users/michaelsw/Desktop/REGRID DATA DONT MOVE/mi_oakland.csv.gz"
SOURCE_COUNTY = "mi_oakland"
BATCH_SIZE    = 1000
MAX_ERRORS    = 50

# ── Column candidates (confirmed against mi_oakland.csv.gz 2026-06-29) ───────
_PARCEL_ID_KEYS = ('parcelnumb', 'parcelnumb_no_formatting', 'state_parcelnumb',
                   'account_number', 'tax_id')
_OWNER_KEYS     = ('owner',)
_ADDRESS_KEYS   = ('address',)
_CITY_KEYS      = ('city', 'scity')
_STATE_KEYS     = ('state2', 'state')
_ZIP_KEYS       = ('szip5', 'szip', 'zip')
_COUNTY_KEYS    = ('county', 'county_name')
_GEOMETRY_KEYS  = ('wkt', 'geometry', 'geom')

_ALL_CRITICAL = frozenset(
    _PARCEL_ID_KEYS + _OWNER_KEYS + _ADDRESS_KEYS + _CITY_KEYS
    + _STATE_KEYS + _ZIP_KEYS + _COUNTY_KEYS + _GEOMETRY_KEYS
)

UPSERT_SQL = """
INSERT INTO parcels_regrid
  (parcel_id, owner_raw, owner_normalized, address, city, state, zip, county,
   geometry_wkt, raw_data, source_county, reconciliation_status)
VALUES %s
ON CONFLICT (parcel_id, source_county) DO UPDATE SET
  owner_raw         = EXCLUDED.owner_raw,
  owner_normalized  = EXCLUDED.owner_normalized,
  address           = EXCLUDED.address,
  city              = EXCLUDED.city,
  state             = EXCLUDED.state,
  zip               = EXCLUDED.zip,
  county            = EXCLUDED.county,
  geometry_wkt      = EXCLUDED.geometry_wkt,
  raw_data          = EXCLUDED.raw_data
RETURNING (xmax = 0) AS was_insert
"""


def _get_db_url():
    url = os.environ.get("PROD_DATABASE_URL", "").strip()
    if not url:
        sys.exit("ERROR: set PROD_DATABASE_URL as an env var for this invocation.")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _first(row, keys):
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return None


def _normalize_name(name: str) -> str:
    from services.naming import normalize_name as _nn
    return _nn(name)


# ── STEP 1: INGEST ────────────────────────────────────────────────────────────

def step1_ingest(db_url: str) -> dict:
    print("\n" + "="*70)
    print(f"STEP 1: INGEST  ({datetime.now():%H:%M:%S})")
    print(f"  Source: {GZ_PATH}")
    print(f"  County: {SOURCE_COUNTY}  |  Batch: {BATCH_SIZE}")
    print("="*70)

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    pg   = conn.cursor()

    rows_seen = rows_inserted = rows_updated = rows_skipped = 0
    errors = []
    batch  = []
    t0     = time.time()
    last_print = t0

    with gzip.open(GZ_PATH, 'rb') as gz:
        text_stream = io.TextIOWrapper(gz, encoding='utf-8-sig', newline='')
        reader = csv.DictReader(text_stream)

        for row_num, raw in enumerate(reader, start=2):
            rows_seen += 1

            # Lowercase-key lookup (header already lowercase in this file)
            row = {(k or '').strip().lower(): v for k, v in raw.items() if k is not None}

            parcel_id = _first(row, _PARCEL_ID_KEYS)
            if not parcel_id:
                rows_skipped += 1
                if len(errors) < MAX_ERRORS:
                    errors.append(f"Row {row_num}: missing parcel_id")
                continue

            owner_raw = _first(row, _OWNER_KEYS)
            address   = _first(row, _ADDRESS_KEYS)
            city      = _first(row, _CITY_KEYS)
            state     = _first(row, _STATE_KEYS)
            zip_code  = _first(row, _ZIP_KEYS)
            county    = _first(row, _COUNTY_KEYS)
            geometry  = _first(row, _GEOMETRY_KEYS)
            raw_data  = json.dumps({k: v for k, v in row.items()
                                    if k not in _ALL_CRITICAL and v})

            try:
                owner_norm = _normalize_name(owner_raw) if owner_raw else None
            except Exception:
                owner_norm = None

            batch.append((
                parcel_id, owner_raw, owner_norm, address, city, state,
                zip_code, county, geometry, raw_data, SOURCE_COUNTY, 'pending',
            ))

            if len(batch) >= BATCH_SIZE:
                rows_inserted, rows_updated = _flush(pg, batch, rows_inserted, rows_updated)
                conn.commit()
                batch.clear()
                now = time.time()
                if now - last_print >= 10:
                    elapsed = now - t0
                    rate = rows_seen / elapsed
                    print(f"  …{rows_seen:,} read  {rows_inserted:,} new  {rows_updated:,} updated"
                          f"  {elapsed:.0f}s  ({rate:.0f} rows/s)")
                    last_print = now

        if batch:
            rows_inserted, rows_updated = _flush(pg, batch, rows_inserted, rows_updated)
            conn.commit()

    elapsed = time.time() - t0

    # Post-ingest count
    pg.execute("SELECT COUNT(*) FROM parcels_regrid WHERE source_county = %s", (SOURCE_COUNTY,))
    (count_in_db,) = pg.fetchone()

    # 3 sample rows
    pg.execute("""
        SELECT parcel_id, owner_raw, address, zip, state,
               geometry_wkt IS NOT NULL,
               SUBSTRING(geometry_wkt,1,80)
        FROM parcels_regrid WHERE source_county = %s ORDER BY id LIMIT 3
    """, (SOURCE_COUNTY,))
    samples = pg.fetchall()

    conn.close()

    print(f"\n  Rows read:     {rows_seen:,}")
    print(f"  Inserted new:  {rows_inserted:,}")
    print(f"  Updated:       {rows_updated:,}")
    print(f"  Skipped/err:   {rows_skipped:,}")
    print(f"  Errors ({len(errors)}):  " + ('; '.join(errors[:3]) if errors else 'none'))
    print(f"  Elapsed:       {elapsed:.1f}s  ({rows_seen/elapsed:.0f} rows/s)")
    print(f"  DB count (mi_oakland): {count_in_db:,}")
    print("\n  --- 3 sample rows ---")
    for s in samples:
        print(f"  parcel={s[0]}  owner={s[1]!r}")
        print(f"    addr={s[2]!r}  zip={s[3]}  state={s[4]}  wkt={'YES' if s[5] else 'NULL'}")
        if s[5]:
            print(f"    wkt: {s[6]}…")

    return {"seen": rows_seen, "inserted": rows_inserted, "updated": rows_updated,
            "skipped": rows_skipped, "count_in_db": count_in_db, "elapsed": elapsed}


def _flush(pg, batch, inserted, updated):
    psycopg2.extras.execute_values(
        pg, UPSERT_SQL.rstrip() + "\nRETURNING (xmax = 0) AS was_insert", batch, page_size=len(batch)
    )
    results = pg.fetchall()
    inserted += sum(1 for r in results if r[0])
    updated  += sum(1 for r in results if not r[0])
    return inserted, updated


# ── STEP 2: DATA QUALITY vs OLD parcels TABLE ─────────────────────────────────

def step2_quality(db_url: str):
    print("\n" + "="*70)
    print(f"STEP 2: DATA QUALITY vs OLD parcels TABLE  ({datetime.now():%H:%M:%S})")
    print("="*70)

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    pg   = conn.cursor()

    pg.execute("SELECT COUNT(*) FROM parcels")
    (old_count,) = pg.fetchone()
    print(f"  Old parcels table rows: {old_count:,}")

    if old_count == 0:
        print("  ⚠️  Old parcels table is EMPTY — cannot do ground-truth comparison.")
        print("  The old parcels table needs to be populated with Oakland ArcGIS data")
        print("  (scripts/import_parcels.py) to enable this comparison.")
        conn.close()
        return

    # Sample parcel IDs from both tables to compare format
    pg.execute("SELECT keypin FROM parcels LIMIT 8")
    old_keys = [r[0] for r in pg.fetchall()]
    pg.execute("SELECT parcel_id FROM parcels_regrid WHERE source_county = %s LIMIT 8", (SOURCE_COUNTY,))
    new_keys = [r[0] for r in pg.fetchall()]
    print(f"\n  Old parcels keypin samples:   {old_keys}")
    print(f"  Regrid parcel_id samples:    {new_keys}")

    # Exact match
    pg.execute("""
        SELECT COUNT(*) FROM parcels p
        JOIN parcels_regrid r ON p.keypin = r.parcel_id
        WHERE r.source_county = %s
    """, (SOURCE_COUNTY,))
    (exact,) = pg.fetchone()
    pct = 100 * exact / old_count if old_count else 0
    print(f"\n  Exact join (keypin = parcel_id): {exact:,}  ({pct:.1f}% of old parcels)")

    if pct < 10:
        print("\n  ⛔  MATCH RATE BELOW 10% — likely a parcel ID format mismatch.")
        print("  Inspect the sample values above before proceeding.")

    # 5 matching examples
    if exact > 0:
        pg.execute("""
            SELECT p.keypin, p.siteaddress, r.parcel_id, r.address, r.owner_raw
            FROM parcels p
            JOIN parcels_regrid r ON p.keypin = r.parcel_id
            WHERE r.source_county = %s
            LIMIT 5
        """, (SOURCE_COUNTY,))
        matches = pg.fetchall()
        print("\n  --- 5 matching rows (auto-link ground truth) ---")
        for m in matches:
            print(f"  old keypin={m[0]}  old addr={m[1]!r}")
            print(f"    regrid  ={m[2]}  regrid addr={m[3]!r}  owner={m[4]!r}")

    # 5 no-match examples
    pg.execute("""
        SELECT p.keypin, p.siteaddress, p.classcode
        FROM parcels p
        LEFT JOIN parcels_regrid r ON p.keypin = r.parcel_id AND r.source_county = %s
        WHERE r.id IS NULL
        LIMIT 5
    """, (SOURCE_COUNTY,))
    no_matches = pg.fetchall()
    if no_matches:
        print("\n  --- 5 in old parcels but NOT found in Regrid ---")
        for n in no_matches:
            print(f"  keypin={n[0]}  addr={n[1]!r}  classcode={n[2]}")

    conn.close()


# ── STEP 3: CRM RECONCILER ────────────────────────────────────────────────────

def step3_reconcile(db_url: str):
    print("\n" + "="*70)
    print(f"STEP 3: CRM RECONCILER  ({datetime.now():%H:%M:%S})")
    print("  Matches parcels_regrid owners against broker accounts/properties.")
    print("  NOTE: match rate here depends on how many broker accounts/properties")
    print("  exist in the CRM for Oakland — not on overlap between the two parcel")
    print("  datasets. Low match rate here = broker has few Oakland CRM records,")
    print("  NOT a data quality problem with the Regrid import.")
    print("="*70)

    os.environ["DATABASE_URL"] = db_url
    from database import SessionLocal
    from sqlalchemy import text as sqla_text
    from services.regrid import reconcile

    db = SessionLocal()

    # Find broker user
    row = db.execute(sqla_text("SELECT id, email FROM users ORDER BY id LIMIT 1")).fetchone()
    if not row:
        print("  ⚠️  No users found — skipping CRM reconcile.")
        db.close()
        return
    user_id, user_email = row
    print(f"  Broker user: {user_email} (id={user_id})")

    # Count broker accounts and Oakland properties
    (acct_count,) = db.execute(sqla_text(
        "SELECT COUNT(*) FROM accounts WHERE owner_id = :u AND merged_into_id IS NULL"
    ), {"u": user_id}).fetchone()
    (prop_count,) = db.execute(sqla_text(
        "SELECT COUNT(*) FROM properties WHERE owner_id = :u"
    ), {"u": user_id}).fetchone()
    (pending,) = db.execute(sqla_text(
        "SELECT COUNT(*) FROM parcels_regrid WHERE source_county = :c AND reconciliation_status = 'pending'"
    ), {"c": SOURCE_COUNTY}).fetchone()
    print(f"  Broker accounts: {acct_count:,}  |  Broker properties: {prop_count:,}")
    print(f"  Pending parcels_regrid rows to process: {pending:,}")
    print(f"\n  Estimated time: ~{pending * acct_count / 1_000_000:.1f}M comparisons"
          f" at ~1μs each = ~{pending * acct_count / 1_000_000:.0f}s")
    print("  Starting…")

    t0 = time.time()
    result = reconcile(db, user_id, county=SOURCE_COUNTY)
    elapsed = time.time() - t0

    processed   = result.get("processed", 0)
    auto_linked = result.get("auto_linked", 0)
    suggested   = result.get("suggested", 0)
    no_match    = result.get("no_match", 0)

    def pct(n): return f"{100*n/processed:.1f}%" if processed else "—"
    print(f"\n  Processed:   {processed:,}")
    print(f"  Auto-linked: {auto_linked:,}  ({pct(auto_linked)})")
    print(f"  Suggested:   {suggested:,}  ({pct(suggested)})")
    print(f"  No-match:    {no_match:,}  ({pct(no_match)})")
    print(f"  Elapsed:     {elapsed:.1f}s")

    if auto_linked > 0:
        rows = db.execute(sqla_text("""
            SELECT r.parcel_id, r.owner_raw, r.address, a.name
            FROM parcels_regrid r
            JOIN accounts a ON r.matched_account_id = a.id
            WHERE r.source_county = :c AND r.reconciliation_status = 'auto_linked'
            LIMIT 5
        """), {"c": SOURCE_COUNTY}).fetchall()
        print("\n  --- 5 auto-linked ---")
        for row in rows:
            print(f"  parcel={row[0]}  regrid_owner={row[1]!r}")
            print(f"    matched_account={row[3]!r}  addr={row[2]!r}")

    if no_match > 0:
        rows = db.execute(sqla_text("""
            SELECT parcel_id, owner_raw, address
            FROM parcels_regrid
            WHERE source_county = :c AND reconciliation_status = 'no_match'
            LIMIT 5
        """), {"c": SOURCE_COUNTY}).fetchall()
        print("\n  --- 5 no-matches (Regrid owners with no matching CRM account) ---")
        for row in rows:
            print(f"  parcel={row[0]}  owner={row[1]!r}  addr={row[2]!r}")

    db.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db_url = _get_db_url()

    print("="*70)
    print(f"Regrid Oakland pilot — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("="*70)

    ingest_result = step1_ingest(db_url)
    step2_quality(db_url)
    step3_reconcile(db_url)

    print("\n" + "="*70)
    print("Done. Review all three steps above before scaling to other counties.")
    print("="*70)


if __name__ == "__main__":
    main()
